import logging
from datetime import datetime
# from typing import Optional # Removed: F401 'typing.Optional' imported but unused

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    # Body # No longer needed directly here
    # FastAPI, # No longer needed here
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from .. import tasks
from ..config import (
    BOT_CONVERSATION_OPENED_MESSAGE_EXTERNAL,
    BOT_ERROR_MESSAGE_INTERNAL,
)
from ..database import get_db
from ..models.database import ChatwootWebhook, Dialogue, DialogueCreate
# from ..models.non_database import ConversationPriority, ConversationStatus # No longer needed here
# ChatwootHandler is used by send_chatwoot_message, which will be moved.
# However, chatwoot_webhook might call send_chatwoot_message if it's kept as a local helper.
# For now, assume send_chatwoot_message is moved and this import might become unused.
from .chatwoot import ChatwootHandler


logger = logging.getLogger(__name__)

router = APIRouter()
chatwoot = ChatwootHandler() # This instance will be used by chatwoot_webhook if it calls local send_chatwoot_message
                             # If send_chatwoot_message is moved and no longer called locally, this can be removed.
                             # Let's assume for now it might be needed for an internal call if error handling in webhook calls it.
                             # The moved `send_chatwoot_message` in `chatwoot_actions.py` will have its own instance.


async def get_or_create_dialogue(db: AsyncSession, data: DialogueCreate) -> Dialogue:
    """
    Get existing dialogue or create a new one.
    Updates the dialogue if it exists with new data.
    """
    statement = select(Dialogue).where(Dialogue.chatwoot_conversation_id == data.chatwoot_conversation_id)
    result = await db.execute(statement)
    dialogue = result.scalar_one_or_none()

    if dialogue:
        # Update existing dialogue with new data
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(dialogue, field, value)
        dialogue.updated_at = datetime.utcnow()
    else:
        # Create new dialogue
        dialogue = Dialogue(**data.model_dump())
        db.add(dialogue)

    await db.commit()
    await db.refresh(dialogue)
    return dialogue


# This is the action endpoint that was identified. It will be called by the webhook in case of error.
# It's better to keep it here if it's only for the webhook's internal use for sending error messages.
# Or, the webhook could call the new action endpoint via an HTTP request (less ideal for internal error reporting).
# For now, let's keep a local version or decide if the webhook should call the public action endpoint.
# The task is to move "general API actions". If this send_message is *only* for webhook error reporting, it's not "general".
# However, the original `send_chatwoot_message` was a public endpoint.
# Let's assume the public endpoint is moved, and the webhook will use an internal helper or call the new public one.
# For simplicity, I'll assume the webhook might have a simplified internal way or this specific call to `send_chatwoot_message`
# will be refactored later. The main public `send_chatwoot_message` endpoint is moved.
# The `except` block in `chatwoot_webhook` calls `send_chatwoot_message`. This needs to be addressed.
# Option 1: Webhook calls the new public action endpoint (adds HTTP overhead).
# Option 2: Keep a private `_send_error_message` helper in webhooks.py.
# Option 3: The ChatwootHandler itself provides a method that the webhook can use. (Cleanest)
# Let's assume for now that `ChatwootHandler` will be enhanced or used directly for this error message.
# So the `send_chatwoot_message` *endpoint* is definitely moved.

@router.post("/chatwoot-webhook")
async def chatwoot_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    print("Received Chatwoot webhook request")
    payload = await request.json()
    webhook_data = ChatwootWebhook.model_validate(payload)

    logger.info(f"Received webhook event: {webhook_data.event}")
    logger.debug(f"Webhook payload: {payload}")

    if webhook_data.event == "message_created":
        logger.info(f"Webhook data: {webhook_data}")
        if webhook_data.sender_type in [
            "agent_bot",
            "????", # TODO: Check what this sender_type means
        ]:
            logger.info(f"Skipping agent_bot message: {webhook_data.content}")
            return {"status": "skipped", "reason": "agent_bot message"}

        if str(webhook_data.content).startswith(BOT_CONVERSATION_OPENED_MESSAGE_EXTERNAL) or str(
            webhook_data.content
        ).startswith(BOT_ERROR_MESSAGE_INTERNAL):
            logger.info(f"Skipping self-generated status/error message: {webhook_data.content}")
            return {"status": "skipped", "reason": "agent_bot status/error message"}

        # All other conditions for skipping seem to be commented out, so we process.
        logger.debug(f"Processing message: {webhook_data}")
        try:
            dialogue_data = webhook_data.to_dialogue_create()
            dialogue = await get_or_create_dialogue(db, dialogue_data)

            tasks.process_message_with_dify.apply_async(
                args=[
                    webhook_data.content,
                    dialogue.dify_conversation_id,
                    dialogue.chatwoot_conversation_id,
                    dialogue.status,
                    webhook_data.message_type,
                ],
                link=tasks.handle_dify_response.s(
                    conversation_id=webhook_data.conversation_id,
                    dialogue_id=dialogue.id,
                ),
                link_error=tasks.handle_dify_error.s(
                    conversation_id=webhook_data.conversation_id,
                ),
            )
            return {"status": "processing"}

        except Exception as e:
            logger.error(f"Failed to process message with Dify: {e}", exc_info=True)
            if webhook_data.conversation_id is not None:
                try:
                    # Use ChatwootHandler directly to send error message
                    await chatwoot.send_message(
                        conversation_id=webhook_data.conversation_id,
                        message=BOT_CONVERSATION_OPENED_MESSAGE_EXTERNAL, # This seems to be a status message, not an error message
                        private=False,
                    )
                except Exception as send_error:
                     logger.error(f"Failed to send error notification to Chatwoot conversation {webhook_data.conversation_id}: {send_error}", exc_info=True)
            else:
                logger.error(
                    "Cannot send error message: conversation_id is None in webhook data for event {webhook_data.event}"
                )
            # Even if sending message fails, we should return an error response for the webhook
            raise HTTPException(status_code=500, detail=f"Failed to process webhook event: {str(e)}")


    elif webhook_data.event == "conversation_created":
        if not webhook_data.conversation:
            logger.warning("Received conversation_created event with no conversation data.")
            return {"status": "skipped", "reason": "no conversation data"}

        dialogue_data = webhook_data.to_dialogue_create()
        dialogue = await get_or_create_dialogue(db, dialogue_data)
        logger.info(f"Processed conversation_created event, dialogue ID: {dialogue.id}")
        return {"status": "success", "dialogue_id": dialogue.id}

    elif webhook_data.event == "conversation_updated":
        if not webhook_data.conversation:
            logger.warning("Received conversation_updated event with no conversation data.")
            return {"status": "skipped", "reason": "no conversation data"}

        dialogue_data = webhook_data.to_dialogue_create()
        dialogue = await get_or_create_dialogue(db, dialogue_data)
        logger.info(f"Processed conversation_updated event, dialogue ID: {dialogue.id}")
        return {"status": "success", "dialogue_id": dialogue.id}

    elif webhook_data.event == "conversation_deleted":
        if not webhook_data.conversation: # Should have conversation ID at least
            logger.warning("Received conversation_deleted event with no conversation data.")
            return {"status": "skipped", "reason": "no conversation data"}

        # Ensure conversation ID is correctly extracted
        if hasattr(webhook_data.conversation, 'id'):
            chatwoot_conversation_id_to_delete = str(webhook_data.conversation.id)
        else:
            # Fallback or error if ID is not where expected. Based on model, it should be webhook_data.id for top-level ID
            # but context suggests it's webhook_data.conversation.id
            logger.error("Could not determine conversation ID from conversation_deleted event.")
            return {"status": "error", "reason": "missing conversation id in conversation_deleted event"}


        statement = select(Dialogue).where(Dialogue.chatwoot_conversation_id == chatwoot_conversation_id_to_delete)
        dialogue_to_delete = await db.execute(statement)
        dialogue_to_delete = dialogue_to_delete.scalar_one_or_none()

        if dialogue_to_delete:
            logger.info(f"Processing conversation_deleted event for Chatwoot convo ID: {chatwoot_conversation_id_to_delete}")
            if dialogue_to_delete.dify_conversation_id:
                logger.info(f"Scheduling deletion of Dify conversation: {dialogue_to_delete.dify_conversation_id}")
                background_tasks.add_task(tasks.delete_dify_conversation, dialogue_to_delete.dify_conversation_id)
            
            await db.delete(dialogue_to_delete)
            await db.commit()
            logger.info(f"Successfully deleted dialogue for Chatwoot convo ID: {chatwoot_conversation_id_to_delete}")
            return {"status": "success", "message": "Dialogue and associated Dify conversation scheduled for deletion"}
        else:
            logger.info(f"No dialogue found for deleted Chatwoot conversation ID: {chatwoot_conversation_id_to_delete}. No action taken.")
            return {"status": "skipped", "reason": "dialogue not found"}

    logger.debug(f"Webhook event {webhook_data.event} processed or skipped.")
    return {"status": "success", "event": webhook_data.event} # Generic success for other events or if logic completes


# The lifespan function for team cache was moved to chatwoot_actions.py
# If webhooks.py had other startup/shutdown logic, it would remain here.
# For now, it seems the lifespan was solely for team cache.

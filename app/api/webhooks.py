import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    FastAPI,
    HTTPException,
    Request,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app import tasks
from app.api.chatwoot import ChatwootHandler
from app.config import (
    BOT_CONVERSATION_OPENED_MESSAGE_EXTERNAL,
    BOT_ERROR_MESSAGE_INTERNAL,
    ENABLE_TEAM_CACHE,
    TEAM_CACHE_TTL_HOURS,
)
from app.db.session import get_session
from app.db.utils import create_db_tables
from app.models import Conversation, ConversationCreate, ConversationResponse
from app.schemas import (
    ChatwootWebhook,
    ConversationPriority,
    ConversationStatus,
)
from app.utils import handle_api_errors

logger = logging.getLogger(__name__)

router = APIRouter()
chatwoot = ChatwootHandler()

# Team management - only initialize if caching is enabled
team_cache: Dict[str, int] = {} if ENABLE_TEAM_CACHE else {}
team_cache_lock = asyncio.Lock() if ENABLE_TEAM_CACHE else None
last_update_time = 0


async def get_or_create_conversation(db: AsyncSession, data: ConversationCreate) -> Conversation:
    """
    Get existing conversation or create a new one.
    Updates the conversation if it exists with new data.
    Uses optimized SQLAlchemy 2.x query patterns.
    """
    # Use SQLAlchemy 2.x select syntax with proper type hints
    statement = select(Conversation).where(Conversation.chatwoot_conversation_id == data.chatwoot_conversation_id)
    result = await db.execute(statement)
    conversation = result.scalar_one_or_none()

    if conversation:
        # Update existing conversation with new data using Pydantic model_dump
        update_data = data.model_dump(exclude_unset=True, exclude={"id"})
        for field, value in update_data.items():
            if hasattr(conversation, field):
                setattr(conversation, field, value)
        conversation.updated_at = datetime.now(UTC)
    else:
        # Create new conversation using Pydantic model_dump
        conversation_data = data.model_dump(exclude={"id"})
        conversation = Conversation(**conversation_data)
        db.add(conversation)

        # Flush to populate auto-generated fields (id, created_at, updated_at)
        # This ensures the database assigns the auto-increment ID and timestamps
        await db.flush()

        # Refresh to ensure all fields are loaded from the database
        await db.refresh(conversation)

    # Note: No manual commit needed - six-line pattern handles this automatically
    # The transaction will be committed when the context manager exits successfully
    return conversation


@router.post("/send-chatwoot-message")
@handle_api_errors("send Chatwoot message")
async def send_chatwoot_message(
    conversation_id: int,
    message: str,
    is_private: bool = False,
) -> Dict[str, str]:
    """
    Send a message to Chatwoot conversation.
    Can be used as a private note if is_private=True
    """
    # For private notes, we need to set both private=True and message_type="private"
    await chatwoot.send_message(
        conversation_id=conversation_id,
        message=message,
        private=is_private,
    )
    return {"status": "success", "message": "Message sent successfully"}


@router.post("/chatwoot-webhook")
async def chatwoot_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    """Process Chatwoot webhook events."""
    webhook_data = None

    try:
        print("Received Chatwoot webhook request")
        payload = await request.json()

        # Use Pydantic v2 model_validate for webhook data validation
        webhook_data = ChatwootWebhook.model_validate(payload)

        logger.info(f"Received webhook event: {webhook_data.event}")
        logger.debug(f"Webhook payload: {payload}")

        if webhook_data.event == "message_created":
            if webhook_data.message_type not in ("incoming", "outgoing"):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "Validation error",
                        "message": "message_type is required for message_created events",
                    },
                )
            logger.info(f"Webhook data: {webhook_data}")
            if webhook_data.sender_type in [
                "agent_bot",
                "????",
            ]:  # бот не реагирует на свои мессаги
                logger.info(f"Skipping agent_bot message: {webhook_data.content}")
                return {"status": "skipped", "reason": "agent_bot message"}

            if str(webhook_data.content).startswith(BOT_CONVERSATION_OPENED_MESSAGE_EXTERNAL) or str(
                webhook_data.content
            ).startswith(BOT_ERROR_MESSAGE_INTERNAL):
                logger.info(f"Skipping agent_bot message: {webhook_data.content}")
                return {"status": "skipped", "reason": "agent_bot message"}

            if True:  # we'll see if we need to filter by status later
                print(f"Processing message: {webhook_data}")
                try:
                    conversation_data = webhook_data.to_conversation_create()
                    conversation = await get_or_create_conversation(db, conversation_data)

                    # Start the task and return immediately
                    tasks.process_message_with_dify.apply_async(
                        args=[
                            webhook_data.content,
                            conversation.dify_conversation_id,
                            conversation.chatwoot_conversation_id,
                            conversation.status,
                            webhook_data.message_type,
                        ],
                        link=tasks.handle_dify_response.s(
                            conversation_id=webhook_data.conversation_id,
                        ),
                        link_error=tasks.handle_dify_error.s(
                            conversation_id=webhook_data.conversation_id,
                        ),
                    )

                    return {"status": "processing"}

                except Exception as e:
                    logger.error(f"Failed to process message with Dify: {e}", exc_info=True)

                    # Try to send error message to Chatwoot if conversation_id is available
                    if webhook_data and webhook_data.conversation_id is not None:
                        try:
                            await chatwoot.send_message(
                                conversation_id=webhook_data.conversation_id,
                                message=BOT_CONVERSATION_OPENED_MESSAGE_EXTERNAL,
                                private=False,
                            )
                        except Exception as send_error:
                            logger.error(f"Failed to send error message to Chatwoot: {send_error}")

                    # Re-raise the original exception to trigger proper error handling
                    raise

        elif webhook_data.event == "conversation_created":
            if not webhook_data.conversation:
                return {"status": "skipped", "reason": "no conversation data"}

            conversation_data = webhook_data.to_conversation_create()
            conversation = await get_or_create_conversation(db, conversation_data)
            return {"status": "success", "conversation_id": conversation.id}

        elif webhook_data.event == "conversation_updated":
            if not webhook_data.conversation:
                return {"status": "skipped", "reason": "no conversation data"}

            conversation_data = webhook_data.to_conversation_create()
            conversation = await get_or_create_conversation(db, conversation_data)
            return {"status": "success", "conversation_id": conversation.id}

        elif webhook_data.event == "conversation_deleted":
            if not webhook_data.conversation:
                return {"status": "skipped", "reason": "no conversation data"}

            conversation_id = str(webhook_data.conversation.id)
            statement = select(Conversation).where(Conversation.chatwoot_conversation_id == conversation_id)
            result = await db.execute(statement)
            conversation = result.scalar_one_or_none()

            if conversation and conversation.dify_conversation_id:
                background_tasks.add_task(tasks.delete_dify_conversation, conversation.dify_conversation_id)
                await db.delete(conversation)
                # Note: No manual commit needed - six-line pattern handles this automatically

        return {"status": "success"}

    except ValueError as e:
        # Pydantic validation errors or other value-related errors
        logger.error(f"Validation error in webhook: {e}", exc_info=True)
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Validation error",
                "message": str(e),
                "event": webhook_data.event if webhook_data else "unknown",
            },
        ) from e

    except Exception as e:
        # Database errors (including transaction errors) and other unexpected errors
        logger.error(f"Unexpected error in webhook processing: {e}", exc_info=True)

        # For database transaction errors, the six-line pattern will handle rollback automatically
        # We just need to provide a proper error response

        error_detail = {
            "error": "Internal server error",
            "message": "Failed to process webhook",
            "event": webhook_data.event if webhook_data else "unknown",
        }

        # Include conversation_id in error response if available for debugging
        if webhook_data and hasattr(webhook_data, "conversation_id") and webhook_data.conversation_id:
            error_detail["conversation_id"] = webhook_data.conversation_id

        raise HTTPException(status_code=500, detail=error_detail) from e


@router.post("/update-labels/{conversation_id}")
@handle_api_errors("update labels")
async def update_labels(
    conversation_id: int, labels: List[str], db: AsyncSession = Depends(get_session)
) -> Dict[str, Any]:
    """Update labels for a Chatwoot conversation."""
    result = await chatwoot.add_labels(conversation_id, labels)
    return {"status": "success", "labels": labels, "result": result}


@router.post("/update-custom-attributes/{conversation_id}")
@handle_api_errors("update custom attributes")
async def update_custom_attributes(
    conversation_id: int,
    custom_attributes: Dict[str, Any],
    db: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    """Update custom attributes for a Chatwoot conversation."""
    result = await chatwoot.update_custom_attributes(conversation_id, custom_attributes)

    # Update local conversation record if it exists
    statement = select(Conversation).where(Conversation.chatwoot_conversation_id == str(conversation_id))
    result_db = await db.execute(statement)
    conversation = result_db.scalar_one_or_none()

    if conversation:
        conversation.updated_at = datetime.now(UTC)
        # Note: No manual commit needed - six-line pattern handles this automatically

    return {
        "status": "success",
        "conversation_id": conversation_id,
        "custom_attributes": custom_attributes,
        "result": result,
    }


@router.post("/toggle-priority/{conversation_id}")
@handle_api_errors("toggle conversation priority")
async def toggle_conversation_priority(
    conversation_id: int,
    priority: ConversationPriority = Body(
        ...,
        embed=True,
        description="Priority level: 'urgent', 'high', 'medium', 'low', or None",
    ),
    db: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    """Toggle the priority of a Chatwoot conversation."""
    # Convert enum to string value for Chatwoot API
    priority_value = priority.value if priority else None
    result = await chatwoot.toggle_priority(conversation_id, priority_value)

    # Update local conversation record if it exists
    statement = select(Conversation).where(Conversation.chatwoot_conversation_id == str(conversation_id))
    result_db = await db.execute(statement)
    conversation = result_db.scalar_one_or_none()

    if conversation:
        conversation.updated_at = datetime.now(UTC)
        # Note: No manual commit needed - six-line pattern handles this automatically

    return {
        "status": "success",
        "conversation_id": conversation_id,
        "priority": priority_value,
        "result": result,
    }


@router.get("/conversations/dify/{dify_conversation_id}")
@handle_api_errors("get conversation by Dify ID")
async def get_chatwoot_conversation_id(
    dify_conversation_id: str, db: AsyncSession = Depends(get_session)
) -> ConversationResponse:
    """Get Chatwoot conversation ID from Dify conversation ID using proper response serialization."""
    statement = select(Conversation).where(Conversation.dify_conversation_id == dify_conversation_id)
    result = await db.execute(statement)
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Use Pydantic v2 model_validate with from_attributes for proper serialization
    return ConversationResponse.model_validate(conversation, from_attributes=True)


@router.get("/conversation-info/{chatwoot_conversation_id}")
@handle_api_errors("get conversation info")
async def get_conversation_info(
    chatwoot_conversation_id: int, db: AsyncSession = Depends(get_session)
) -> ConversationResponse:
    """Get conversation information using optimized query and proper response serialization."""
    statement = select(Conversation).where(Conversation.chatwoot_conversation_id == str(chatwoot_conversation_id))
    result = await db.execute(statement)
    conversation = result.scalar_one_or_none()

    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Use Pydantic v2 model_validate with from_attributes for proper serialization
    return ConversationResponse.model_validate(conversation, from_attributes=True)


async def update_team_cache():
    """Update the team name to ID mapping cache."""
    if not ENABLE_TEAM_CACHE:
        logger.warning("Team caching is disabled. Skipping cache update.")
        return {}

    global team_cache, last_update_time

    async with team_cache_lock:
        try:
            teams = await chatwoot.get_teams()

            # Create case-insensitive mappings from name to ID
            new_cache = {team["name"].lower(): team["id"] for team in teams}

            # Update the cache
            team_cache = new_cache
            last_update_time = datetime.now(UTC).timestamp()

            logger.info(f"Updated team cache with {len(team_cache)} teams")
            return team_cache
        except Exception as e:
            logger.error(f"Failed to update team cache: {e}", exc_info=True)
            raise


async def get_team_id(team_name: str) -> Optional[int]:
    """Get team ID from name, updating cache if necessary.

    Args:
        team_name: The name of the team to look up

    Returns:
        The team ID or None if not found
    """
    if not ENABLE_TEAM_CACHE:
        # Direct API call when caching is disabled
        try:
            teams = await chatwoot.get_teams()
            team_map = {team["name"].lower(): team["id"] for team in teams}
            return team_map.get(team_name.lower())
        except Exception as e:
            logger.error(f"Failed to get team ID for '{team_name}' (no cache): {e}")
            return None

    # Use cache when enabled
    cache_age_hours = (datetime.now(UTC).timestamp() - last_update_time) / 3600
    if not team_cache or cache_age_hours > TEAM_CACHE_TTL_HOURS:
        await update_team_cache()

    return team_cache.get(team_name.lower())


@router.post("/refresh-teams")
@handle_api_errors("refresh teams cache")
async def refresh_teams_cache():
    """Manually refresh the team cache."""
    if not ENABLE_TEAM_CACHE:
        # When caching is disabled, just return current teams from API
        teams = await chatwoot.get_teams()
        return {"status": "success", "teams": len(teams), "cache_enabled": False}

    teams = await update_team_cache()
    return {"status": "success", "teams": len(teams), "cache_enabled": True}


@router.post("/assign-team/{conversation_id}")
@handle_api_errors("assign conversation to team")
async def assign_conversation_to_team(
    conversation_id: int,
    team: str = Body(
        ...,
        embed=True,
        description="Team name to assign the conversation to",
    ),
    db: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    """Assign a Chatwoot conversation to a team using optimized patterns."""
    if not team or team.lower() == "none":
        return {"status": "success", "conversation_id": conversation_id, "team": "None"}

    # Log the attempt
    logger.info(f"Attempting to assign conversation {conversation_id} to team {team}")

    # Get team_id from name
    team_id = await get_team_id(team)

    if team_id is None:
        if ENABLE_TEAM_CACHE:
            # Try to refresh the cache and try again
            await update_team_cache()
            team_id = await get_team_id(team)

        if team_id is None:
            # Get available teams for error message
            try:
                if ENABLE_TEAM_CACHE:
                    available_teams = list(team_cache.keys())
                else:
                    teams = await chatwoot.get_teams()
                    available_teams = [team["name"].lower() for team in teams]
            except Exception:
                available_teams = ["Unable to fetch teams"]

            raise HTTPException(
                status_code=404,
                detail=f"Team '{team}' not found. Available teams: {available_teams}",
            )

    # Assign the conversation to the team
    result = await chatwoot.assign_team(conversation_id=conversation_id, team_id=team_id)

    # Update local conversation record if it exists
    statement = select(Conversation).where(Conversation.chatwoot_conversation_id == str(conversation_id))
    result_db = await db.execute(statement)
    conversation = result_db.scalar_one_or_none()

    if conversation:
        conversation.updated_at = datetime.now(UTC)
        # Note: No manual commit needed - six-line pattern handles this automatically

    # Log successful result
    logger.info(f"Successfully assigned conversation {conversation_id} to team {team} (ID: {team_id})")

    return {
        "status": "success",
        "conversation_id": conversation_id,
        "team": team,
        "team_id": team_id,
        "result": result,
    }


@router.post("/toggle-status/{conversation_id}")
@handle_api_errors("toggle conversation status")
async def toggle_conversation_status(
    conversation_id: int,
    status: ConversationStatus = Body(..., embed=True),
    db: AsyncSession = Depends(get_session),
) -> Dict[str, Any]:
    """Toggle the status of a Chatwoot conversation using optimized patterns."""
    # Get current conversation data to find out the previous status
    previous_status_val: Optional[str] = None
    try:
        conversation_data = await chatwoot.get_conversation_data(conversation_id)
        previous_status_val = conversation_data.get("status")
        logger.info(f"Current status for convo {conversation_id} before toggle: {previous_status_val}")
    except Exception as e_get_status:
        # Log the error but proceed, previous_status will be None
        # The notification logic in toggle_status handles previous_status being None
        logger.warning(f"Could not fetch current status for convo {conversation_id} before toggle: {e_get_status}")

    result = await chatwoot.toggle_status(
        conversation_id=conversation_id,
        status=status.value,
        previous_status=previous_status_val,
        is_error_transition=False,  # This is not an error-induced transition
    )

    # Update local conversation record if it exists
    statement = select(Conversation).where(Conversation.chatwoot_conversation_id == str(conversation_id))
    result_db = await db.execute(statement)
    conversation = result_db.scalar_one_or_none()

    if conversation:
        conversation.status = status.value
        conversation.updated_at = datetime.now(UTC)
        # Note: No manual commit needed - six-line pattern handles this automatically

    return {
        "status": "success",
        "conversation_id": conversation_id,
        "new_status": status.value,
        "previous_status": previous_status_val,
        "result": result,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan events manager"""
    # Application startup
    await create_db_tables()
    logger.info("Application startup: Database tables checked/created.")
    # Consider any other startup logic here, e.g., initializing caches, connecting to external services

    if ENABLE_TEAM_CACHE:
        await update_team_cache()
        logger.info(f"Initialized team cache with {len(team_cache)} teams")
    else:
        logger.info("Team caching is disabled. Teams will be fetched directly from API.")

    yield  # Application is now running

    # Application shutdown
    # Consider any cleanup logic here, e.g., closing connections, saving state
    logger.info("Application shutdown: Cleaning up resources.")

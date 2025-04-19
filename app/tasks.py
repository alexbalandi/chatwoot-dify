import logging
from typing import Any, Dict, Optional

import httpx
from celery import Celery, signals
from dotenv import load_dotenv

from . import config
from .api.chatwoot import ChatwootHandler
from .config import BOT_ERROR_MESSAGE
from .database import SessionLocal
from .models.database import Dialogue, DifyResponse
from .utils.sentry import init_sentry

load_dotenv()

# Use timeout constants from config
HTTPX_TIMEOUT = httpx.Timeout(
    connect=config.HTTPX_CONNECT_TIMEOUT,
    read=config.HTTPX_READ_TIMEOUT,
    write=config.HTTPX_WRITE_TIMEOUT,
    pool=config.HTTPX_POOL_TIMEOUT,
)

# Use LOG_LEVEL from config instead of directly from environment
LOG_LEVEL = config.LOG_LEVEL

REDIS_BROKER = config.REDIS_BROKER
REDIS_BACKEND = config.REDIS_BACKEND

# Configure root logger
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    force=True,  # Override any existing configuration
)

# Ensure celery logging is properly configured
celery_logger = logging.getLogger("celery")
celery_logger.setLevel(getattr(logging, LOG_LEVEL.upper()))

# Configure our app logger
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, LOG_LEVEL.upper()))

# Ensure logs are propagated up
logger.propagate = True

celery = Celery("tasks")
celery.config_from_object(config, namespace="CELERY")


# Initialize Sentry on Celery daemon startup
@signals.celeryd_init.connect
def init_sentry_for_celery(**_kwargs):
    if init_sentry(with_fastapi=False, with_asyncpg=False, with_celery=True):
        logger.info("Celery daemon: Sentry initialized via celeryd_init signal")


# Initialize Sentry on each worker process startup
@signals.worker_init.connect
def init_sentry_for_worker(**_kwargs):
    if init_sentry(with_fastapi=False, with_asyncpg=False, with_celery=True):
        logger.info("Celery worker: Sentry initialized via worker_init signal")


def make_dify_request(url: str, data: dict, headers: dict) -> dict:
    """Make a request to Dify API with retry logic"""
    with httpx.Client(timeout=HTTPX_TIMEOUT) as client:
        response = client.post(url, json=data, headers=headers)
        response.raise_for_status()
        return response.json()


# Helper function to update dialogue in DB (synchronous)
def update_dialogue_dify_id_sync(chatwoot_convo_id: str, new_dify_id: str):
    logger.info(f"Attempting to update dify_conversation_id for chatwoot_convo_id={chatwoot_convo_id} to {new_dify_id}")
    with SessionLocal() as db:  # Use synchronous session
        try:
            # Query dialogue based on chatwoot_conversation_id
            dialogue = db.query(Dialogue).filter_by(chatwoot_conversation_id=chatwoot_convo_id).first()
            if dialogue:
                if not dialogue.dify_conversation_id:  # Update only if it's not already set
                    dialogue.dify_conversation_id = new_dify_id
                    db.commit()
                    logger.info(f"Successfully updated dify_conversation_id for chatwoot_convo_id={chatwoot_convo_id}")
                else:
                    logger.warning(
                        f"dify_conversation_id already set for chatwoot_convo_id={chatwoot_convo_id}. Skipping update."
                    )
            else:
                logger.error(
                    f"Dialogue record not found for chatwoot_conversation_id={chatwoot_convo_id} during update attempt."
                )
        except Exception as e:
            logger.error(
                f"Failed to update dify_conversation_id for chatwoot_convo_id={chatwoot_convo_id}: {e}", exc_info=True
            )
            db.rollback()  # Rollback on error


@celery.task(bind=True, max_retries=3, default_retry_delay=5)
def process_message_with_dify(
    self,
    message: str,
    dify_conversation_id: Optional[str] = None,
    chatwoot_conversation_id: Optional[str] = None,
    conversation_status: Optional[str] = None,
    message_type: Optional[str] = None,  # `incoming` and `outgoing`
) -> Dict[str, Any]:
    """
    Process a message with Dify and return the response as a dictionary.
    Handles initial conversation creation if dify_conversation_id is None.
    Retries on 404 if an existing dify_conversation_id is provided but not found.
    """
    if message.startswith(BOT_ERROR_MESSAGE):
        return {"status": "skipped", "reason": "agent_bot message"}
    url = f"{config.DIFY_API_URL}/chat-messages"
    headers = {"Authorization": f"Bearer {config.DIFY_API_KEY}", "Content-Type": "application/json"}

    logger.info(
        f"Processing message with Dify for chatwoot_conversation_id={chatwoot_conversation_id}, "
        f"dify_conversation_id={dify_conversation_id}, direction: {message_type}"
    )
    data = {
        "query": message,
        "inputs": {
            "chatwoot_conversation_id": chatwoot_conversation_id,
            "conversation_status": conversation_status,
            "message_direction": message_type,
        },
        "response_mode": config.DIFY_RESPONSE_MODE,
        "user": "user",
    }

    # Only include conversation_id in the payload if it's already set
    if dify_conversation_id:
        data["conversation_id"] = dify_conversation_id
        logger.info("Using existing dify_conversation_id.")
    else:
        logger.info("No dify_conversation_id provided. Attempting to create conversation via first message.")
        # Payload for creation doesn't include 'conversation_id' key

    try:
        with httpx.Client(timeout=HTTPX_TIMEOUT) as client:
            response = client.post(url, json=data, headers=headers)
            # Store response content before raising exception
            if response.status_code >= 400:
                error_content = response.text
                logger.error(f"Dify API error response ({response.status_code}): {error_content}")
            response.raise_for_status()  # Raise exception for 4xx/5xx
            result = response.json()
            logger.info(f"Dify API success for chatwoot_conversation_id={chatwoot_conversation_id}")

            # --- Handle Conversation Creation ---
            # If we started without an ID, extract the new one from the response and update DB
            if not dify_conversation_id and chatwoot_conversation_id:
                new_dify_id = result.get("conversation_id")
                if new_dify_id:
                    logger.info(f"New Dify conversation created: {new_dify_id}. Updating database.")
                    # Update DB synchronously within the task
                    update_dialogue_dify_id_sync(chatwoot_conversation_id, new_dify_id)
                else:
                    # This case shouldn't happen if Dify is working correctly, but log a warning.
                    logger.warning(
                        f"Dify API call succeeded but did not return a 'conversation_id' when one was expected. "
                        f"Dify response: {result}"
                    )
            # --- End Handle Conversation Creation ---

            return result  # Return successful result (contains first message answer)

    except httpx.HTTPStatusError as e:
        # Specific retry logic for 404 ONLY when a conversation ID WAS provided
        if e.response.status_code == 404 and dify_conversation_id:
            logger.warning(
                f"Dify 404 (Conversation Not Found) for *existing* dify_id={dify_conversation_id}. "
                f"Retrying task (attempt {self.request.retries + 1}/{self.max_retries})..."
            )
            try:
                # Use Celery's retry mechanism with countdown
                self.retry(exc=e, countdown=config.CELERY_RETRY_COUNTDOWN)  # Use configured countdown
            except self.MaxRetriesExceededError:
                logger.error(
                    f"Max retries exceeded for Dify 404 on conversation {dify_conversation_id}. Failing task.",
                    exc_info=True,
                )
                # Fall through to generic error handling (set status to open, etc.)
        # If it was a 404 but dify_conversation_id was None, it means creation failed - don't retry.
        elif e.response.status_code == 404 and not dify_conversation_id:
            logger.error(
                f"Dify returned 404 when attempting initial conversation creation."
                f"Payload: {data}. Response: {e.response.text}",
                exc_info=True,
            )
            # Fall through to generic error handling
        # Log other HTTP errors before falling through
        elif isinstance(e, httpx.HTTPStatusError):
            logger.error(
                f"HTTP Error {e.response.status_code} processing Dify message: {e.response.text}", exc_info=True
            )
            # Fall through to generic error handling

        # Generic error handling for non-retryable errors or max retries exceeded
        logger.critical(
            f"Critical error processing message with Dify: {e} \n"
            f"conversation_id: {dify_conversation_id} \n chatwoot_conversation_id: {chatwoot_conversation_id}",
            exc_info=True,
        )
        # If it's an HTTP error, try to extract and log the response content again (might be redundant but safe)
        if isinstance(e, httpx.HTTPStatusError) and hasattr(e, "response"):
            logger.error(f"Final Response content on failure: {e.response.text}")

        # Set conversation status to open on error
        if chatwoot_conversation_id:
            try:
                logger.info(f"Setting Chatwoot conversation {chatwoot_conversation_id} status to 'open' due to error")
                chatwoot = ChatwootHandler()
                # Use the proper method from ChatwootHandler that already exists
                result = chatwoot.toggle_status_sync(conversation_id=int(chatwoot_conversation_id), status="open")
                logger.info(f"Successfully set conversation {chatwoot_conversation_id} status to 'open'")
            except Exception as status_error:
                logger.error(f"Failed to set conversation {chatwoot_conversation_id} status to 'open': {status_error}")

        raise e from e

    except Exception as e:  # Catch other non-HTTP errors
        logger.critical(
            f"Non-HTTP critical error processing message with Dify: {e} \n"
            f"conversation_id: {dify_conversation_id} \n chatwoot_conversation_id: {chatwoot_conversation_id}",
            exc_info=True,
        )
        # Set conversation status to open on error
        if chatwoot_conversation_id:
            try:
                logger.info(
                    f"Setting Chatwoot conversation {chatwoot_conversation_id} status to 'open' due to non-HTTP error"
                )
                chatwoot = ChatwootHandler()
                # Use the proper method from ChatwootHandler that already exists
                result = chatwoot.toggle_status_sync(conversation_id=int(chatwoot_conversation_id), status="open")
                logger.info(f"Successfully set conversation {chatwoot_conversation_id} status to 'open'")
            except Exception as status_error:
                logger.error(f"Failed to set conversation {chatwoot_conversation_id} status to 'open': {status_error}")

        raise e from e


@celery.task(name="app.tasks.handle_dify_response")
def handle_dify_response(dify_result: Dict[str, Any], conversation_id: int, dialogue_id: int):
    """Handle the response from Dify"""

    chatwoot = ChatwootHandler()

    # No need to update dialogue here anymore, it's done in process_message_with_dify if needed.
    # We still need the DifyResponse model for validation/extraction.
    try:
        dify_response_data = DifyResponse(**dify_result)

        # Send message back to Chatwoot. Sync is okay because we use separate instance of ChatwootHandler
        chatwoot.send_message_sync(
            conversation_id=conversation_id,
            message=dify_response_data.answer,
            private=False,
        )
    except Exception as e:
        logger.error(f"Error handling Dify response: {str(e)}", exc_info=True)
        # Re-raise to ensure Celery knows this task failed
        raise


@celery.task(name="app.tasks.handle_dify_error")
def handle_dify_error(request: Dict[str, Any], exc: Exception, traceback: str, conversation_id: int):
    """Handle any errors from the Dify task"""
    from .api.chatwoot import ChatwootHandler

    logger.error(f"Dify task failed for conversation {conversation_id}: {exc} \n {request} \n {traceback}")

    # Send message back to Chatwoot. Sync is okay because we use separate instance of ChatwootHandler
    chatwoot = ChatwootHandler()
    chatwoot.send_message_sync(
        conversation_id=conversation_id,
        message=BOT_ERROR_MESSAGE,
        private=False,
    )


@celery.task(name="app.tasks.delete_dify_conversation")
def delete_dify_conversation(dify_conversation_id: str):
    """Delete a conversation from Dify when it's deleted in Chatwoot"""
    logger.info(f"Deleting Dify conversation: {dify_conversation_id}")

    url = f"{config.DIFY_API_URL}/conversations/{dify_conversation_id}"
    headers = {"Authorization": f"Bearer {config.DIFY_API_KEY}", "Content-Type": "application/json"}

    try:
        with httpx.Client(timeout=HTTPX_TIMEOUT) as client:
            response = client.delete(url, headers=headers)
            response.raise_for_status()
            logger.info(f"Successfully deleted Dify conversation: {dify_conversation_id}")
            return {"status": "success", "conversation_id": dify_conversation_id}
    except Exception as e:
        logger.error(f"Failed to delete Dify conversation {dify_conversation_id}: {e}", exc_info=True)
        raise e from e

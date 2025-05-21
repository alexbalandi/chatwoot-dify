import logging
from typing import Any, Dict, Optional

import httpx # Keep for ChatwootHandler and other potential non-Dify calls if any
from celery import Celery, signals
from dotenv import load_dotenv

from . import config
from .api.chatwoot import ChatwootHandler
# Import DifyClient and its exceptions
from .dify_client import DifyClient, DifyApiError, DifyConversationNotFoundError
from .config import BOT_CONVERSATION_OPENED_MESSAGE_EXTERNAL, BOT_ERROR_MESSAGE_INTERNAL
from .database import SessionLocal
from .models.database import Dialogue, DifyResponse
from .utils.sentry import init_sentry

load_dotenv()

# HTTPX_TIMEOUT is now used by DifyClient internally, passed from config.DIFY_HTTP_TIMEOUT
# We might still need a general timeout for other httpx calls (e.g. Chatwoot)
# For now, let's assume ChatwootHandler manages its own timeouts or use a default one.
# If ChatwootHandler needs specific timeouts, they should be configured similarly.
# The global HTTPX_TIMEOUT might still be useful for other direct httpx calls in this file, if any.
HTTPX_TIMEOUT = httpx.Timeout(
    connect=config.HTTPX_CONNECT_TIMEOUT,
    read=config.HTTPX_READ_TIMEOUT,
    write=config.HTTPX_WRITE_TIMEOUT,
    pool=config.HTTPX_POOL_TIMEOUT,
)


# Use LOG_LEVEL from config instead of directly from environment
LOG_LEVEL = config.LOG_LEVEL
# Ensure DifyClient's logger also respects this level if not already configured
dify_client_logger = logging.getLogger("app.dify_client")
dify_client_logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

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
                f"Failed to update dify_conversation_id for chatwoot_convo_id={chatwoot_convo_id}: {e}",
                exc_info=True,
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
    # Prevent bot from replying to its own error or status messages
    if message.startswith(BOT_CONVERSATION_OPENED_MESSAGE_EXTERNAL) or message.startswith(BOT_ERROR_MESSAGE_INTERNAL):
        logger.info(f"Skipping self-generated message: {message[:50]}...")
        return {"status": "skipped", "reason": "agent_bot message"}

    logger.info(
        f"Processing message with Dify for chatwoot_conversation_id={chatwoot_conversation_id}, "
        f"dify_conversation_id={dify_conversation_id}, direction: {message_type}"
    )

    # Instantiate DifyClient - Timeout is already configured in DIFY_HTTP_TIMEOUT from config
    dify_client = DifyClient(api_url=config.DIFY_API_URL, api_key=config.DIFY_API_KEY, timeout=config.DIFY_HTTP_TIMEOUT)

    # Prepare inputs for DifyClient
    dify_inputs = {
        "chatwoot_conversation_id": chatwoot_conversation_id,
        "conversation_status": conversation_status,
        "message_direction": message_type,
    }
    # The 'user' parameter for Dify is typically a user identifier string.
    # In the original code, it was hardcoded as "user".
    dify_user_id = "user" # Or derive from Chatwoot if available/needed

    try:
        result = dify_client.send_chat_message(
            message_content=message,
            user_id=dify_user_id,
            inputs=dify_inputs,
            response_mode=config.DIFY_RESPONSE_MODE,
            conversation_id=dify_conversation_id
        )
        logger.info(f"Dify API call successful for chatwoot_conversation_id={chatwoot_conversation_id}")

        # --- Handle Conversation Creation ---
        if not dify_conversation_id and chatwoot_conversation_id:
            new_dify_id = result.get("conversation_id")
            if new_dify_id:
                logger.info(f"New Dify conversation created: {new_dify_id}. Updating database.")
                update_dialogue_dify_id_sync(chatwoot_conversation_id, new_dify_id)
            else:
                error_msg = (
                    f"Dify API call succeeded but didn't return a 'conversation_id' "
                    f"when one was expected (initial creation for chatwoot_convo_id={chatwoot_conversation_id}). "
                    f"Dify response: {result}"
                )
                logger.error(error_msg)
                try:
                    logger.warning(
                        f"Retrying task due to missing conversation_id on creation "
                        f"(attempt {self.request.retries + 1}/{self.max_retries})..."
                    )
                    self.retry(exc=RuntimeError(error_msg), countdown=config.CELERY_RETRY_COUNTDOWN)
                except self.MaxRetriesExceededError:
                    logger.error(
                        f"Max retries exceeded for missing conversation_id on creation for "
                        f"chatwoot_convo_id={chatwoot_conversation_id}. Failing task.",
                        exc_info=True,
                    )
                    raise RuntimeError(error_msg) from None
        # --- End Handle Conversation Creation ---

        return result

    except DifyConversationNotFoundError as e:
        # This is the specific 404 error for an existing conversation_id from DifyClient
        logger.warning(
            f"DifyConversationNotFoundError for dify_id={dify_conversation_id}. "
            f"Retrying task (attempt {self.request.retries + 1}/{self.max_retries}). Error: {e}"
        )
        try:
            self.retry(exc=e, countdown=config.CELERY_RETRY_COUNTDOWN)
        except self.MaxRetriesExceededError:
            logger.error(
                f"Max retries exceeded for DifyConversationNotFoundError on conversation {dify_conversation_id}. Failing task.",
                exc_info=True,
            )
            # Fall through to generic error handling by re-raising
            # The generic handler below will catch this re-raised 'e'
            pass # Let it fall through to the DifyApiError or general Exception handler

    except DifyApiError as e: # Catch other Dify API errors (non-404 or 404 on creation)
        # Log the DifyApiError. The DifyClient should have already logged details.
        logger.error(
            f"DifyApiError processing message for chatwoot_convo_id={chatwoot_conversation_id}, "
            f"dify_convo_id={dify_conversation_id}. Error: {e}",
            exc_info=True
        )
        # Check if it's a 404 during creation (dify_conversation_id was None)
        # The DifyClient raises DifyApiError for general HTTP errors, and DifyConversationNotFoundError for 404s on *existing* IDs.
        # If dify_conversation_id was None, a 404 means creation failed. This is not typically retried.
        if "404" in str(e) and not dify_conversation_id: # Simple check, might need refinement
             logger.error(
                f"Dify returned 404 when attempting initial conversation creation. Error: {e}",
                exc_info=True
            )
        # For other DifyApiErrors, we might not want to retry indefinitely or use the same logic as 404.
        # The original code retried only specific 404s. Other HTTPStatusErrors fell through.
        # We will let this fall through to the generic error handling for now.
        pass # Let it fall through to the generic Exception handler that calls Chatwoot etc.


    # Generic error handling for DifyApiError that wasn't retried, or other exceptions
    # This block will catch DifyApiError if it's not DifyConversationNotFoundError or if retries for it are exhausted.
    # It will also catch any other unexpected exceptions.
    except Exception as e: # Catches DifyApiError, DifyConversationNotFoundError (if retries exhausted), httpx.RequestError (if DifyClient fails to catch), etc.
        logger.critical(
            f"Critical error processing message with Dify: {e} \n"
            f"dify_conversation_id: {dify_conversation_id} \n chatwoot_conversation_id: {chatwoot_conversation_id}",
            exc_info=True,
        )

        # Set conversation status to open on error
        if chatwoot_conversation_id:
            try:
                logger.info(f"Setting Chatwoot conversation {chatwoot_conversation_id} status to 'open' due to error")
                chatwoot = ChatwootHandler()
                current_status_before_toggle = conversation_status
                # Set status to open, indicating it's an error transition for internal note
                chatwoot.toggle_status_sync(
                    conversation_id=int(chatwoot_conversation_id),
                    status="open",
                    previous_status=current_status_before_toggle,
                    is_error_transition=True,  # Indicate this is an error-induced transition
                )
                logger.info(f"Successfully set conversation {chatwoot_conversation_id} status to 'open' (HTTP error)")

                # Send public error message to the user
                logger.info(f"Sending external error message to conversation {chatwoot_conversation_id}")
                chatwoot.send_message_sync(
                    conversation_id=int(chatwoot_conversation_id),
                    message=config.BOT_CONVERSATION_OPENED_MESSAGE_EXTERNAL,
                    private=False,
                )

            except Exception as status_error:
                logger.error(
                    f"Failed to set conversation {chatwoot_conversation_id} status to 'open'"
                    f"or send error messages: {status_error}"
                )

        raise e from e

    except Exception as e:  # Catch other non-HTTP errors
        logger.critical(
            f"Non-HTTP critical error processing message with Dify: {e} \n"
            f"conversation_id: {dify_conversation_id} \n "
            f"chatwoot_conversation_id: {chatwoot_conversation_id}",
            exc_info=True,
        )
        # Set conversation status to open on error and send messages
        if chatwoot_conversation_id:
            try:
                logger.info(
                    f"Setting Chatwoot conversation {chatwoot_conversation_id} status to 'open' due to non-HTTP error"
                )
                chatwoot = ChatwootHandler()
                current_status_before_toggle = conversation_status
                # Set status to open, indicating it's an error transition for internal note
                chatwoot.toggle_status_sync(
                    conversation_id=int(chatwoot_conversation_id),
                    status="open",
                    previous_status=current_status_before_toggle,
                    is_error_transition=True,  # Indicate this is an error-induced transition
                )
                logger.info(
                    f"Successfully set conversation {chatwoot_conversation_id} status to 'open' (non-HTTP error)"
                )

                # Send public error message to the user
                logger.info(f"Sending external error message to conversation {chatwoot_conversation_id}")
                chatwoot.send_message_sync(
                    conversation_id=int(chatwoot_conversation_id),
                    message=config.BOT_CONVERSATION_OPENED_MESSAGE_EXTERNAL,
                    private=False,
                )
            except Exception as status_error:
                logger.error(
                    f"Failed to set conversation {chatwoot_conversation_id} status to 'open' or"
                    f"send error messages (non-HTTP error): {status_error}"
                )

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
    # The import 'from .api.chatwoot import ChatwootHandler' and associated message sending logic
    # have been removed as per new requirements. Only logging remains.

    logger.error(f"Dify task failed for conversation {conversation_id}: {exc} \n {request} \n {traceback}")


@celery.task(name="app.tasks.delete_dify_conversation")
def delete_dify_conversation(dify_conversation_id: str):
    """Delete a conversation from Dify when it's deleted in Chatwoot"""
    logger.info(f"Attempting to delete Dify conversation: {dify_conversation_id}")

    dify_client = DifyClient(api_url=config.DIFY_API_URL, api_key=config.DIFY_API_KEY, timeout=config.DIFY_HTTP_TIMEOUT)

    try:
        result = dify_client.delete_conversation(conversation_id=dify_conversation_id)
        logger.info(f"Successfully initiated deletion of Dify conversation: {dify_conversation_id}. Result: {result}")
        return result
    except DifyConversationNotFoundError: # Specific error for 404
        logger.warning(
            f"Dify conversation {dify_conversation_id} not found for deletion (404). Assuming already deleted or never existed.",
            exc_info=True
        )
        # Not re-raising as an error, as the goal is for it to be gone.
        return {"status": "not_found", "conversation_id": dify_conversation_id}
    except DifyApiError as e: # Catch other errors from DifyClient during delete
        logger.error(
            f"DifyApiError occurred while deleting Dify conversation {dify_conversation_id}: {e}",
            exc_info=True,
        )
        # Re-raise to mark the task as failed if deletion fails for reasons other than not found
        raise e from e
    except Exception as e: # Catch any other unexpected errors
        logger.error(
            f"Unexpected error while deleting Dify conversation {dify_conversation_id}: {e}",
            exc_info=True,
        )
        raise e from e

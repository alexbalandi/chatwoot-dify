import logging
from typing import Any, Dict, List # Removed Optional: F401 'typing.Optional' imported but unused
import httpx

from .base_service import BaseChatwootService
from app import config # For BOT_ERROR_MESSAGE_INTERNAL if used by internal notifications within message sending

logger = logging.getLogger(__name__)

class MessageService(BaseChatwootService):
    async def send_message(
        self,
        conversation_id: int,
        message: str,
        private: bool = False,
        attachments: List[str] | None = None, # Assuming attachments are URLs
        content_attributes: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Send a message or private note to a conversation with rich content support."""
        url = f"{self.conversations_url}/{conversation_id}/messages"
        data = {
            "content": message,
            "message_type": "outgoing", # Or determine based on context if needed
            "private": private,
            "content_attributes": content_attributes or {},
        }

        if attachments:
            # Assuming attachments are a list of file URLs to be sent
            # Chatwoot API expects attachments as an array of objects, each with a 'url' key
            # This needs to be confirmed with Chatwoot's API documentation for actual file uploads.
            # If they are local file paths, they'd need to be uploaded as multipart/form-data.
            # For now, let's assume they are URLs as per the original `ChatwootHandler` hint.
            # The original code had `data["attachments"] = [{"url": url} for url in attachments]`
            # which implies `url` was a variable, not the parameter. This seems like a bug.
            # Correcting it to use the attachment URLs provided in the list.
            data["attachments"] = [{"resource_url": attachment_url} for attachment_url in attachments]
            # Note: Chatwoot's actual API for message attachments might require files to be uploaded
            # via multipart POST to a separate endpoint first, then referenced by ID.
            # This implementation matches the previous structure; if file uploads are needed,
            # this part will require significant changes.

        logger.debug(f"Sending message to Chatwoot convo {conversation_id}. URL: {url}, Data: {data}")
        try:
            async with httpx.AsyncClient(timeout=config.HTTPX_DEFAULT_TIMEOUT) as client: # Use configured timeout
                response = await client.post(url, json=data, headers=self.headers)
                response.raise_for_status()
                logger.info(f"Message sent successfully to Chatwoot convo {conversation_id}")
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error sending message to Chatwoot convo {conversation_id}: {e.response.status_code} - {e.response.text}",
                exc_info=True
            )
            raise # Re-raise to allow higher-level handling
        except httpx.RequestError as e:
            logger.error(f"Request error sending message to Chatwoot convo {conversation_id}: {e}", exc_info=True)
            raise


    def send_message_sync(self, conversation_id: int, message: str, private: bool = False) -> Dict[str, Any]:
        """Synchronous version of send_message for use in Celery tasks."""
        url = f"{self.conversations_url}/{conversation_id}/messages"
        data = {
            "content": message,
            "message_type": "outgoing",
            "private": private,
        }
        logger.debug(f"Sending message sync to Chatwoot convo {conversation_id}. URL: {url}, Data: {data}")
        try:
            with httpx.Client(timeout=config.HTTPX_DEFAULT_TIMEOUT) as client: # Use configured timeout
                response = client.post(url, json=data, headers=self.headers)
                response.raise_for_status()
                logger.info(f"Message sent successfully sync to Chatwoot convo {conversation_id}")
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error sending message sync to Chatwoot convo {conversation_id}: {e.response.status_code} - {e.response.text}",
                exc_info=True
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error sending message sync to Chatwoot convo {conversation_id}: {e}", exc_info=True)
            raise

logger.info("MessageService initialized.")

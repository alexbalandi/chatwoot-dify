import httpx
import logging
from app.config import DIFY_API_URL, DIFY_API_KEY, DIFY_HTTP_TIMEOUT, LOG_LEVEL

# Configure logger for this module
logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))


# Custom Exceptions
class DifyApiError(Exception):
    """Base exception for Dify API errors."""
    pass

class DifyConversationNotFoundError(DifyApiError):
    """Custom exception for Dify conversation not found (404)."""
    pass


class DifyClient:
    def __init__(self, api_url: str = DIFY_API_URL, api_key: str = DIFY_API_KEY, timeout: httpx.Timeout = DIFY_HTTP_TIMEOUT):
        self.api_url = api_url
        self.api_key = api_key
        self.timeout = timeout # Should be an instance of httpx.Timeout
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def send_chat_message(self, message_content: str, user_id: str, inputs: dict, response_mode: str, conversation_id: str = None):
        """
        Sends a chat message to the Dify API.
        Returns the parsed JSON response from Dify.
        """
        payload = {
            "inputs": inputs,
            "query": message_content,
            "user": user_id,
            "response_mode": response_mode,
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id

        url = f"{self.api_url}/chat-messages"
        logger.debug(f"Sending chat message to Dify. URL: {url}, Payload: {payload}")

        try:
            response = httpx.post(url, headers=self.headers, json=payload, timeout=self.timeout)
            
            logger.debug(f"Dify request sent. URL: {url}, Method: POST, Headers: {self.headers}, Payload: {payload}")

            if response.status_code >= 400:
                error_content = response.text
                logger.error(f"Dify API error response ({response.status_code}) for conversation {conversation_id}: {error_content}")
            
            response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
            
            logger.info(f"Dify API success for query: {message_content[:30]}... (Conversation ID: {conversation_id})")
            return response.json() # Return the parsed JSON response

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTPStatusError from Dify: {e.response.status_code}, Response: {e.response.text}", exc_info=True)
            if e.response.status_code == 404 and conversation_id: # Only if conversation_id was provided
                raise DifyConversationNotFoundError(f"Dify conversation {conversation_id} not found.")
            # General Dify API error for other HTTP issues
            raise DifyApiError(f"Dify API request failed: {e.response.status_code} - {e.response.text}") from e
        except httpx.RequestError as e:
            # Handle network errors or other request issues
            logger.error(f"RequestError connecting to Dify API: {e}", exc_info=True)
            raise DifyApiError(f"Error connecting to Dify API: {e}")


    def delete_conversation(self, conversation_id: str):
        """
        Deletes a Dify conversation.
        """
        url = f"{self.api_url}/conversations/{conversation_id}"
        logger.debug(f"Attempting to delete Dify conversation: {conversation_id} at URL: {url}")

        try:
            response = httpx.delete(url, headers=self.headers, timeout=self.timeout)
            response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
            logger.info(f"Successfully deleted Dify conversation: {conversation_id}")
            # Dify might return specific data on successful deletion, adjust as needed.
            # For now, assume 200/204 means success. The original task returns a dict.
            return {"status": "success", "conversation_id": conversation_id}
        except httpx.HTTPStatusError as e:
            error_message = f"Error deleting Dify conversation {conversation_id}: {e.response.status_code} - {e.response.text}"
            logger.error(error_message, exc_info=True)
            if e.response.status_code == 404:
                raise DifyConversationNotFoundError(f"Dify conversation {conversation_id} not found for deletion.")
            raise DifyApiError(error_message) from e
        except httpx.RequestError as e:
            error_message = f"Network error connecting to Dify API for deleting conversation {conversation_id}: {e}"
            logger.error(error_message, exc_info=True)
            raise DifyApiError(error_message) from e

import logging
from typing import Any, Dict, List, Optional, Tuple
import httpx

from .base_service import BaseChatwootService
from app import config # For BOT_ERROR_MESSAGE_INTERNAL, HTTPX_DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

class ConversationService(BaseChatwootService):
    async def add_labels(self, conversation_id: int, labels: List[str]) -> Dict[str, Any]:
        """Add labels to a conversation."""
        url = f"{self.conversations_url}/{conversation_id}/labels"
        logger.debug(f"Adding labels to Chatwoot convo {conversation_id}. URL: {url}, Labels: {labels}")
        try:
            async with httpx.AsyncClient(timeout=config.HTTPX_DEFAULT_TIMEOUT) as client:
                response = await client.post(url, json={"labels": labels}, headers=self.headers)
                response.raise_for_status()
                logger.info(f"Labels added successfully to Chatwoot convo {conversation_id}.")
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error adding labels to Chatwoot convo {conversation_id}: {e.response.status_code} - {e.response.text}",
                exc_info=True
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error adding labels to Chatwoot convo {conversation_id}: {e}", exc_info=True)
            raise

    async def get_conversation_data(self, conversation_id: int) -> Dict[str, Any]:
        """Get conversation data including custom attributes and labels. Uses admin headers."""
        url = f"{self.conversations_url}/{conversation_id}"
        logger.debug(f"Getting data for Chatwoot convo {conversation_id}. URL: {url}")
        try:
            async with httpx.AsyncClient(timeout=config.HTTPX_DEFAULT_TIMEOUT) as client:
                response = await client.get(url, headers=self.admin_headers) # Use admin headers
                response.raise_for_status()
                logger.info(f"Data retrieved successfully for Chatwoot convo {conversation_id}.")
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error getting data for Chatwoot convo {conversation_id}: {e.response.status_code} - {e.response.text}",
                exc_info=True
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error getting data for Chatwoot convo {conversation_id}: {e}", exc_info=True)
            raise

    async def assign_conversation(self, conversation_id: int, assignee_id: Optional[int] = None) -> Dict[str, Any]:
        """Assign a conversation to an agent. If assignee_id is None, unassigns."""
        url = f"{self.conversations_url}/{conversation_id}/assignments"
        data = {"assignee_id": assignee_id}
        logger.debug(f"Assigning Chatwoot convo {conversation_id} to assignee {assignee_id}. URL: {url}, Data: {data}")
        try:
            async with httpx.AsyncClient(timeout=config.HTTPX_DEFAULT_TIMEOUT) as client:
                response = await client.post(url, json=data, headers=self.headers)
                response.raise_for_status()
                logger.info(f"Chatwoot convo {conversation_id} assigned successfully to assignee {assignee_id}.")
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error assigning Chatwoot convo {conversation_id}: {e.response.status_code} - {e.response.text}",
                exc_info=True
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error assigning Chatwoot convo {conversation_id}: {e}", exc_info=True)
            raise

    async def patch_custom_attributes(self, conversation_id: int, custom_attributes: Dict[str, Any]) -> Dict[str, Any]:
        """Update custom attributes for a conversation using PATCH method."""
        url = f"{self.conversations_url}/{conversation_id}/custom_attributes"
        payload = {"custom_attributes": custom_attributes}
        logger.debug(f"Patching custom attributes for Chatwoot convo {conversation_id}. URL: {url}, Payload: {payload}")
        try:
            async with httpx.AsyncClient(timeout=config.HTTPX_DEFAULT_TIMEOUT) as client:
                response = await client.patch(url, json=payload, headers=self.headers)
                response.raise_for_status()
                logger.info(f"Custom attributes patched successfully for Chatwoot convo {conversation_id}.")
                if response.content and len(response.content.strip()) > 0:
                    return response.json()
                return {} # Return empty dict if no content, as per original
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error patching custom attributes for Chatwoot convo {conversation_id}: {e.response.status_code} - {e.response.text}",
                exc_info=True
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error patching custom attributes for Chatwoot convo {conversation_id}: {e}", exc_info=True)
            raise

    async def toggle_priority(self, conversation_id: int, priority: Optional[str]) -> Dict[str, Any]:
        """Toggle the priority of a conversation. Valid priorities: 'urgent', 'high', 'medium', 'low', or None to clear."""
        url = f"{self.conversations_url}/{conversation_id}/toggle_priority"
        data = {"priority": priority} # API handles None to clear priority
        logger.debug(f"Toggling priority for Chatwoot convo {conversation_id}. URL: {url}, Data: {data}")
        try:
            async with httpx.AsyncClient(timeout=config.HTTPX_DEFAULT_TIMEOUT) as client:
                response = await client.post(url, json=data, headers=self.headers)
                response.raise_for_status()
                logger.info(f"Priority toggled successfully for Chatwoot convo {conversation_id} to {priority}.")
                if response.content and len(response.content.strip()) > 0:
                    return response.json()
                return {}
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error toggling priority for Chatwoot convo {conversation_id}: {e.response.status_code} - {e.response.text}",
                exc_info=True
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error toggling priority for Chatwoot convo {conversation_id}: {e}", exc_info=True)
            raise

    async def assign_team(self, conversation_id: int, team_id: Optional[int]) -> Dict[str, Any]:
        """Assign a conversation to a team. If team_id is None, unassigns from team."""
        url = f"{self.conversations_url}/{conversation_id}/assignments"
        data = {"team_id": team_id}
        logger.debug(f"Assigning Chatwoot convo {conversation_id} to team {team_id}. URL: {url}, Data: {data}")
        try:
            async with httpx.AsyncClient(timeout=config.HTTPX_DEFAULT_TIMEOUT) as client:
                response = await client.post(url, json=data, headers=self.headers)
                response.raise_for_status()
                logger.info(f"Chatwoot convo {conversation_id} assigned successfully to team {team_id}.")
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error assigning Chatwoot convo {conversation_id} to team {team_id}: {e.response.status_code} - {e.response.text}",
                exc_info=True
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error assigning Chatwoot convo {conversation_id} to team {team_id}: {e}", exc_info=True)
            raise

    async def toggle_status(
        self,
        conversation_id: int,
        status: str,
    ) -> Tuple[Dict[str, Any], bool]: # Returns (response_json, should_send_internal_notification)
        """Toggle conversation status. Valid statuses: 'open', 'resolved', 'pending', 'snoozed'."""
        url = f"{self.conversations_url}/{conversation_id}/toggle_status"
        data = {"status": status}
        logger.debug(f"Toggling status for Chatwoot convo {conversation_id}. URL: {url}, Data: {data}")
        
        # This flag will be determined by the caller (ChatwootHandler) based on previous_status and is_error_transition
        # For now, the service method itself doesn't decide to send the message.
        # The boolean return value is a placeholder for the Facade to decide.
        # The original logic was: if status == "open" and previous_status == "pending" and is_error_transition:
        # This method doesn't have previous_status or is_error_transition.
        # The Facade (ChatwootHandler) will need to manage this.
        # So, this service method just performs the status toggle.
        # The Tuple return type is to make it explicit that the Facade needs to handle the notification part.

        try:
            async with httpx.AsyncClient(timeout=config.HTTPX_DEFAULT_TIMEOUT) as client:
                response = await client.post(url, json=data, headers=self.headers)
                response.raise_for_status()
                logger.info(f"Status toggled successfully for Chatwoot convo {conversation_id} to {status}.")
                # The decision to send internal message is deferred to the facade
                return response.json(), False # False means this method doesn't trigger it directly
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error toggling status for Chatwoot convo {conversation_id}: {e.response.status_code} - {e.response.text}",
                exc_info=True
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error toggling status for Chatwoot convo {conversation_id}: {e}", exc_info=True)
            raise

    def toggle_status_sync(
        self,
        conversation_id: int,
        status: str,
    ) -> Tuple[Dict[str, Any], bool]: # Returns (response_json, should_send_internal_notification)
        """Toggle conversation status synchronously."""
        url = f"{self.conversations_url}/{conversation_id}/toggle_status"
        data = {"status": status}
        logger.debug(f"Toggling status sync for Chatwoot convo {conversation_id}. URL: {url}, Data: {data}")
        
        try:
            with httpx.Client(timeout=config.HTTPX_DEFAULT_TIMEOUT) as client:
                response = client.post(url, json=data, headers=self.headers)
                response.raise_for_status()
                logger.info(f"Status toggled successfully sync for Chatwoot convo {conversation_id} to {status}.")
                # Decision to send internal message deferred to facade
                return response.json(), False # False means this method doesn't trigger it directly
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error toggling status sync for Chatwoot convo {conversation_id}: {e.response.status_code} - {e.response.text}",
                exc_info=True
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error toggling status sync for Chatwoot convo {conversation_id}: {e}", exc_info=True)
            raise

    async def get_conversation_list(self, status: str = "all", assignee_type: str = "all", team_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get a list of conversations based on filters."""
        # Original ChatwootHandler get_conversation_list did not have team_id filter.
        # Adding it here as it's a common Chatwoot API parameter.
        params = {"status": status, "assignee_type": assignee_type}
        if team_id is not None:
            params["team_id"] = team_id
        
        url = f"{self.conversations_url}" # Parameters will be added by httpx
        logger.debug(f"Getting Chatwoot conversation list. URL: {url}, Params: {params}")
        try:
            async with httpx.AsyncClient(timeout=config.HTTPX_DEFAULT_TIMEOUT) as client:
                response = await client.get(url, params=params, headers=self.headers)
                response.raise_for_status()
                data = response.json()
                logger.info(f"Conversation list retrieved successfully. Count: {len(data.get('data', {}).get('payload', []))}")
                # The response structure is {"data": {"payload": [...]}}
                return data.get("data", {}).get("payload", []) # Adjusted to match typical Chatwoot structure
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error getting Chatwoot conversation list: {e.response.status_code} - {e.response.text}",
                exc_info=True
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error getting Chatwoot conversation list: {e}", exc_info=True)
            raise

logger.info("ConversationService initialized.")

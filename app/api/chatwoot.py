import logging
from typing import Any, Dict, List, Optional

# No longer directly using httpx here, services handle their clients
# import httpx

from .. import config
# Import the new service classes
from app.services.chatwoot.message_service import MessageService
from app.services.chatwoot.conversation_service import ConversationService
from app.services.chatwoot.admin_service import AdminService

logger = logging.getLogger(__name__)

class ChatwootHandler:
    def __init__(
        self,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        account_id: Optional[str] = None,
        admin_api_key: Optional[str] = None, # Added for completeness, passed to AdminService
    ):
        # Store config values to pass to services
        # Services will use these to construct their own base URLs and headers
        self.effective_api_url = api_url or config.CHATWOOT_API_URL
        self.effective_account_id = account_id or config.CHATWOOT_ACCOUNT_ID
        self.effective_api_key = api_key or config.CHATWOOT_API_KEY
        self.effective_admin_api_key = admin_api_key or config.CHATWOOT_ADMIN_API_KEY

        # Instantiate services
        # Each service will inherit common configs from BaseChatwootService
        self.message_service = MessageService(
            api_url=self.effective_api_url,
            account_id=self.effective_account_id,
            api_key=self.effective_api_key
        )
        self.conversation_service = ConversationService(
            api_url=self.effective_api_url,
            account_id=self.effective_account_id,
            api_key=self.effective_api_key,
            admin_api_key=self.effective_admin_api_key # For get_conversation_data
        )
        self.admin_service = AdminService(
            api_url=self.effective_api_url,
            account_id=self.effective_account_id,
            api_key=self.effective_api_key, # Standard API key for some admin actions if needed
            admin_api_key=self.effective_admin_api_key # Specifically for admin-privileged actions
        )
        logger.info("ChatwootHandler initialized with all services.")

    # --- Message Methods ---
    async def send_message(
        self,
        conversation_id: int,
        message: str,
        private: bool = False,
        attachments: List[str] | None = None,
        content_attributes: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        return await self.message_service.send_message(
            conversation_id=conversation_id,
            message=message,
            private=private,
            attachments=attachments,
            content_attributes=content_attributes,
        )

    def send_message_sync(self, conversation_id: int, message: str, private: bool = False) -> Dict[str, Any]:
        return self.message_service.send_message_sync(
            conversation_id=conversation_id, message=message, private=private
        )

    # --- Conversation Methods ---
    async def add_labels(self, conversation_id: int, labels: List[str]) -> Dict[str, Any]:
        return await self.conversation_service.add_labels(conversation_id=conversation_id, labels=labels)

    async def get_conversation_data(self, conversation_id: int) -> Dict[str, Any]:
        return await self.conversation_service.get_conversation_data(conversation_id=conversation_id)

    async def assign_conversation(self, conversation_id: int, assignee_id: Optional[int] = None) -> Dict[str, Any]:
        return await self.conversation_service.assign_conversation(
            conversation_id=conversation_id, assignee_id=assignee_id
        )

    async def patch_custom_attributes(self, conversation_id: int, custom_attributes: Dict[str, Any]) -> Dict[str, Any]:
        return await self.conversation_service.patch_custom_attributes(
            conversation_id=conversation_id, custom_attributes=custom_attributes
        )

    async def toggle_priority(self, conversation_id: int, priority: Optional[str]) -> Dict[str, Any]:
        return await self.conversation_service.toggle_priority(conversation_id=conversation_id, priority=priority)

    async def assign_team(self, conversation_id: int, team_id: Optional[int] = None, team_name: Optional[str] = None) -> Dict[str, Any]:
        """Assign a conversation to a team. Looks up team_id by name if only name is provided."""
        if team_name and team_id is None: # team_id takes precedence if both are somehow provided
            teams = await self.admin_service.get_teams() # Use AdminService to get teams
            team_map = {team["name"].lower(): team["id"] for team in teams}
            # Ensure team_name is not None before lower()
            resolved_team_id = team_map.get(team_name.lower() if team_name else "", None)
            if resolved_team_id is None:
                logger.warning(f"Team '{team_name}' not found for assigning to conversation {conversation_id}.")
                # Decide behavior: raise error or assign to None (unassign)?
                # Original logic defaults team_id to 0 if not found, which might be an invalid ID.
                # Let's be explicit: if team name is given but not found, either error or pass None to assign_team.
                # Passing None to assign_team method of ConversationService should mean unassignment.
                team_id_to_assign = None
            else:
                team_id_to_assign = resolved_team_id
        else:
            team_id_to_assign = team_id

        return await self.conversation_service.assign_team(
            conversation_id=conversation_id, team_id=team_id_to_assign
        )

    async def toggle_status(
        self,
        conversation_id: int,
        status: str,
        previous_status: Optional[str] = None, # Facade needs this to decide on internal message
        is_error_transition: bool = False,    # Facade needs this
    ) -> Dict[str, Any]:
        # The service method toggle_status now returns (response_json, should_send_notification_flag)
        # However, I simplified the service to not return the flag. The facade will make this decision.
        response_json = await self.conversation_service.toggle_status(
            conversation_id=conversation_id, status=status
        )
        
        # Logic for sending internal notification, now handled by the facade
        if status == "open" and previous_status == "pending" and is_error_transition:
            try:
                logger.info(
                    f"ChatwootHandler: Convo {conversation_id} changed from pending to "
                    "open due to error, sending internal notification."
                )
                # Use MessageService for sending the notification
                await self.message_service.send_message(
                    conversation_id=conversation_id,
                    message=config.BOT_ERROR_MESSAGE_INTERNAL,
                    private=True,
                )
            except Exception as e_notify:
                logger.error(
                    f"ChatwootHandler: Failed to send 'pending to open internal error' "
                    f"notification for convo {conversation_id}: {e_notify}",
                    exc_info=True
                )
        return response_json # Return the main response from status toggle

    def toggle_status_sync(
        self,
        conversation_id: int,
        status: str,
        previous_status: Optional[str] = None, # Facade needs this
        is_error_transition: bool = False,    # Facade needs this
    ) -> Dict[str, Any]:
        response_json = self.conversation_service.toggle_status_sync(
            conversation_id=conversation_id, status=status
        )

        if status == "open" and previous_status == "pending" and is_error_transition:
            try:
                logger.info(
                    f"ChatwootHandler (sync): Convo {conversation_id} changed from pending to open due to error, "
                    "sending internal notification."
                )
                self.message_service.send_message_sync(
                    conversation_id=conversation_id,
                    message=config.BOT_ERROR_MESSAGE_INTERNAL,
                    private=True,
                )
            except Exception as e_notify:
                logger.error(
                    f"ChatwootHandler (sync): Failed to send 'pending to open internal error' notification "
                    f"for convo {conversation_id}: {e_notify}",
                    exc_info=True
                )
        return response_json

    async def get_conversation_list(self, status: str = "all", assignee_type: str = "all", team_id: Optional[int] = None) -> List[Dict[str, Any]]:
        return await self.conversation_service.get_conversation_list(
            status=status, assignee_type=assignee_type, team_id=team_id
        )

    # --- Admin Methods ---
    async def get_teams(self) -> List[Dict[str, Any]]:
        return await self.admin_service.get_teams()

    async def create_custom_attribute_definition(
        self,
        display_name: str,
        attribute_key: str,
        attribute_values: List[str],
        description: str = "",
        attribute_model: int = 0,
    ) -> Dict[str, Any]:
        return await self.admin_service.create_custom_attribute_definition(
            display_name=display_name,
            attribute_key=attribute_key,
            attribute_values=attribute_values,
            description=description,
            attribute_model=attribute_model,
        )

    # Note: If ChatwootHandler was an async context manager or had an explicit close method
    # for a shared httpx.AsyncClient, that would be handled here.
    # Based on the "revised approach", services manage their own clients, so no top-level close needed in ChatwootHandler.
    # async def close_client(self):
    #     # If a shared client was used, close it here.
    #     # await self.shared_async_client.aclose()
    #     logger.info("ChatwootHandler's resources (if any) released.")
    #     pass

logger.info("ChatwootHandler (Facade) initialized using services.")

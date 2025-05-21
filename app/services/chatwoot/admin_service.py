import logging
from typing import Any, Dict, List # Removed Optional: F401 'typing.Optional' imported but unused
import httpx

from .base_service import BaseChatwootService
from app import config # For HTTPX_DEFAULT_TIMEOUT

logger = logging.getLogger(__name__)

class AdminService(BaseChatwootService):
    async def get_teams(self) -> List[Dict[str, Any]]:
        """Fetch all teams from the Chatwoot account. Uses admin headers."""
        url = f"{self.account_url}/teams"
        logger.debug(f"Getting teams from Chatwoot. URL: {url}")
        try:
            async with httpx.AsyncClient(timeout=config.HTTPX_DEFAULT_TIMEOUT) as client:
                response = await client.get(url, headers=self.admin_headers) # Use admin headers
                response.raise_for_status()
                logger.info("Teams retrieved successfully from Chatwoot.")
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error fetching teams from Chatwoot: {e.response.status_code} - {e.response.text}",
                exc_info=True
            )
            # Original code had a fallback to hardcoded teams, replicating that here.
            # This might be desired if the API is flaky but some team data is critical.
            # Consider if this fallback is still appropriate or should be removed for stricter error handling.
            logger.warning("Chatwoot API error for get_teams. Resorting to hardcoded teams as a fallback.")
            return [
                {"id": 3, "name": "срочная служба", "description": "", "allow_auto_assign": True, "private": False, "account_id": int(self.account_id), "is_member": True},
                {"id": 4, "name": "консультанты", "description": "", "allow_auto_assign": True, "private": False, "account_id": int(self.account_id), "is_member": True},
                {"id": 5, "name": "мобилизация", "description": "", "allow_auto_assign": True, "private": False, "account_id": int(self.account_id), "is_member": True},
                {"id": 6, "name": "дезертиры", "description": "", "allow_auto_assign": True, "private": False, "account_id": int(self.account_id), "is_member": True},
            ] # Ensure account_id matches type if necessary
        except httpx.RequestError as e:
            logger.error(f"Request error fetching teams from Chatwoot: {e}", exc_info=True)
            logger.warning("Chatwoot request error for get_teams. Resorting to hardcoded teams as a fallback.")
            return [
                {"id": 3, "name": "срочная служба", "description": "", "allow_auto_assign": True, "private": False, "account_id": int(self.account_id), "is_member": True},
                {"id": 4, "name": "консультанты", "description": "", "allow_auto_assign": True, "private": False, "account_id": int(self.account_id), "is_member": True},
                {"id": 5, "name": "мобилизация", "description": "", "allow_auto_assign": True, "private": False, "account_id": int(self.account_id), "is_member": True},
                {"id": 6, "name": "дезертиры", "description": "", "allow_auto_assign": True, "private": False, "account_id": int(self.account_id), "is_member": True},
            ]
            # raise # Or re-raise depending on how critical real-time data is vs. fallback

    async def create_custom_attribute_definition(
        self,
        display_name: str,
        attribute_key: str,
        attribute_values: List[str],
        description: str = "",
        attribute_model: int = 0, # 0 for conversation, 1 for contact
    ) -> Dict[str, Any]:
        """Create a new custom attribute definition for conversations or contacts."""
        url = f"{self.account_url}/custom_attribute_definitions"
        data = {
            "attribute_display_name": display_name,
            "attribute_display_type": 6,  # 6 represents list type in Chatwoot
            "attribute_description": description,
            "attribute_key": attribute_key,
            "attribute_values": attribute_values,
            "attribute_model": attribute_model,
        }
        logger.debug(f"Creating custom attribute definition in Chatwoot. URL: {url}, Data: {data}")
        try:
            async with httpx.AsyncClient(timeout=config.HTTPX_DEFAULT_TIMEOUT) as client:
                response = await client.post(url, json=data, headers=self.headers) # Standard headers, not admin? Check API spec. Assume standard for now.
                                                                                  # Original ChatwootHandler uses self.headers here.
                response.raise_for_status()
                logger.info(f"Custom attribute definition '{attribute_key}' created successfully in Chatwoot.")
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error creating custom attribute definition '{attribute_key}' in Chatwoot: {e.response.status_code} - {e.response.text}",
                exc_info=True
            )
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error creating custom attribute definition '{attribute_key}' in Chatwoot: {e}", exc_info=True)
            raise

logger.info("AdminService initialized.")

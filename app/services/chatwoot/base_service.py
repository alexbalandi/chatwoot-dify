import logging
# import httpx # Removed: F401 'httpx' imported but unused

from app import config # For CHATWOOT_API_URL, CHATWOOT_ACCOUNT_ID, etc.

logger = logging.getLogger(__name__)

class BaseChatwootService:
    def __init__(
        self,
        api_url: str = config.CHATWOOT_API_URL,
        account_id: str = config.CHATWOOT_ACCOUNT_ID,
        api_key: str = config.CHATWOOT_API_ACCESS_TOKEN,
        admin_api_key: str = config.CHATWOOT_ADMIN_API_ACCESS_TOKEN, # If needed by subclasses
    ):
        self.api_url = api_url.rstrip('/')
        self.account_id = account_id
        self.api_key = api_key
        self.admin_api_key = admin_api_key

        self.base_url = f"{self.api_url}/api/v1"
        self.account_url = f"{self.base_url}/accounts/{self.account_id}"
        self.conversations_url = f"{self.account_url}/conversations"
        self.contacts_url = f"{self.account_url}/contacts" # Added for completeness, might be used later

        self.headers = {
            "Content-Type": "application/json; charset=utf-8",
            "api_access_token": self.api_key,
        }
        
        self.admin_headers = {
            "Content-Type": "application/json; charset=utf-8",
            "api_access_token": self.admin_api_key, # Use admin token for admin operations
        }

    # Common helper methods for making HTTP requests can be added here if desired,
    # but for now, following the revised strategy, each service method will manage its client.
    # Example of a helper (if we weren't using `async with` in each method):
    # async def _request(self, client: httpx.AsyncClient, method: str, url: str, **kwargs):
    #     try:
    #         response = await client.request(method, url, **kwargs)
    #         response.raise_for_status()
    #         return response
    #     except httpx.HTTPStatusError as e:
    #         logger.error(f"HTTP error {e.response.status_code} for {method} {url}: {e.response.text}")
    #         # Depending on strategy, either raise a custom error or re-raise
    #         raise
    #     except httpx.RequestError as e:
    #         logger.error(f"Request error for {method} {url}: {e}")
    #         raise

    # Similarly for sync requests
    # def _request_sync(self, client: httpx.Client, method: str, url: str, **kwargs):
    #     try:
    #         response = client.request(method, url, **kwargs)
    #         response.raise_for_status()
    #         return response
    #     except httpx.HTTPStatusError as e:
    #         logger.error(f"Sync HTTP error {e.response.status_code} for {method} {url}: {e.response.text}")
    #         raise
    #     except httpx.RequestError as e:
    #         logger.error(f"Sync request error for {method} {url}: {e}")
    #         raise

logger.info("BaseChatwootService initialized.")

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional # Keep all these as they are likely used by various actions

from fastapi import (
    APIRouter,
    # BackgroundTasks, # Not used by moved actions
    Body,             # Used by some actions
    Depends,          # Used by actions needing DB
    FastAPI,          # For lifespan
    HTTPException,    # Used for error responses
    # Request,        # Not used by moved actions
)
from sqlalchemy.ext.asyncio import AsyncSession # Used by actions needing DB
from sqlalchemy.future import select            # Used by actions needing DB

# from .. import tasks # Not used by moved actions
# from ..config import ( # Specific config messages not used by actions
#    BOT_CONVERSATION_OPENED_MESSAGE_EXTERNAL,
#    BOT_ERROR_MESSAGE_INTERNAL,
# )
from ..database import get_db # Used by actions needing DB
from ..models.database import Dialogue # Used by get_chatwoot_conversation_id, get_dialogue_info
from ..models.non_database import ConversationPriority, ConversationStatus # Used by toggle_priority, toggle_status
from .chatwoot import ChatwootHandler

logger = logging.getLogger(__name__)
actions_router = APIRouter()
chatwoot = ChatwootHandler()

# Team management cache and functions
team_cache: Dict[str, int] = {}
team_cache_lock = asyncio.Lock()
last_update_time = 0

async def update_team_cache():
    """Update the team name to ID mapping cache."""
    global team_cache, last_update_time
    async with team_cache_lock:
        try:
            teams = await chatwoot.get_teams()
            new_cache = {team["name"].lower(): team["id"] for team in teams}
            team_cache = new_cache
            last_update_time = datetime.utcnow().timestamp()
            logger.info(f"Updated team cache with {len(team_cache)} teams")
            return team_cache
        except Exception as e:
            logger.error(f"Failed to update team cache: {e}", exc_info=True)
            raise

async def get_team_id(team_name: str) -> Optional[int]:
    """Get team ID from name, updating cache if necessary."""
    if not team_cache or (datetime.utcnow().timestamp() - last_update_time) > 24 * 3600:  # Cache for 24 hours
        await update_team_cache()
    return team_cache.get(team_name.lower())

@asynccontextmanager
async def lifespan(app: FastAPI): # app: FastAPI is needed here by FastAPI's lifespan convention
    """Lifespan events manager for actions_router."""
    try:
        await update_team_cache()
        logger.info(f"Initialized team cache for actions_router with {len(team_cache)} teams")
    except Exception as e:
        logger.error(f"Failed to initialize team cache for actions_router: {e}", exc_info=True)
    yield
    # Shutdown logic can go here if needed

actions_router.router.lifespan_context = lifespan

@actions_router.post("/send-chatwoot-message")
async def send_chatwoot_message(
    conversation_id: int,
    message: str,
    is_private: bool = False,
    # db: AsyncSession = Depends(get_db), # Removed as ChatwootHandler doesn't need DB for this
):
    """
    Send a message to Chatwoot conversation.
    Can be used as a private note if is_private=True
    """
    try:
        await chatwoot.send_message(
            conversation_id=conversation_id,
            message=message,
            private=is_private,
        )
        return {"status": "success", "message": "Message sent successfully"}
    except Exception as e:
        logger.error(f"Failed to send message to Chatwoot conversation {conversation_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to send message to Chatwoot: {str(e)}") from e

@actions_router.post("/update-labels/{conversation_id}")
async def update_labels(conversation_id: int, labels: List[str]): # Removed db: AsyncSession = Depends(get_db)
    """
    Update labels for a Chatwoot conversation
    """
    try:
        result = await chatwoot.add_labels(conversation_id=conversation_id, labels=labels)
        return {
            "status": "success",
            "conversation_id": conversation_id,
            "labels": result,
        }
    except Exception as e:
        logger.error(f"Failed to update labels for conversation {conversation_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update labels: {str(e)}") from e

@actions_router.post("/update-custom-attributes/{conversation_id}")
async def update_custom_attributes(
    conversation_id: int,
    custom_attributes: Dict[str, Any],
    # db: AsyncSession = Depends(get_db), # Removed
):
    """
    Update custom attributes for a Chatwoot conversation
    """
    if not isinstance(custom_attributes, dict) or not custom_attributes:
        return {
            "status": "success",
            "conversation_id": conversation_id,
            "custom_attributes": "No custom attrs provided",
        }
    try:
        result = await chatwoot.patch_custom_attributes(
            conversation_id=conversation_id, custom_attributes=custom_attributes
        )
        logger.info(f"Updated custom attributes for conversation {conversation_id}: {result}")
        return {
            "status": "success",
            "conversation_id": conversation_id,
            "custom_attributes": result,
        }
    except Exception as e:
        logger.exception(f"Failed to update custom attributes for conversation {conversation_id}:")
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "conversation_id": conversation_id,
                "attempted_attributes": custom_attributes
            },
        ) from e

@actions_router.post("/toggle-priority/{conversation_id}")
async def toggle_conversation_priority(
    conversation_id: int,
    priority: ConversationPriority = Body(
        ..., # Ellipsis means this field is required
        embed=True,
        description="Priority level: 'urgent', 'high', 'medium', 'low', or None",
    ),
    # db: AsyncSession = Depends(get_db), # Removed
):
    """
    Toggle the priority of a Chatwoot conversation
    """
    try:
        priority_value = priority.value if priority else None # Handle if priority can be None from enum
        
        # If priority_value is None, it means client wants to clear priority.
        # ChatwootHandler's toggle_priority should handle priority=None.
        logger.info(f"Attempting to set priority '{priority_value}' for conversation {conversation_id}")
        result = await chatwoot.toggle_priority(conversation_id=conversation_id, priority=priority_value)
        return {
            "status": "success",
            "conversation_id": conversation_id,
            "priority": result.get("priority", priority_value) if result else priority_value,
        }
    except Exception as e:
        logger.exception(f"Detailed error when toggling priority for conversation {conversation_id}:")
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "conversation_id": conversation_id,
                "attempted_priority": priority.value if priority else "None",
            },
        ) from e

@actions_router.get("/conversations/dify/{dify_conversation_id}")
async def get_chatwoot_conversation_id(dify_conversation_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get Chatwoot conversation ID from Dify conversation ID
    """
    statement = select(Dialogue).where(Dialogue.dify_conversation_id == dify_conversation_id)
    dialogue_result = await db.execute(statement)
    dialogue = dialogue_result.scalar_one_or_none()

    if not dialogue:
        raise HTTPException(
            status_code=404,
            detail=f"No conversation found with Dify ID: {dify_conversation_id}",
        )
    return {
        "chatwoot_conversation_id": dialogue.chatwoot_conversation_id,
        "status": dialogue.status,
        "assignee_id": dialogue.assignee_id,
    }

@actions_router.get("/dialogue-info/{chatwoot_conversation_id}")
async def get_dialogue_info(chatwoot_conversation_id: str, db: AsyncSession = Depends(get_db)):
    """
    Retrieve dialogue information, including the Dify conversation ID,
    based on the Chatwoot conversation ID.
    """
    logger.debug(f"Received request for dialogue info for Chatwoot convo ID: {chatwoot_conversation_id}")
    statement = select(Dialogue).where(Dialogue.chatwoot_conversation_id == chatwoot_conversation_id)
    result = await db.execute(statement)
    dialogue = result.scalar_one_or_none()

    if not dialogue:
        logger.warning(f"Dialogue not found for Chatwoot convo ID: {chatwoot_conversation_id}")
        raise HTTPException(
            status_code=404,
            detail=f"Dialogue not found for Chatwoot conversation ID {chatwoot_conversation_id}",
        )
    logger.debug(
        f"Found dialogue for Chatwoot convo ID {chatwoot_conversation_id}: Dify ID = {dialogue.dify_conversation_id}"
    )
    return {
        "chatwoot_conversation_id": dialogue.chatwoot_conversation_id,
        "dify_conversation_id": dialogue.dify_conversation_id,
        "status": dialogue.status,
        "created_at": dialogue.created_at,
        "updated_at": dialogue.updated_at,
    }

@actions_router.post("/refresh-teams")
async def refresh_teams_cache_endpoint():
    """Manually refresh the team cache."""
    try:
        teams = await update_team_cache()
        return {"status": "success", "teams_cached": len(teams)}
    except Exception as e:
        logger.error(f"Failed to refresh teams cache via endpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to refresh teams: {str(e)}") from e

@actions_router.post("/assign-team/{conversation_id}")
async def assign_conversation_to_team(
    conversation_id: int,
    team: str = Body(
        ...,
        embed=True,
        description="Team name to assign the conversation to. Case-insensitive. Send 'None' or empty to unassign.",
    ),
    # db: AsyncSession = Depends(get_db), # Removed
):
    """
    Assign a Chatwoot conversation to a team.
    Team name matching is case-insensitive. 'None' or empty string unassigns.
    """
    team_id_to_assign: Optional[int] = None
    team_display_name = "None (unassigned)"

    if team and team.strip().lower() not in ["none", ""]:
        team_name_stripped = team.strip()
        team_display_name = team_name_stripped
        logger.info(f"Attempting to assign conversation {conversation_id} to team '{team_name_stripped}'")
        team_id_to_assign = await get_team_id(team_name_stripped)

        if team_id_to_assign is None:
            logger.info(f"Team '{team_name_stripped}' not found in cache. Refreshing cache and retrying.")
            await update_team_cache() # Attempt a cache refresh
            team_id_to_assign = await get_team_id(team_name_stripped)

            if team_id_to_assign is None:
                logger.warning(f"Team '{team_name_stripped}' not found after cache refresh for conversation {conversation_id}.")
                current_teams = list(name.capitalize() for name in team_cache.keys())
                raise HTTPException(
                    status_code=404,
                    detail=f"Team '{team_name_stripped}' not found. Available teams: {current_teams if current_teams else 'No teams in cache. Try refreshing teams.'}",
                )
    else: # Unassign if team is "none", empty or None
        logger.info(f"Attempting to unassign team from conversation {conversation_id}")
    
    try:
        result = await chatwoot.assign_team(conversation_id=conversation_id, team_id=team_id_to_assign)
        logger.info(f"Successfully assigned conversation {conversation_id} to team '{team_display_name}' (ID: {team_id_to_assign})")
        return {
            "status": "success",
            "conversation_id": conversation_id,
            "team_assigned": team_display_name,
            "team_id": team_id_to_assign,
            "result": result,
        }
    except Exception as e:
        logger.exception(f"Error assigning/unassigning team for conversation {conversation_id}:")
        raise HTTPException(status_code=500, detail=str(e))

@actions_router.post("/toggle-status/{conversation_id}")
async def toggle_conversation_status(
    conversation_id: int,
    status: ConversationStatus = Body(..., embed=True, description="Status to set: 'open', 'pending', 'resolved', 'snoozed'"),
    # db: AsyncSession = Depends(get_db), # Removed
):
    """
    Toggle the status of a Chatwoot conversation.
    """
    try:
        # Fetching current status to provide context for the toggle_status method in ChatwootHandler
        # This is needed for the facade (ChatwootHandler) to decide on internal notifications.
        previous_status_val: Optional[str] = None
        try:
            conversation_data = await chatwoot.get_conversation_data(conversation_id)
            previous_status_val = conversation_data.get("status")
            logger.info(f"Current status for convo {conversation_id} before toggle: {previous_status_val}")
        except Exception as e_get_status:
            logger.warning(f"Could not fetch current status for convo {conversation_id} before toggle: {e_get_status}. Proceeding without it.")

        result = await chatwoot.toggle_status(
            conversation_id=conversation_id,
            status=status.value,
            previous_status=previous_status_val, # Pass to facade
            is_error_transition=False, # This is a direct API action, not an error-induced one by the system
        )
        return {
            "status": "success",
            "conversation_id": conversation_id,
            "new_status": status.value,
            "result": result,
        }
    except Exception as e:
        logger.exception(f"Failed to toggle status for conversation {conversation_id} to {status.value}:")
        raise HTTPException(
            status_code=500,
            detail={"error": str(e), "conversation_id": conversation_id, "attempted_status": status.value},
        ) from e

logger.info("Chatwoot actions router initialized with all action endpoints and refined imports.")

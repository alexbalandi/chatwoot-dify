import random
import string
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.chatwoot import ChatwootHandler

# Mark all tests in this file as requiring the event loop
pytestmark = pytest.mark.asyncio


# Helper function to generate random strings for testing
def random_string(length=10):
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


async def test_chatwoot_connection(chatwoot_handler, wait_for_service):
    """Test that we can connect to Chatwoot."""

    async def check_chatwoot():
        teams = await chatwoot_handler.get_teams()
        return len(teams) > 0

    # Wait for Chatwoot to be available
    is_available = await wait_for_service(check_chatwoot)
    assert is_available, "Chatwoot service is not available"

    # Get teams to verify connection
    teams = await chatwoot_handler.get_teams()
    assert len(teams) > 0, "Expected at least one team in Chatwoot"


async def test_chatwoot_connection_with_mock(mock_chatwoot_handler):
    """Test Chatwoot connection using mock for unit testing."""
    # Test using the mock handler
    teams = await mock_chatwoot_handler.get_teams()
    assert len(teams) > 0
    assert teams[0]["name"] == "Test Team"


async def test_send_message(chatwoot_handler, new_chatwoot_conversation):
    """Test sending a message to a conversation."""
    message = (
        f"Test message {random_string()} at {datetime.now(timezone.utc).isoformat()} - "
        "Acknowledge receiving by saying `I see a test message`"
    )
    result = await chatwoot_handler.send_message(
        conversation_id=new_chatwoot_conversation, message=message, private=True
    )
    assert result is not None
    assert "id" in result, "Expected response to contain message ID"


async def test_send_message_with_mock(mock_chatwoot_handler):
    """Test sending a message using mock."""
    message = f"Test message {random_string()}"
    result = await mock_chatwoot_handler.send_message(conversation_id=123, message=message, private=True)

    assert result is not None
    assert result["id"] == 123
    assert result["content"] == "Test response"


async def test_update_conversation_status(chatwoot_handler, new_chatwoot_conversation):
    """Test updating conversation status."""
    conversation_data = await chatwoot_handler.get_conversation_data(new_chatwoot_conversation)
    original_status = conversation_data.get("status", "open")
    new_status = "resolved" if original_status != "resolved" else "open"
    result = await chatwoot_handler.toggle_status(conversation_id=new_chatwoot_conversation, status=new_status)
    print("toggle_status response:", result)
    assert result["payload"]["success"] is True
    updated_conversation = await chatwoot_handler.get_conversation_data(new_chatwoot_conversation)
    assert updated_conversation["status"] == new_status
    await chatwoot_handler.toggle_status(conversation_id=new_chatwoot_conversation, status=original_status)


async def test_update_conversation_status_with_mock(mock_chatwoot_handler):
    """Test updating conversation status using mock."""
    # Mock the get_conversation_data to return current status
    mock_chatwoot_handler.get_conversation_data.return_value = {"status": "pending"}

    result = await mock_chatwoot_handler.toggle_status(conversation_id=123, status="open")
    assert result is not None
    assert result["status"] == "success"


async def test_add_labels(chatwoot_handler, new_chatwoot_conversation):
    """Test adding labels to a conversation."""
    test_label = "test_label"
    result = await chatwoot_handler.add_labels(conversation_id=new_chatwoot_conversation, labels=[test_label])
    print("add_labels response:", result)
    assert isinstance(result.get("payload"), list)
    conversation_data = await chatwoot_handler.get_conversation_data(new_chatwoot_conversation)
    assert test_label in conversation_data.get("labels", [])


async def test_add_labels_with_mock(mock_chatwoot_handler):
    """Test adding labels using mock."""
    test_label = f"test-label-{random_string(5)}"

    # Update mock to return the label
    mock_chatwoot_handler.get_conversation_data.return_value = {"labels": [test_label]}

    result = await mock_chatwoot_handler.add_labels(conversation_id=123, labels=[test_label])
    assert result is not None

    # Verify label was added
    conversation_data = await mock_chatwoot_handler.get_conversation_data(123)
    assert test_label in conversation_data["labels"]


async def test_update_custom_attributes(chatwoot_handler, new_chatwoot_conversation):
    """Test updating custom attributes."""
    test_attribute_key = f"test_attr_{random_string(5)}"
    test_attribute_value = f"value_{random_string(5)}"
    result = await chatwoot_handler.update_custom_attributes(
        conversation_id=new_chatwoot_conversation,
        custom_attributes={test_attribute_key: test_attribute_value},
    )
    print("update_custom_attributes response:", result)
    assert "custom_attributes" in result
    conversation_data = await chatwoot_handler.get_conversation_data(new_chatwoot_conversation)
    assert conversation_data["custom_attributes"].get(test_attribute_key) == test_attribute_value


async def test_update_custom_attributes_with_mock(mock_chatwoot_handler):
    """Test updating custom attributes using mock."""
    test_key = f"test_attr_{random_string(5)}"
    test_value = f"value_{random_string(5)}"

    # Update mock to return the custom attributes
    mock_chatwoot_handler.get_conversation_data.return_value = {"custom_attributes": {test_key: test_value}}

    result = await mock_chatwoot_handler.update_custom_attributes(
        conversation_id=123, custom_attributes={test_key: test_value}
    )
    assert result is not None

    # Verify attribute was added
    conversation_data = await mock_chatwoot_handler.get_conversation_data(123)
    assert test_key in conversation_data["custom_attributes"]
    assert conversation_data["custom_attributes"][test_key] == test_value


async def test_toggle_priority(chatwoot_handler, new_chatwoot_conversation):
    """Test toggling priority of a conversation."""
    conversation_data = await chatwoot_handler.get_conversation_data(new_chatwoot_conversation)
    original_priority = conversation_data.get("priority", "medium")
    new_priority = "high" if original_priority != "high" else "medium"
    result = await chatwoot_handler.toggle_priority(conversation_id=new_chatwoot_conversation, priority=new_priority)
    print("toggle_priority response:", result)
    assert result == {}  # Empty dict means success
    updated_conversation = await chatwoot_handler.get_conversation_data(new_chatwoot_conversation)
    assert updated_conversation["priority"] == new_priority
    await chatwoot_handler.toggle_priority(conversation_id=new_chatwoot_conversation, priority=original_priority)


async def test_toggle_priority_with_mock(mock_chatwoot_handler):
    """Test toggling priority using mock."""
    # Mock initial priority
    mock_chatwoot_handler.get_conversation_data.side_effect = [
        {"priority": "low"},  # Initial call
        {"priority": "high"},  # After update call
    ]

    result = await mock_chatwoot_handler.toggle_priority(conversation_id=123, priority="high")
    assert result is not None
    assert result["status"] == "success"


async def test_error_handling_invalid_conversation_id(chatwoot_handler):
    """Test error handling when using invalid conversation ID."""

    invalid_id = 99999999  # Assuming this ID doesn't exist

    # Attempt to get conversation data
    with pytest.raises(httpx.HTTPStatusError):
        await chatwoot_handler.get_conversation_data(invalid_id)


async def test_error_handling_with_mock():
    """Test error handling using mock."""
    mock_handler = AsyncMock(spec=ChatwootHandler)
    mock_handler.get_conversation_data.side_effect = Exception("Conversation not found")

    with pytest.raises(Exception) as exc_info:
        await mock_handler.get_conversation_data(99999999)

    assert "Conversation not found" in str(exc_info.value)


async def test_webhook_payload_validation(chatwoot_webhook_factory):
    """Test webhook payload validation with Pydantic v2 schemas."""
    # Test valid webhook payload
    webhook = chatwoot_webhook_factory(
        event="message_created",
        message_type="incoming",
        content="Test message",
        conversation_id=123,
        sender_id=456,
    )

    assert webhook.event == "message_created"
    assert webhook.message_type == "incoming"
    assert webhook.content == "Test message"
    assert webhook.conversation_id == 123
    assert webhook.sender_id == 456


async def test_webhook_payload_computed_fields(chatwoot_webhook_factory):
    """Test webhook payload computed fields work correctly."""
    webhook = chatwoot_webhook_factory(conversation_id=123, sender_id=456)

    # Test computed fields
    assert webhook.conversation_id == 123
    assert webhook.sender_id == 456
    assert webhook.assignee_id is None  # Should be None based on factory default


async def test_database_integration_with_chatwoot_data(
    async_session: AsyncSession, conversation_factory, chatwoot_webhook_factory
):
    """Test integration between Chatwoot webhook data and database operations."""
    # Create webhook data
    webhook = chatwoot_webhook_factory(conversation_id=12345, sender_id=67890)

    # Create conversation based on webhook data
    conversation = conversation_factory(chatwoot_conversation_id=str(webhook.conversation_id), status="pending")

    # Add to database
    async_session.add(conversation)
    await async_session.commit()
    await async_session.refresh(conversation)

    # Verify database entry
    assert conversation.id is not None
    assert conversation.chatwoot_conversation_id == "12345"
    assert conversation.status == "pending"


async def test_chatwoot_handler_with_database_operations(
    async_session: AsyncSession, mock_chatwoot_handler, conversation_factory
):
    """Test combining Chatwoot handler operations with database updates."""
    # Create a conversation in the database
    conversation = conversation_factory(
        chatwoot_conversation_id="12345",  # Use numeric string
        status="pending",
    )
    async_session.add(conversation)
    await async_session.commit()
    await async_session.refresh(conversation)

    # Mock Chatwoot operations
    mock_chatwoot_handler.toggle_status.return_value = {"status": "success"}

    # Simulate updating status both in Chatwoot and database
    chatwoot_result = await mock_chatwoot_handler.toggle_status(
        conversation_id=int(conversation.chatwoot_conversation_id), status="open"
    )

    # Update database
    conversation.status = "open"
    await async_session.commit()
    await async_session.refresh(conversation)  # Refresh after commit

    # Verify both operations
    assert chatwoot_result["status"] == "success"
    assert conversation.status == "open"


async def test_bulk_conversation_processing(async_session: AsyncSession, conversation_factory, mock_chatwoot_handler):
    """Test processing multiple conversations efficiently."""
    # Create multiple conversations
    conversations = [conversation_factory(chatwoot_conversation_id=f"conv_{i}", status="pending") for i in range(3)]

    for conv in conversations:
        async_session.add(conv)
    await async_session.commit()

    # Refresh all objects to avoid lazy loading issues
    for conv in conversations:
        await async_session.refresh(conv)

    # Mock bulk operations
    mock_chatwoot_handler.get_conversation_data.return_value = {"status": "processed"}

    # Process all conversations - access chatwoot_conversation_id early to avoid lazy loading
    conv_ids = [conv.chatwoot_conversation_id for conv in conversations]
    results = []
    for conv_id in conv_ids:
        result = await mock_chatwoot_handler.get_conversation_data(conv_id)
        results.append(result)

    # Verify all operations succeeded
    assert len(results) == 3
    assert all(result["status"] == "processed" for result in results)

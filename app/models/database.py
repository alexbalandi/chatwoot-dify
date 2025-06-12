from datetime import UTC, datetime
from typing import Literal, Optional

from sqlalchemy import Column
from sqlalchemy.types import DateTime as SqlaDateTime
from sqlmodel import Field, SQLModel


class Dialogue(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    chatwoot_conversation_id: str = Field(index=True)
    dify_conversation_id: Optional[str] = Field(default=None)
    status: str = Field(default="pending")
    assignee_id: Optional[int] = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            SqlaDateTime(timezone=True),
            nullable=False,
            default=lambda: datetime.now(UTC),
        ),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(
            SqlaDateTime(timezone=True),
            nullable=False,
            default=lambda: datetime.now(UTC),
            onupdate=lambda: datetime.now(UTC),
        ),
    )


# This can be used for both validation and creation
class DialogueCreate(SQLModel):
    chatwoot_conversation_id: str
    status: str = "pending"
    assignee_id: Optional[int] = None
    dify_conversation_id: Optional[str] = None


# Chatwoot webhook models
class ChatwootSender(SQLModel):
    id: Optional[int] = None
    type: Optional[str] = None  # "user", "agent_bot", etc.


class ChatwootMeta(SQLModel):
    assignee: Optional[dict] = None

    @property
    def assignee_id(self) -> Optional[int]:
        return self.assignee.get("id") if self.assignee else None


class ChatwootConversation(SQLModel):
    id: int
    status: str = "pending"
    inbox_id: Optional[int] = None
    meta: ChatwootMeta = Field(default_factory=ChatwootMeta)

    @property
    def assignee_id(self) -> Optional[int]:
        return self.meta.assignee_id


class ChatwootMessage(SQLModel):
    id: int
    content: str
    message_type: Literal["incoming", "outgoing"]
    conversation: ChatwootConversation
    sender: ChatwootSender


class ChatwootWebhook(SQLModel):
    event: str
    message_type: Literal["incoming", "outgoing"]  # TODO: ideally remove this
    sender: Optional[ChatwootSender] = None  # From payload["sender"]
    message: Optional[ChatwootMessage] = None
    conversation: Optional[ChatwootConversation] = None
    content: Optional[str] = None  # From payload["content"]
    echo_id: Optional[str] = None  # To identify AI-generated messages

    @property
    def sender_id(self) -> Optional[int]:
        """Get sender ID from the top-level sender field"""
        return self.sender.id if self.sender else None

    @property
    def conversation_id(self) -> Optional[int]:
        """Get conversation ID from either message or conversation"""
        if self.message and self.message.conversation:
            return self.message.conversation.id
        elif self.conversation:
            return self.conversation.id
        return None

    @property
    def assignee_id(self) -> Optional[int]:
        """Get assignee ID from conversation meta"""
        if self.message and self.message.conversation:
            return self.message.conversation.assignee_id
        elif self.conversation:
            return self.conversation.assignee_id
        return None

    @property
    def derived_message_type(self) -> Optional[str]:
        """Get message type from the nested message object"""
        return self.message.message_type if self.message else None

    @property
    def status(self) -> Optional[str]:
        """Get status from conversation"""
        if self.conversation:
            return self.conversation.status
        return None

    @property
    def sender_type(self) -> Optional[str]:
        """Get sender type"""
        return self.sender.type if self.sender else None

    def to_dialogue_create(self) -> DialogueCreate:
        return DialogueCreate(
            chatwoot_conversation_id=str(self.conversation_id),
            status=self.status or "open",
            assignee_id=self.assignee_id,
        )


class DifyResponse(SQLModel):
    event: Optional[str] = None
    task_id: Optional[str] = None
    id: Optional[str] = None
    message_id: Optional[str] = None
    conversation_id: Optional[str] = None
    mode: Optional[str] = None
    answer: str  # This is the only required field
    response_metadata: Optional[dict] = None
    created_at: Optional[int] = None

    @classmethod
    def error_response(cls) -> "DifyResponse":
        """Create an error response object"""
        return cls(
            answer=(
                "I apologize, but I'm temporarily unavailable. "
                "Please try again later or wait for a human operator to respond."
            )
        )

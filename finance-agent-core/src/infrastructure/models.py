import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Index, String, Text

from .database import Base


class ChatMessage(Base):
    __tablename__ = "chat_history"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    thread_id = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False)  # 'user', 'assistant', 'system', 'tool'
    content = Column(Text, nullable=False)
    message_type = Column(String)  # 'human', 'ai', 'tool'
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    metadata_ = Column(JSON, default={})

    # Compound index for efficient session retrieval with ordering
    __table_args__ = (Index("idx_thread_created", "thread_id", "created_at"),)

    def to_dict(self):
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "type": self.metadata_.get("type", "text") if self.metadata_ else "text",
            "data": self.metadata_.get("data") if self.metadata_ else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Artifact(Base):
    """
    Stores large JSON artifacts (e.g., news items, financial statements, price data).
    Supports reference-based state management to avoid duplicating large data in checkpoints.
    """

    __tablename__ = "artifacts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    key = Column(
        String, nullable=True, index=True
    )  # Optional semantic key for debugging
    thread_id = Column(String, nullable=True, index=True)  # Optional thread association
    type = Column(String, nullable=False)  # e.g., "news_items", "financial_statements"
    data = Column(JSON, nullable=False)  # The actual artifact payload
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "key": self.key,
            "thread_id": self.thread_id,
            "type": self.type,
            "data": self.data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base


class NotificationEventModel(Base):
    __tablename__ = "notification_events"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    event_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    notification_type: Mapped[str] = mapped_column(String(80), nullable=False)
    organization_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("auth_organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    action_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    action_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        CheckConstraint(
            "(action_type IS NULL AND action_ref IS NULL) OR "
            "(action_type IS NOT NULL AND action_ref IS NOT NULL)",
            name="ck_notification_event_action_pair",
        ),
        Index("idx_notification_event_created", "created_at", "id"),
    )


class NotificationInboxItemModel(Base):
    __tablename__ = "notification_inbox_items"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    event_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("notification_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "recipient_user_id",
            name="uq_notification_inbox_event_recipient",
        ),
        Index(
            "idx_notification_inbox_recipient_created",
            "recipient_user_id",
            "created_at",
            "id",
        ),
        Index(
            "idx_notification_inbox_recipient_unread",
            "recipient_user_id",
            "read_at",
        ),
    )

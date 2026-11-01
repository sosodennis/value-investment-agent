from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.database import Base


class AuditEventModel(Base):
    __tablename__ = "auth_audit_events"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("auth_organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(
        String(128),
        ForeignKey("auth_users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    actor_system: Mapped[str | None] = mapped_column(String(120), nullable=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('user', 'system')",
            name="ck_auth_audit_actor_type",
        ),
        CheckConstraint(
            "outcome IN ('success', 'denied', 'failure')",
            name="ck_auth_audit_outcome",
        ),
        CheckConstraint(
            "(actor_type = 'user' AND actor_user_id IS NOT NULL AND actor_system IS NULL) OR "
            "(actor_type = 'system' AND actor_user_id IS NULL AND actor_system IS NOT NULL)",
            name="ck_auth_audit_actor_identity",
        ),
        Index(
            "idx_auth_audit_organization_time",
            "organization_id",
            "occurred_at",
            "id",
        ),
        Index("idx_auth_audit_correlation", "correlation_id"),
    )


def utc_now() -> datetime:
    return datetime.now(UTC)

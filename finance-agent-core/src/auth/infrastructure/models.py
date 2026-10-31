from __future__ import annotations

import uuid
from datetime import datetime

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


class UserModel(Base):
    __tablename__ = "auth_users"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(
        String(320), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )


class OrganizationModel(Base):
    __tablename__ = "auth_organizations"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )


class MembershipModel(Base):
    __tablename__ = "auth_memberships"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("auth_organizations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "user_id", name="uq_auth_membership_organization_user"
        ),
        CheckConstraint(
            "role IN ('owner', 'admin', 'member')",
            name="ck_auth_membership_role",
        ),
        CheckConstraint(
            "status IN ('pending', 'active', 'suspended', 'removed')",
            name="ck_auth_membership_status",
        ),
        Index("idx_auth_membership_user_status", "user_id", "status"),
    )


class OrganizationLifecycleEventModel(Base):
    __tablename__ = "auth_organization_lifecycle_events"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("auth_organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_user_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True
    )
    payload: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )


class SessionModel(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    active_organization_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("auth_organizations.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )


class OwnedResourceModel(Base):
    __tablename__ = "auth_owned_resources"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("resource_type", "resource_id", name="uq_auth_owned_resource"),
        Index("idx_auth_owned_resource_user_type", "user_id", "resource_type"),
    )

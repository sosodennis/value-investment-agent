from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.auth.domain.entities import AuthenticatedContext


class Principal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    subject: str
    email: str
    organization_id: str
    membership_id: str
    role: Literal["user"] = "user"
    auth_type: Literal["session"] = "session"

    @classmethod
    def from_context(cls, context: AuthenticatedContext) -> Principal:
        return cls(
            user_id=context.user.id,
            subject=context.user.id,
            email=context.user.email,
            organization_id=context.membership.organization_id,
            membership_id=context.membership.id,
        )


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)


class SelectOrganizationRequest(BaseModel):
    organization_id: str = Field(min_length=1, max_length=128)


class OrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class OrganizationRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class OrganizationRoleChangeRequest(BaseModel):
    role: Literal["admin", "member"]


class OrganizationStatusChangeRequest(BaseModel):
    status: Literal["active", "suspended", "removed"]


class OrganizationOwnershipTransferRequest(BaseModel):
    target_user_id: str = Field(min_length=1, max_length=128)


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_id: str
    name: str
    created_at: datetime
    membership_id: str
    role: Literal["owner", "admin", "member"]
    status: Literal["pending", "active", "suspended", "removed"]


class OrganizationMemberResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    email: str
    membership_id: str
    organization_id: str
    role: Literal["owner", "admin", "member"]
    status: Literal["pending", "active", "suspended", "removed"]
    created_at: datetime
    updated_at: datetime

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.auth.domain.entities import UserRecord


class Principal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    subject: str
    email: str
    role: Literal["user"] = "user"
    auth_type: Literal["session"] = "session"

    @classmethod
    def from_user(cls, user: UserRecord) -> Principal:
        return cls(user_id=user.id, subject=user.id, email=user.email)


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.auth.application.errors import RegistrationConflictError
from src.auth.domain.entities import SessionRecord, UserRecord
from src.auth.infrastructure.models import (
    OwnedResourceModel,
    SessionModel,
    UserModel,
)
from src.infrastructure.database import AsyncSessionLocal


class SqlAlchemyUserRepository:
    async def get_by_email(self, email: str) -> UserRecord | None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserModel).where(UserModel.email == email)
            )
            model = result.scalar_one_or_none()
        return self._to_record(model) if model else None

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        async with AsyncSessionLocal() as session:
            model = await session.get(UserModel, user_id)
        return self._to_record(model) if model else None

    async def create(self, *, email: str, password_hash: str) -> UserRecord:
        model = UserModel(email=email, password_hash=password_hash)
        async with AsyncSessionLocal() as session:
            session.add(model)
            try:
                await session.commit()
                await session.refresh(model)
            except IntegrityError as exc:
                await session.rollback()
                raise RegistrationConflictError("email is already registered") from exc
        return self._to_record(model)

    @staticmethod
    def _to_record(model: UserModel) -> UserRecord:
        return UserRecord(
            id=model.id,
            email=model.email,
            password_hash=model.password_hash,
            created_at=model.created_at,
        )


class SqlAlchemySessionRepository:
    async def create(
        self,
        *,
        user_id: str,
        token_hash: str,
        csrf_token_hash: str,
        expires_at: datetime,
    ) -> SessionRecord:
        model = SessionModel(
            user_id=user_id,
            token_hash=token_hash,
            csrf_token_hash=csrf_token_hash,
            expires_at=expires_at,
        )
        async with AsyncSessionLocal() as session:
            session.add(model)
            await session.commit()
            await session.refresh(model)
        return self._to_record(model)

    async def get_active_by_token_hash(
        self,
        *,
        token_hash: str,
        now: datetime,
    ) -> SessionRecord | None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SessionModel)
                .where(SessionModel.token_hash == token_hash)
                .where(SessionModel.revoked_at.is_(None))
                .where(SessionModel.expires_at > now)
            )
            model = result.scalar_one_or_none()
        return self._to_record(model) if model else None

    async def revoke(self, *, session_id: str, revoked_at: datetime) -> None:
        async with AsyncSessionLocal() as session:
            model = await session.get(SessionModel, session_id)
            if model is not None:
                model.revoked_at = revoked_at
                await session.commit()

    @staticmethod
    def _to_record(model: SessionModel) -> SessionRecord:
        return SessionRecord(
            id=model.id,
            user_id=model.user_id,
            token_hash=model.token_hash,
            csrf_token_hash=model.csrf_token_hash,
            expires_at=model.expires_at,
            revoked_at=model.revoked_at,
            created_at=model.created_at,
        )


class SqlAlchemyOwnershipRepository:
    async def claim(
        self,
        *,
        resource_type: str,
        resource_id: str,
        user_id: str,
    ) -> bool:
        async with AsyncSessionLocal() as session:
            existing_result = await session.execute(
                select(OwnedResourceModel)
                .where(OwnedResourceModel.resource_type == resource_type)
                .where(OwnedResourceModel.resource_id == resource_id)
            )
            existing = existing_result.scalar_one_or_none()
            if existing is not None:
                return existing.user_id == user_id
            session.add(
                OwnedResourceModel(
                    resource_type=resource_type,
                    resource_id=resource_id,
                    user_id=user_id,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                result = await session.execute(
                    select(OwnedResourceModel)
                    .where(OwnedResourceModel.resource_type == resource_type)
                    .where(OwnedResourceModel.resource_id == resource_id)
                )
                existing = result.scalar_one_or_none()
                return existing is not None and existing.user_id == user_id
        return True

    async def owner_of(
        self,
        *,
        resource_type: str,
        resource_id: str,
    ) -> str | None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(OwnedResourceModel.user_id)
                .where(OwnedResourceModel.resource_type == resource_type)
                .where(OwnedResourceModel.resource_id == resource_id)
            )
            return result.scalar_one_or_none()

    async def list_owned_ids(
        self,
        *,
        resource_type: str,
        user_id: str,
    ) -> set[str]:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(OwnedResourceModel.resource_id)
                .where(OwnedResourceModel.resource_type == resource_type)
                .where(OwnedResourceModel.user_id == user_id)
            )
            return set(result.scalars().all())

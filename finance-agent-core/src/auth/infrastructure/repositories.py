from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from src.auth.application.errors import RegistrationConflictError
from src.auth.domain.entities import (
    MembershipRecord,
    MembershipRole,
    MembershipStatus,
    OrganizationMembership,
    OrganizationRecord,
    RegistrationRecord,
    SessionRecord,
    UserRecord,
)
from src.auth.infrastructure.models import (
    MembershipModel,
    OrganizationModel,
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

    async def create_with_default_organization(
        self,
        *,
        email: str,
        password_hash: str,
        display_name: str,
        display_name_normalized: str,
    ) -> RegistrationRecord:
        user_model = UserModel(
            email=email,
            display_name=display_name,
            display_name_normalized=display_name_normalized,
            password_hash=password_hash,
        )
        organization_model = OrganizationModel(name="Personal organization")
        async with AsyncSessionLocal() as session:
            try:
                session.add_all([user_model, organization_model])
                await session.flush()
                membership_model = MembershipModel(
                    organization_id=organization_model.id,
                    user_id=user_model.id,
                    role=MembershipRole.OWNER.value,
                    status=MembershipStatus.ACTIVE.value,
                )
                session.add(membership_model)
                await session.commit()
                await session.refresh(user_model)
                await session.refresh(organization_model)
                await session.refresh(membership_model)
            except IntegrityError as exc:
                await session.rollback()
                raise RegistrationConflictError("email is already registered") from exc
        return RegistrationRecord(
            user=self._to_record(user_model),
            organization=self._to_organization_record(organization_model),
            membership=self._to_membership_record(membership_model),
        )

    @staticmethod
    def _to_record(model: UserModel) -> UserRecord:
        return UserRecord(
            id=model.id,
            email=model.email,
            password_hash=model.password_hash,
            created_at=model.created_at,
            display_name=model.display_name,
        )

    @staticmethod
    def _to_organization_record(model: OrganizationModel) -> OrganizationRecord:
        return OrganizationRecord(
            id=model.id,
            name=model.name,
            created_at=model.created_at,
        )

    @staticmethod
    def _to_membership_record(model: MembershipModel) -> MembershipRecord:
        return MembershipRecord(
            id=model.id,
            organization_id=model.organization_id,
            user_id=model.user_id,
            role=MembershipRole(model.role),
            status=MembershipStatus(model.status),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class SqlAlchemyOrganizationRepository:
    async def get_default_for_user(self, user_id: str) -> OrganizationMembership | None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(OrganizationModel, MembershipModel)
                .join(
                    MembershipModel,
                    MembershipModel.organization_id == OrganizationModel.id,
                )
                .where(MembershipModel.user_id == user_id)
                .where(MembershipModel.status == MembershipStatus.ACTIVE.value)
                .order_by(MembershipModel.created_at, MembershipModel.id)
                .limit(1)
            )
            row = result.first()
        return self._to_context(row) if row else None

    async def get_membership(
        self, *, user_id: str, organization_id: str
    ) -> OrganizationMembership | None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(OrganizationModel, MembershipModel)
                .join(
                    MembershipModel,
                    MembershipModel.organization_id == OrganizationModel.id,
                )
                .where(MembershipModel.user_id == user_id)
                .where(MembershipModel.organization_id == organization_id)
            )
            row = result.first()
        return self._to_context(row) if row else None

    @staticmethod
    def _to_context(
        row: tuple[OrganizationModel, MembershipModel],
    ) -> OrganizationMembership:
        organization, membership = row
        return OrganizationMembership(
            organization=SqlAlchemyUserRepository._to_organization_record(organization),
            membership=SqlAlchemyUserRepository._to_membership_record(membership),
        )


class SqlAlchemySessionRepository:
    async def create(
        self,
        *,
        user_id: str,
        active_organization_id: str,
        token_hash: str,
        csrf_token_hash: str,
        expires_at: datetime,
    ) -> SessionRecord:
        model = SessionModel(
            user_id=user_id,
            active_organization_id=active_organization_id,
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

    async def set_active_organization(
        self, *, session_id: str, organization_id: str, now: datetime
    ) -> bool:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                update(SessionModel)
                .where(SessionModel.id == session_id)
                .where(SessionModel.revoked_at.is_(None))
                .where(SessionModel.expires_at > now)
                .values(active_organization_id=organization_id)
            )
            await session.commit()
        return result.rowcount == 1

    @staticmethod
    def _to_record(model: SessionModel) -> SessionRecord:
        return SessionRecord(
            id=model.id,
            user_id=model.user_id,
            active_organization_id=model.active_organization_id,
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

    async def release(self, *, resource_type: str, resource_id: str) -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(OwnedResourceModel)
                .where(OwnedResourceModel.resource_type == resource_type)
                .where(OwnedResourceModel.resource_id == resource_id)
            )
            await session.commit()

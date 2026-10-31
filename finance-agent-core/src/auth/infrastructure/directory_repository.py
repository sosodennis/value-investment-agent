from __future__ import annotations

from sqlalchemy import and_, exists, or_, select

from src.auth.domain.entities import DirectoryPage, DirectoryUser, MembershipStatus
from src.auth.infrastructure.models import MembershipModel, UserModel
from src.infrastructure.database import AsyncSessionLocal


class SqlAlchemyDirectoryRepository:
    async def search_users(
        self,
        *,
        organization_id: str,
        query: str,
        limit: int,
        cursor: tuple[str, str] | None,
        include_external: bool,
    ) -> DirectoryPage:
        current_membership = exists(
            select(MembershipModel.id).where(
                and_(
                    MembershipModel.organization_id == organization_id,
                    MembershipModel.user_id == UserModel.id,
                    MembershipModel.status.in_(
                        (MembershipStatus.ACTIVE.value, MembershipStatus.PENDING.value)
                    ),
                )
            )
        )
        current_active_membership = exists(
            select(MembershipModel.id).where(
                and_(
                    MembershipModel.organization_id == organization_id,
                    MembershipModel.user_id == UserModel.id,
                    MembershipModel.status == MembershipStatus.ACTIVE.value,
                )
            )
        )
        statement = select(
            UserModel.id, UserModel.display_name, UserModel.display_name_normalized
        ).where(UserModel.display_name_normalized.startswith(query, autoescape=True))
        statement = statement.where(
            ~current_membership if include_external else current_active_membership
        )
        if cursor is not None:
            cursor_name, cursor_user_id = cursor
            statement = statement.where(
                or_(
                    UserModel.display_name_normalized > cursor_name,
                    and_(
                        UserModel.display_name_normalized == cursor_name,
                        UserModel.id > cursor_user_id,
                    ),
                )
            )
        statement = statement.order_by(
            UserModel.display_name_normalized, UserModel.id
        ).limit(limit)

        async with AsyncSessionLocal() as session:
            rows = (await session.execute(statement)).all()
        return DirectoryPage(
            items=tuple(
                DirectoryUser(user_id=user_id, display_name=display_name)
                for user_id, display_name, _normalized_name in rows
            ),
            next_cursor=None,
        )

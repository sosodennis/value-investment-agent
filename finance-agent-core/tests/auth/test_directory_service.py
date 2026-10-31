from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from src.auth.application.directory_service import DirectoryService
from src.auth.domain.entities import (
    AuthenticatedContext,
    DirectoryPage,
    DirectoryUser,
    MembershipRecord,
    MembershipRole,
    MembershipStatus,
    SessionRecord,
    UserRecord,
)
from src.auth.domain.policies import AuthPolicyError


def _context() -> AuthenticatedContext:
    now = datetime(2026, 1, 1)
    user = UserRecord(
        id="actor",
        email="actor@example.test",
        password_hash="unused",
        created_at=now,
        display_name="Actor",
    )
    membership = MembershipRecord(
        id="membership",
        organization_id="organization-a",
        user_id=user.id,
        role=MembershipRole.MEMBER,
        status=MembershipStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    return AuthenticatedContext(
        user=user,
        membership=membership,
        session=SessionRecord(
            id="session",
            user_id=user.id,
            active_organization_id=membership.organization_id,
            token_hash="token",
            csrf_token_hash="csrf",
            expires_at=now + timedelta(hours=1),
            revoked_at=None,
            created_at=now,
        ),
    )


class MemoryDirectoryRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.users = tuple(
            DirectoryUser(user_id=f"user-{index}", display_name=f"Analyst {index}")
            for index in range(1, 5)
        )

    async def search_users(
        self,
        *,
        organization_id: str,
        query: str,
        limit: int,
        cursor: tuple[str, str] | None,
        include_external: bool,
    ) -> DirectoryPage:
        self.calls.append(
            {
                "organization_id": organization_id,
                "query": query,
                "limit": limit,
                "cursor": cursor,
                "include_external": include_external,
            }
        )
        start = 0
        if cursor is not None:
            start = next(
                index
                for index, item in enumerate(self.users)
                if (item.display_name.casefold(), item.user_id) > cursor
            )
        return DirectoryPage(items=self.users[start : start + limit], next_cursor=None)


@pytest.mark.asyncio
async def test_directory_search_normalizes_query_and_paginates_deterministically() -> (
    None
):
    repository = MemoryDirectoryRepository()
    service = DirectoryService(
        repository=repository, cursor_secret="test-directory-cursor-secret"
    )

    first = await service.search_users(
        context=_context(), query="  ANALYST  ", limit=2, cursor=None
    )
    second = await service.search_users(
        context=_context(), query="analyst", limit=2, cursor=first.next_cursor
    )

    assert [item.user_id for item in first.items] == ["user-1", "user-2"]
    assert [item.user_id for item in second.items] == ["user-3", "user-4"]
    assert repository.calls[0] == {
        "organization_id": "organization-a",
        "query": "analyst",
        "limit": 3,
        "cursor": None,
        "include_external": False,
    }
    assert repository.calls[1]["cursor"] == ("analyst 2", "user-2")
    assert repository.calls[1]["include_external"] is False
    assert second.next_cursor is None


@pytest.mark.asyncio
async def test_short_queries_return_empty_without_touching_directory_repository() -> (
    None
):
    repository = MemoryDirectoryRepository()
    service = DirectoryService(
        repository=repository, cursor_secret="test-directory-cursor-secret"
    )

    result = await service.search_users(
        context=_context(), query=" ", limit=50, cursor=None
    )

    assert result == DirectoryPage(items=(), next_cursor=None)
    assert repository.calls == []


@pytest.mark.asyncio
async def test_cursor_is_bound_to_the_query_and_page_size_is_bounded() -> None:
    repository = MemoryDirectoryRepository()
    service = DirectoryService(
        repository=repository, cursor_secret="test-directory-cursor-secret"
    )
    first = await service.search_users(
        context=_context(), query="analyst", limit=2, cursor=None
    )

    with pytest.raises(AuthPolicyError, match="invalid directory cursor"):
        await service.search_users(
            context=_context(), query="other", limit=2, cursor=first.next_cursor
        )
    with pytest.raises(AuthPolicyError, match="page size"):
        await service.search_users(
            context=_context(), query="analyst", limit=51, cursor=None
        )

    tampered_cursor = first.next_cursor[:-1] + (
        "A" if first.next_cursor[-1] != "A" else "B"
    )
    with pytest.raises(AuthPolicyError, match="invalid directory cursor"):
        await service.search_users(
            context=_context(), query="analyst", limit=2, cursor=tampered_cursor
        )


@pytest.mark.asyncio
async def test_owner_and_admin_search_can_include_external_candidates() -> None:
    repository = MemoryDirectoryRepository()
    service = DirectoryService(
        repository=repository, cursor_secret="test-directory-cursor-secret"
    )
    context = _context()
    context = replace(
        context,
        membership=replace(context.membership, role=MembershipRole.OWNER),
    )

    await service.search_users(context=context, query="analyst", limit=2, cursor=None)

    assert repository.calls[-1]["include_external"] is True

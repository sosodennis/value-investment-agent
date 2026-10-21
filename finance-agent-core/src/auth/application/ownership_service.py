from __future__ import annotations

from src.auth.application.ports import OwnershipRepository


class OwnershipService:
    def __init__(self, repository: OwnershipRepository) -> None:
        self._repository = repository

    async def claim(
        self,
        *,
        user_id: str,
        resource_type: str,
        resource_id: str,
    ) -> bool:
        return await self._repository.claim(
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=user_id,
        )

    async def owns(
        self,
        *,
        user_id: str,
        resource_type: str,
        resource_id: str,
    ) -> bool:
        owner_id = await self._repository.owner_of(
            resource_type=resource_type,
            resource_id=resource_id,
        )
        return owner_id == user_id

    async def owned_ids(self, *, user_id: str, resource_type: str) -> set[str]:
        return await self._repository.list_owned_ids(
            resource_type=resource_type,
            user_id=user_id,
        )

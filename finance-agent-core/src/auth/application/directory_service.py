from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json

from src.auth.application.ports import DirectoryRepository
from src.auth.domain.entities import (
    AuthenticatedContext,
    DirectoryPage,
    MembershipRole,
)
from src.auth.domain.policies import AuthPolicyError, normalize_directory_query

MIN_DIRECTORY_QUERY_LENGTH = 2
MAX_DIRECTORY_PAGE_SIZE = 50


class DirectoryService:
    def __init__(self, *, repository: DirectoryRepository, cursor_secret: str) -> None:
        if not cursor_secret:
            raise ValueError("directory cursor secret is required")
        self._repository = repository
        self._cursor_secret = cursor_secret.encode("utf-8")

    async def search_users(
        self,
        *,
        context: AuthenticatedContext,
        query: str,
        limit: int,
        cursor: str | None,
    ) -> DirectoryPage:
        if not 1 <= limit <= MAX_DIRECTORY_PAGE_SIZE:
            raise AuthPolicyError("directory page size is invalid")
        normalized_query = normalize_directory_query(query)
        if len(normalized_query) < MIN_DIRECTORY_QUERY_LENGTH:
            return DirectoryPage(items=(), next_cursor=None)
        include_external = context.membership.role in {
            MembershipRole.OWNER,
            MembershipRole.ADMIN,
        }
        decoded_cursor = self._decode_cursor(
            cursor,
            normalized_query,
            organization_id=context.membership.organization_id,
            include_external=include_external,
        )
        page = await self._repository.search_users(
            organization_id=context.membership.organization_id,
            query=normalized_query,
            limit=limit + 1,
            cursor=decoded_cursor,
            include_external=include_external,
        )
        if len(page.items) <= limit:
            return DirectoryPage(items=page.items, next_cursor=None)
        visible_items = page.items[:limit]
        last_item = visible_items[-1]
        return DirectoryPage(
            items=visible_items,
            next_cursor=self._encode_cursor(
                query=normalized_query,
                organization_id=context.membership.organization_id,
                include_external=include_external,
                display_name=last_item.display_name,
                user_id=last_item.user_id,
            ),
        )

    def _encode_cursor(
        self,
        *,
        query: str,
        organization_id: str,
        include_external: bool,
        display_name: str,
        user_id: str,
    ) -> str:
        payload = json.dumps(
            {
                "q": query,
                "o": organization_id,
                "x": include_external,
                "n": display_name.casefold(),
                "u": user_id,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        encoded_payload = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
        signature = hmac.new(
            self._cursor_secret, encoded_payload.encode("ascii"), hashlib.sha256
        ).digest()
        encoded_signature = (
            base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
        )
        return f"{encoded_payload}.{encoded_signature}"

    def _decode_cursor(
        self,
        cursor: str | None,
        query: str,
        *,
        organization_id: str,
        include_external: bool,
    ) -> tuple[str, str] | None:
        if cursor is None:
            return None
        try:
            encoded_payload, encoded_signature = cursor.split(".", maxsplit=1)
            expected_signature = hmac.new(
                self._cursor_secret,
                encoded_payload.encode("ascii"),
                hashlib.sha256,
            ).digest()
            supplied_signature = base64.urlsafe_b64decode(
                f"{encoded_signature}{'=' * (-len(encoded_signature) % 4)}"
            )
            if not hmac.compare_digest(expected_signature, supplied_signature):
                raise ValueError
            padding = "=" * (-len(encoded_payload) % 4)
            payload = json.loads(
                base64.urlsafe_b64decode(f"{encoded_payload}{padding}").decode("utf-8")
            )
            if (
                not isinstance(payload, dict)
                or payload.get("q") != query
                or payload.get("o") != organization_id
                or payload.get("x") is not include_external
                or not isinstance(payload.get("n"), str)
                or not isinstance(payload.get("u"), str)
                or not payload["n"]
                or not payload["u"]
            ):
                raise ValueError
            return payload["n"], payload["u"]
        except (
            ValueError,
            TypeError,
            UnicodeError,
            binascii.Error,
            json.JSONDecodeError,
        ) as exc:
            raise AuthPolicyError("invalid directory cursor") from exc

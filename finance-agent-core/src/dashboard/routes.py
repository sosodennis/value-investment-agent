from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.analysis_runtime.domain.errors import InvalidCursorError
from src.auth.entrypoint import Principal, require_current_user
from src.dashboard.contracts import (
    DashboardCapabilities,
    MarketMoversResponse,
    RecentAnalysesResponse,
    RecentAnalysisItem,
)

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])


def _decode_cursor(
    token: str | None,
) -> tuple[datetime | None, str | None, str | None]:
    if token is None:
        return None, None, None
    try:
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
        if (
            not isinstance(payload, dict)
            or set(payload) != {"started_at", "thread_id", "run_id"}
            or not isinstance(payload["thread_id"], str)
            or not payload["thread_id"].strip()
            or not isinstance(payload["run_id"], str)
            or not payload["run_id"].strip()
        ):
            raise ValueError("invalid cursor fields")
        started_at_value = payload["started_at"]
        if started_at_value is None:
            started_at = None
        elif isinstance(started_at_value, str):
            started_at = datetime.fromisoformat(started_at_value.replace("Z", "+00:00"))
            if started_at.tzinfo is None:
                raise ValueError("cursor timestamp must include a timezone")
            started_at = started_at.astimezone(timezone.utc)
        else:
            raise ValueError("invalid cursor timestamp")
        return started_at, payload["thread_id"], payload["run_id"]
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="invalid_cursor") from exc


def _encode_cursor(started_at: datetime | None, thread_id: str, run_id: str) -> str:
    payload = json.dumps(
        {
            "started_at": started_at.isoformat() if started_at else None,
            "thread_id": thread_id,
            "run_id": run_id,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _explicit_text_field(value: object, key: str) -> str | None:
    if not isinstance(value, dict):
        return None
    field_value = value.get(key)
    return (
        field_value.strip()
        if isinstance(field_value, str) and field_value.strip()
        else None
    )


@router.get("/recent-analyses", response_model=RecentAnalysesResponse)
async def recent_analyses(
    request: Request,
    limit: int = Query(default=10, ge=1, le=50),
    next_cursor: str | None = Query(default=None, min_length=1, max_length=512),
    principal: Principal = Depends(require_current_user),
) -> RecentAnalysesResponse:
    runtime = getattr(request.app.state, "analysis_runtime", None)
    if runtime is None:
        raise HTTPException(status_code=503, detail="analysis runtime is unavailable")
    before_started_at, before_thread_id, before_run_id = _decode_cursor(next_cursor)
    try:
        page = await runtime.list_run_history(
            principal_id=principal.user_id,
            limit=limit,
            before_started_at=before_started_at,
            before_thread_id=before_thread_id,
            before_run_id=before_run_id,
        )
    except InvalidCursorError as exc:
        raise HTTPException(status_code=400, detail=exc.code) from exc

    items = [
        RecentAnalysisItem(
            thread_id=run.thread_id,
            run_id=run.run_id,
            status=run.status,
            started_at=run.started_at,
            updated_at=run.updated_at,
            ticker=_explicit_text_field(run.input_data, "ticker"),
            company_name=_explicit_text_field(run.input_data, "company_name"),
            summary=_explicit_text_field(run.input_data, "summary"),
        )
        for run in page.runs
    ]
    cursor = None
    if page.has_more:
        if page.next_thread_id is None or page.next_run_id is None:
            raise HTTPException(status_code=500, detail="invalid_history_page")
        cursor = _encode_cursor(
            page.next_started_at, page.next_thread_id, page.next_run_id
        )
    return RecentAnalysesResponse(
        fetched_at=datetime.now(timezone.utc), items=items, next_cursor=cursor
    )


@router.get("/market-movers", response_model=MarketMoversResponse)
async def market_movers(
    request: Request,
    limit: int = Query(default=3, ge=1, le=10),
    _principal: Principal = Depends(require_current_user),
) -> MarketMoversResponse:
    return await request.app.state.market_movers_service.get(limit=limit)


@router.get("/capabilities", response_model=DashboardCapabilities)
async def capabilities(
    request: Request,
    principal: Principal = Depends(require_current_user),
) -> DashboardCapabilities:
    del principal
    return await request.app.state.readiness_provider.check(
        runtime_available=getattr(request.app.state, "analysis_runtime", None)
        is not None
    )

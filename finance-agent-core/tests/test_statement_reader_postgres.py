from __future__ import annotations

import gzip
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.agents.fundamental.application.statement_reader import (
    FiscalArtifactCurrentReader,
    StatementReaderService,
)
from src.agents.fundamental.composition.statement_routes import build_statement_router
from src.agents.fundamental.infrastructure.fundamental_service_client import (
    FundamentalServiceClientSettings,
    HttpFundamentalServiceClient,
)
from src.artifacts.application.service import ArtifactService
from src.artifacts.infrastructure.sqlalchemy_repository import (
    SqlAlchemyArtifactRepository,
)
from src.artifacts.interface.routes import (
    build_default_artifact_service,
)
from src.artifacts.interface.routes import (
    router as artifact_router,
)
from src.auth.application.ownership_service import OwnershipService
from src.auth.application.wiring import get_auth_service
from src.auth.infrastructure.repositories import SqlAlchemyOwnershipRepository
from src.infrastructure.database import Base
from src.infrastructure.models import (
    Artifact,
    WorkflowActivityEvent,
    WorkflowRun,
    WorkflowRunHistory,
)
from src.shared.artifacts.fiscal_statement_contracts import FiscalReadResultV2
from src.shared.artifacts.statement_read_artifact import (
    StatementEditionV2,
    StatementReadArtifactV3,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.getenv("CORE_STATEMENT_TEST_DATABASE_URL"),
        reason="requires disposable Core PostgreSQL database",
    ),
]


@pytest.fixture
async def core_database(monkeypatch):
    url = make_url(os.environ["CORE_STATEMENT_TEST_DATABASE_URL"])
    admin_url = url.set(drivername="postgresql").render_as_string(hide_password=False)
    database_name = "issue495_core_" + uuid4().hex
    admin = await asyncpg.connect(admin_url)
    try:
        await admin.execute(f'CREATE DATABASE "{database_name}"')
    finally:
        await admin.close()
    engine = create_async_engine(
        url.set(drivername="postgresql+asyncpg", database=database_name)
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(
            "src.artifacts.infrastructure.sqlalchemy_repository.AsyncSessionLocal",
            sessions,
        )
        monkeypatch.setattr(
            "src.auth.infrastructure.repositories.AsyncSessionLocal", sessions
        )
        yield sessions
    finally:
        await engine.dispose()
        admin = await asyncpg.connect(admin_url)
        try:
            await admin.execute(f'DROP DATABASE "{database_name}" WITH (FORCE)')
        finally:
            await admin.close()


async def test_real_cookie_csrf_new_existing_thread_persistence_current_refusal_and_zero_workflow(
    core_database, monkeypatch
):
    auth = get_auth_service()
    registered = await auth.register(
        email=f"{uuid4().hex}@example.test",
        display_name="Fiscal reader",
        password="test-boundary-password",
        now=datetime.utcnow(),
    )
    value = FiscalReadResultV2.model_validate_json(
        gzip.decompress(
            (
                Path(__file__).resolve().parents[2]
                / "contracts/fixtures/fiscal-statements-quarter.v2.json.gz"
            ).read_bytes()
        )
    )
    edition = StatementEditionV2(
        edition_id="aapl-historical",
        label="Historical Apple",
        ticker="AAPL",
        company_name="Apple Inc.",
        scope=value.binding.scope,
        cutoff_at=value.binding.cutoff_at,
        annual_manifest_digest="a" * 64,
        fiscal_manifest_digest=value.binding.manifest_digest,
    )
    state = {"revoked": False}
    upstream = []

    async def respond(request):
        body = json.loads(request.content)
        upstream.append(body)
        assert request.method == "GET"
        assert request.url.path == "/v1/data/fiscal-statements"
        assert body["context"]["principal"]["subject_id"] == registered.user.id
        assert (
            body["context"]["principal"]["organization_id"]
            == registered.active_organization_id
        )
        assert body["context"]["signature"]
        base = {
            "contract_version": "internal.v1",
            "correlation_id": body["context"]["correlation_id"],
        }
        if state["revoked"]:
            return httpx.Response(
                409,
                json={
                    **base,
                    "error": {
                        "code": "FISCAL_AUTHORITY_REVOKED",
                        "message": "retained boundary refusal",
                        "retryable": False,
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                **base,
                "schema_version": "fundamental.v1",
                "result": value.model_dump(mode="json"),
            },
        )

    ownership = OwnershipService(SqlAlchemyOwnershipRepository())
    artifacts = ArtifactService(SqlAlchemyArtifactRepository())

    async def owns(user, thread, org):
        return await ownership.owns(
            user_id=user,
            resource_type="thread",
            resource_id=thread,
            organization_id=org,
        )

    async def claim(user, thread, org):
        return await ownership.claim(
            user_id=user,
            resource_type="thread",
            resource_id=thread,
            organization_id=org,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
        client = HttpFundamentalServiceClient(
            FundamentalServiceClientSettings(
                base_url="https://fundamental.test",
                service_token="ephemeral-core-boundary-key",
                max_attempts=1,
            ),
            client=transport,
        )
        reader = StatementReaderService(
            client=client,
            artifacts=artifacts,
            editions=(edition,),
            owns_thread=owns,
            claim_thread=claim,
        )

        @asynccontextmanager
        async def reader_factory():
            yield reader

        @asynccontextmanager
        async def current_factory():
            yield FiscalArtifactCurrentReader(client)

        monkeypatch.setattr(
            "src.artifacts.interface.routes.get_ownership_service", lambda: ownership
        )
        monkeypatch.setattr(
            "src.artifacts.interface.routes.build_default_fiscal_artifact_current_reader",
            current_factory,
        )
        app = FastAPI()
        app.include_router(build_statement_router(reader_factory))
        app.include_router(artifact_router)
        app.dependency_overrides[build_default_artifact_service] = lambda: artifacts
        body = {
            "contract_version": "workspace.statement-reader.v2",
            "kind": "new_thread",
            "creation_id": str(uuid4()),
            "edition_id": edition.edition_id,
            "frequency": "quarter",
        }
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://core.test"
        ) as browser:
            unauth = await browser.post(
                "/api/v1/fundamental/statements/read", json=body
            )
            assert unauth.status_code == 401
            browser.cookies.set("app_session", registered.session_token)
            browser.cookies.set("app_csrf", registered.csrf_token)
            no_csrf = await browser.post(
                "/api/v1/fundamental/statements/read", json=body
            )
            assert no_csrf.status_code == 403
            browser.headers["X-CSRF-Token"] = registered.csrf_token
            created = await browser.post(
                "/api/v1/fundamental/statements/read", json=body
            )
            assert created.status_code == 200, created.text
            identity = created.json()
            retried = await browser.post(
                "/api/v1/fundamental/statements/read", json=body
            )
            assert retried.json() == identity
            existing = {
                key: item for key, item in body.items() if key != "creation_id"
            } | {"kind": "existing_thread", "thread_id": identity["thread_id"]}
            repeated = await browser.post(
                "/api/v1/fundamental/statements/read", json=existing
            )
            assert repeated.json() == identity
            saved = await browser.get(identity["reference"]["download_url"])
            assert saved.status_code == 200, saved.text
            stored = await artifacts.get_artifact_envelope(
                identity["reference"]["artifact_id"]
            )
            assert saved.json() == stored.model_dump(mode="json")
            saved_selection = StatementReadArtifactV3.model_validate(
                saved.json()["data"]["statement_read"]
            )
            assert saved_selection.edition == edition
            assert saved_selection.frequency == "quarter"
            switched = await browser.post(
                "/api/v1/fundamental/statements/read",
                json={
                    "contract_version": "workspace.statement-reader.v2",
                    "kind": "saved_artifact",
                    "thread_id": identity["thread_id"],
                    "artifact_id": identity["reference"]["artifact_id"],
                    "frequency": "quarter",
                },
            )
            assert switched.status_code == 200, switched.text
            assert switched.json() == identity
            assert saved.headers["cache-control"] == "private, no-store"
            conditional = await browser.get(
                identity["reference"]["download_url"], headers={"If-None-Match": "*"}
            )
            assert (
                conditional.status_code == 200 and conditional.content == saved.content
            )
            state["revoked"] = True
            refused = await browser.get(
                identity["reference"]["download_url"], headers={"If-None-Match": "*"}
            )
            assert refused.status_code == 502
            assert refused.json()["detail"]["code"] == "FISCAL_AUTHORITY_REVOKED"
            assert "statement_read" not in refused.text
            assert "rows" not in refused.text
            before = len(upstream)
            wrong = await browser.post(
                "/api/v1/fundamental/statements/read",
                json=existing | {"thread_id": "another-thread"},
            )
            assert wrong.status_code == 404
            assert len(upstream) == before
        outsider = await auth.register(
            email=f"{uuid4().hex}@example.test",
            display_name="Other organization",
            password="test-boundary-password",
            now=datetime.utcnow(),
        )
        before = len(upstream)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://core.test"
        ) as browser:
            browser.cookies.set("app_session", outsider.session_token)
            denied = await browser.get(identity["reference"]["download_url"])
            assert denied.status_code == 404
            assert len(upstream) == before
        async with core_database() as session:
            assert (
                await session.scalar(select(func.count()).select_from(WorkflowRun)) == 0
            )
            assert (
                await session.scalar(
                    select(func.count()).select_from(WorkflowActivityEvent)
                )
                == 0
            )
            assert await session.scalar(select(func.count()).select_from(Artifact)) == 1
            assert (
                await session.scalar(
                    select(func.count()).select_from(WorkflowRunHistory)
                )
                == 0
            )

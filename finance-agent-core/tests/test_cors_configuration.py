from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from api.server import _cors_origins
from src.interface.auth.local_admin import settings as local_admin_settings


def test_frontend_origins_are_shared_by_cors_and_local_admin(monkeypatch):
    origins = "http://localhost:33178,http://127.0.0.1:33178/"
    monkeypatch.setenv("FRONTEND_ALLOWED_ORIGINS", origins)
    monkeypatch.delenv("LOCAL_ADMIN_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://legacy.example")

    assert _cors_origins() == ["http://localhost:33178", "http://127.0.0.1:33178"]
    assert local_admin_settings().allowed_origins == frozenset(
        {"http://localhost:33178", "http://127.0.0.1:33178"}
    )


def test_legacy_allowlists_resolve_to_one_shared_origin_list(monkeypatch):
    monkeypatch.delenv("FRONTEND_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:33001/")
    monkeypatch.setenv("LOCAL_ADMIN_ALLOWED_ORIGINS", "http://localhost:33178")

    assert _cors_origins() == ["http://localhost:33001"]
    assert local_admin_settings().allowed_origins == frozenset(
        {"http://localhost:33001"}
    )


def test_cors_preflight_allows_credentials_only_for_configured_origin(monkeypatch):
    monkeypatch.delenv("FRONTEND_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("LOCAL_ADMIN_ALLOWED_ORIGINS", raising=False)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:33178")
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    app.add_route("/correlation", lambda _request: JSONResponse({"status": "ok"}))
    client = TestClient(app)

    allowed = client.options(
        "/api/v1/auth/me",
        headers={
            "Origin": "http://localhost:33178",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-csrf-token",
        },
    )
    rejected = client.options(
        "/api/v1/auth/me",
        headers={
            "Origin": "http://untrusted.example",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:33178"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    response = client.get(
        "/correlation",
        headers={"Origin": "http://localhost:33178", "X-Request-ID": "trace-cors"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-expose-headers"] == "X-Request-ID"
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers

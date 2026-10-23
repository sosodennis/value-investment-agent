from __future__ import annotations

import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "search-service" / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT / "finance-agent-core"))

from pydantic import BaseModel  # noqa: E402
from src.shared.internal_services import (  # noqa: E402
    InternalErrorResponse,
    InternalReadiness,
)

from search_service.contracts import (  # noqa: E402
    SEARCH_ERROR_STATUSES,
    EmptyEnvelope,
    NewsSearchEnvelope,
    ProviderCatalog,
    ProviderCatalogResult,
    ProviderCatalogSuccess,
    ProviderKeyAddEnvelope,
    ProviderKeyAddInput,
    ProviderKeyDeleteEnvelope,
    ProviderKeyDeleteResult,
    ProviderKeyDeleteSuccess,
    ProviderKeyList,
    ProviderKeyListSuccess,
    ProviderKeyReplaceEnvelope,
    ProviderKeyReplaceInput,
    ProviderKeyResult,
    ProviderKeySuccess,
    ProviderKeyTestEnvelope,
    ProviderKeyTestResult,
    ProviderKeyTestSuccess,
    SearchOperationResult,
    SearchSuccess,
    SettingsEnvelope,
    SettingsReadResult,
    SettingsSuccess,
    WebSearchEnvelope,
)

_SCHEMA_MODELS: tuple[type[BaseModel], ...] = (
    EmptyEnvelope,
    NewsSearchEnvelope,
    ProviderCatalog,
    ProviderCatalogResult,
    ProviderCatalogSuccess,
    ProviderKeyAddInput,
    ProviderKeyAddEnvelope,
    ProviderKeyDeleteEnvelope,
    ProviderKeyDeleteResult,
    ProviderKeyDeleteSuccess,
    ProviderKeyList,
    ProviderKeyListSuccess,
    ProviderKeyReplaceInput,
    ProviderKeyReplaceEnvelope,
    ProviderKeyResult,
    ProviderKeySuccess,
    ProviderKeyTestEnvelope,
    ProviderKeyTestResult,
    ProviderKeyTestSuccess,
    SearchOperationResult,
    SearchSuccess,
    SettingsEnvelope,
    SettingsReadResult,
    SettingsSuccess,
    WebSearchEnvelope,
    InternalErrorResponse,
    InternalReadiness,
)


def _models() -> dict[str, object]:
    schemas: dict[str, object] = {}
    for model in _SCHEMA_MODELS:
        schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
        definitions = schema.pop("$defs", {})
        for name, definition in definitions.items():
            schemas[name] = definition
        schemas[model.__name__] = schema
    return schemas


def _ref(name: str) -> dict[str, object]:
    return {"$ref": f"#/components/schemas/{name}"}


def _body(name: str) -> dict[str, object]:
    return {
        "required": True,
        "content": {"application/json": {"schema": _ref(name)}},
    }


def _response(name: str, description: str) -> dict[str, object]:
    return {
        "description": description,
        "content": {"application/json": {"schema": _ref(name)}},
    }


def _operation(
    operation_id: str,
    request_model: str,
    success_model: str,
    *,
    success_status: str = "200",
    errors: tuple[str, ...] = ("400", "401", "422", "429", "502", "503", "504"),
    description: str,
) -> dict[str, object]:
    responses: dict[str, object] = {
        success_status: _response(success_model, "Successful operation")
    }
    for status in sorted(
        set(errors) | {str(status) for status in SEARCH_ERROR_STATUSES.values()}
    ):
        responses[status] = _response("InternalErrorResponse", "Stable internal error")
    return {
        "operationId": operation_id,
        "description": description,
        "security": [{"ServiceToken": []}],
        "requestBody": _body(request_model),
        "responses": responses,
    }


def document() -> dict[str, object]:
    empty = "EmptyEnvelope"
    paths: dict[str, object] = {
        "/contract": {
            "get": {
                "operationId": "contract",
                "responses": {
                    "200": {
                        "description": "Search contract version and operations",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": [
                                        "contract_version",
                                        "schema_version",
                                        "operations",
                                    ],
                                    "properties": {
                                        "contract_version": {"const": "internal.v1"},
                                        "schema_version": {"const": "search.v1"},
                                        "operations": {
                                            "type": "array",
                                            "items": {"enum": ["web", "news"]},
                                        },
                                    },
                                }
                            }
                        },
                    }
                },
            }
        },
        "/livez": {
            "get": {
                "operationId": "livez",
                "responses": {"200": {"description": "Process is alive"}},
            }
        },
        "/readyz": {
            "get": {
                "operationId": "readyz",
                "responses": {
                    "200": _response("InternalReadiness", "Service is ready"),
                    "503": _response("InternalReadiness", "Service is not ready"),
                },
            }
        },
        "/v1/search/web": {
            "post": _operation(
                "webSearch",
                "WebSearchEnvelope",
                "SearchSuccess",
                errors=("400", "401", "422", "429", "502", "503", "504"),
                description="Run provider-neutral web search.",
            )
        },
        "/v1/search/news": {
            "post": _operation(
                "newsSearch",
                "NewsSearchEnvelope",
                "SearchSuccess",
                errors=("400", "401", "422", "429", "502", "503", "504"),
                description="Run provider-neutral news search.",
            )
        },
        "/v1/providers/catalog": {
            "post": _operation(
                "providerCatalog",
                empty,
                "ProviderCatalogSuccess",
                errors=("400", "401", "503"),
                description="Read the supported provider operations and options.",
            )
        },
        "/v1/settings/read": {
            "post": _operation(
                "settingsRead",
                empty,
                "SettingsSuccess",
                errors=("400", "401", "503", "504"),
                description="Read settings for the authenticated user.",
            )
        },
        "/v1/settings/update": {
            "post": _operation(
                "settingsUpdate",
                "SettingsEnvelope",
                "SettingsSuccess",
                errors=("400", "401", "404", "503", "504"),
                description="Atomically replace the authenticated user's provider order and enablement.",
            )
        },
        "/v1/provider-keys/test": {
            "post": _operation(
                "providerKeyTest",
                "ProviderKeyTestEnvelope",
                "ProviderKeyTestSuccess",
                errors=("400", "401", "422", "429", "503", "504"),
                description="Test a submitted key without persisting it.",
            )
        },
        "/v1/provider-keys/add": {
            "post": _operation(
                "providerKeyAddTestActivate",
                "ProviderKeyAddEnvelope",
                "ProviderKeySuccess",
                errors=("400", "401", "422", "429", "502", "503", "504"),
                description="Test a key before activating it for the authenticated user.",
            )
        },
        "/v1/provider-keys/replace": {
            "post": _operation(
                "providerKeyReplaceTestActivate",
                "ProviderKeyReplaceEnvelope",
                "ProviderKeySuccess",
                errors=("400", "401", "404", "422", "429", "502", "503", "504"),
                description="Test a replacement before activation. Failed tests leave the current key unchanged.",
            )
        },
        "/v1/provider-keys/delete": {
            "post": _operation(
                "providerKeyDelete",
                "ProviderKeyDeleteEnvelope",
                "ProviderKeyDeleteSuccess",
                errors=("400", "401", "404", "503", "504"),
                description="Delete an owned key idempotently. This request contains no key material.",
            )
        },
        "/v1/provider-keys/list": {
            "post": _operation(
                "providerKeyList",
                empty,
                "ProviderKeyListSuccess",
                errors=("400", "401", "503", "504"),
                description="List masked key metadata for the authenticated user.",
            )
        },
    }
    return {
        "openapi": "3.1.0",
        "x-search-error-status-mappings": SEARCH_ERROR_STATUSES,
        "info": {
            "title": "Search Service",
            "version": "search.v1",
            "description": "Provider-neutral web and news search contract.",
        },
        "paths": paths,
        "components": {
            "schemas": _models(),
            "securitySchemes": {
                "ServiceToken": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Internal caller credential. The JSON context carries the authenticated principal.",
                }
            },
        },
    }


if __name__ == "__main__":
    target = REPOSITORY_ROOT / "contracts" / "search-service-openapi.json"
    target.write_text(json.dumps(document(), indent=2, sort_keys=True) + "\n")

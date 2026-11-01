import json
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
LOCAL_PROVIDER_TOKEN = "local-development-only-token"
TEST_PROVIDER_TOKEN = "compose-test-provider-token"
TEST_ENCRYPTION_KEY = "compose-test-encryption-key"
TEST_SEARCH_SERVICE_TOKEN = "compose-test-search-service-token"
TEST_SEARCH_ENCRYPTION_KEY = "compose-test-search-encryption-key"
TEST_DIRECTORY_CURSOR_SECRET = "compose-test-directory-cursor-secret"
TEST_AUDIT_CURSOR_SECRET = "compose-test-audit-cursor-secret"


def _compose_config(
    *files: str,
    provider_token: str | None,
    audit_secret: str | None = TEST_AUDIT_CURSOR_SECRET,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("COMPOSE_FILE", None)
    env.pop("LLM_PROVIDER_SERVICE_TOKEN", None)
    env["LLM_PROVIDER_ENCRYPTION_KEY"] = TEST_ENCRYPTION_KEY
    env["SEARCH_SERVICE_TOKEN"] = TEST_SEARCH_SERVICE_TOKEN
    env["SEARCH_PROVIDER_ENCRYPTION_KEY"] = TEST_SEARCH_ENCRYPTION_KEY
    env["DIRECTORY_CURSOR_SECRET"] = TEST_DIRECTORY_CURSOR_SECRET
    if audit_secret is not None:
        env["AUDIT_CURSOR_SECRET"] = audit_secret
    else:
        env.pop("AUDIT_CURSOR_SECRET", None)
    if provider_token is not None:
        env["LLM_PROVIDER_SERVICE_TOKEN"] = provider_token
    return subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            "value-investment-agent-compose-auth-test",
            "--env-file",
            "/dev/null",
            *files,
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_compose_auth_dev_and_production_secret() -> None:
    local = _compose_config(provider_token=None)
    assert local.returncode == 0, local.stderr
    local_services = json.loads(local.stdout)["services"]
    assert local_services["backend"]["environment"]["LLM_PROVIDER_SERVICE_TOKEN"] == (
        LOCAL_PROVIDER_TOKEN
    )

    production_files = (
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.production.yml",
    )
    production_without_token = _compose_config(*production_files, provider_token=None)
    assert production_without_token.returncode != 0
    assert "LLM_PROVIDER_SERVICE_TOKEN" in production_without_token.stderr

    production_without_audit_secret = _compose_config(
        *production_files,
        provider_token=TEST_PROVIDER_TOKEN,
        audit_secret=None,
    )
    assert production_without_audit_secret.returncode != 0
    assert "AUDIT_CURSOR_SECRET" in production_without_audit_secret.stderr

    production = _compose_config(*production_files, provider_token=TEST_PROVIDER_TOKEN)
    assert production.returncode == 0, production.stderr
    services = json.loads(production.stdout)["services"]
    assert services["backend"]["environment"]["APP_ENV"] == "production"
    assert services["backend"]["environment"]["SEARCH_SERVICE_TOKEN"] == (
        TEST_SEARCH_SERVICE_TOKEN
    )
    assert services["search-service"]["environment"]["SEARCH_SERVICE_TOKEN"] == (
        TEST_SEARCH_SERVICE_TOKEN
    )
    assert (
        services["search-service"]["environment"]["SEARCH_PROVIDER_ENCRYPTION_KEY"]
        == TEST_SEARCH_ENCRYPTION_KEY
    )


def test_canonical_compose_has_one_llm_provider_service() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    services = compose["services"]
    assert "llm-provider-service" in services
    assert "llm-gateway" not in services
    assert "llm-gateway-db-init" not in services
    provider = services["llm-provider-service"]["environment"]
    assert provider["LLM_PROVIDER_ENCRYPTION_KEY"].startswith(
        "${LLM_PROVIDER_ENCRYPTION_KEY:?"
    )
    assert provider["LLM_PROVIDER_KEY_COOLDOWN_SECONDS"] == (
        "${LLM_PROVIDER_KEY_COOLDOWN_SECONDS:-30}"
    )


def test_backend_does_not_receive_provider_runtime_secrets() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    backend_environment = compose["services"]["backend"]["environment"]
    backend_variables = {
        entry.removeprefix("- ").split("=", maxsplit=1)[0]
        for entry in backend_environment
    }
    assert "LLM_PROVIDER_ENCRYPTION_KEY" not in backend_variables
    assert not any(name.startswith("LITELLM_") for name in backend_variables)
    assert not any(name.startswith("OPENROUTER_") for name in backend_variables)


def test_litellm_is_a_provider_service_dependency() -> None:
    pyproject = (ROOT / "llm-provider-service/pyproject.toml").read_text()
    assert '"litellm==1.106.6"' in pyproject
    assert '"cryptography>=50.0.0,<51.0.0"' in pyproject
    assert '"filelock==4.2.5"' in pyproject

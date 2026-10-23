import json
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
LOCAL_PROVIDER_TOKEN = "local-development-only-token"
TEST_MASTER_KEY = "compose-test-master-key"
TEST_PRODUCTION_PROVIDER_TOKEN = "compose-test-production-token"


def _compose_config(
    *files: str, provider_token: str | None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("COMPOSE_FILE", None)
    env.pop("LLM_PROVIDER_SERVICE_TOKEN", None)
    env["LITELLM_MASTER_KEY"] = TEST_MASTER_KEY
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
            "--profile",
            "llm-gateway",
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


def _assert_shared_provider_token(config_output: str, expected_token: str) -> None:
    services = json.loads(config_output)["services"]
    backend_environment = services["backend"]["environment"]
    provider_environment = services["llm-provider-service"]["environment"]

    assert backend_environment["LLM_PROVIDER_SERVICE_TOKEN"] == expected_token
    assert provider_environment["LLM_PROVIDER_SERVICE_TOKEN"] == expected_token
    assert expected_token.strip()
    assert "LITELLM_MASTER_KEY" not in backend_environment
    assert "LLM_GATEWAY_API_KEY" not in backend_environment
    assert not any(
        name.startswith(("LLM_GATEWAY_", "OPENROUTER_")) for name in backend_environment
    )


def test_compose_auth_dev_default_and_production_secret() -> None:
    local = _compose_config(provider_token=None)
    assert local.returncode == 0, "default local Compose config failed"
    _assert_shared_provider_token(local.stdout, LOCAL_PROVIDER_TOKEN)

    production_files = (
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.production.yml",
    )
    production_without_token = _compose_config(*production_files, provider_token=None)
    assert production_without_token.returncode != 0
    assert "LLM_PROVIDER_SERVICE_TOKEN" in production_without_token.stderr

    production = _compose_config(
        *production_files, provider_token=TEST_PRODUCTION_PROVIDER_TOKEN
    )
    assert production.returncode == 0, "production Compose config rejected a token"
    _assert_shared_provider_token(production.stdout, TEST_PRODUCTION_PROVIDER_TOKEN)
    production_services = json.loads(production.stdout)["services"]
    assert production_services["backend"]["environment"]["APP_ENV"] == "production"


def test_litellm_poc_uses_database_managed_openrouter_deployments() -> None:
    config = yaml.safe_load((ROOT / "infra/litellm/config.yaml").read_text())
    assert "model_list" not in config
    router_settings = config["router_settings"]
    assert router_settings["num_retries"] == 1
    assert router_settings["allowed_fails"] == 0
    assert (
        router_settings["cooldown_time"]
        == "os.environ/LLM_PROVIDER_KEY_COOLDOWN_SECONDS"
    )
    assert config["litellm_settings"]["callbacks"] == [
        "provider_key_telemetry.provider_key_telemetry"
    ]


def test_litellm_cooldown_state_uses_shared_redis_configuration() -> None:
    config = yaml.safe_load((ROOT / "infra/litellm/config.yaml").read_text())
    router_settings = config["router_settings"]
    coordination = config["general_settings"]["coordination_redis"]

    assert router_settings["redis_host"] == "os.environ/LITELLM_REDIS_HOST"
    assert router_settings["redis_port"] == "os.environ/LITELLM_REDIS_PORT"
    assert router_settings["redis_password"] == "os.environ/LITELLM_REDIS_PASSWORD"
    assert coordination == {
        "host": "os.environ/LITELLM_REDIS_HOST",
        "port": "os.environ/LITELLM_REDIS_PORT",
        "password": "os.environ/LITELLM_REDIS_PASSWORD",
    }


def test_poc_does_not_store_literal_provider_credentials() -> None:
    config_text = (ROOT / "infra/litellm/config.yaml").read_text()

    assert "sk-" not in config_text
    assert "OPENROUTER_API_KEY" not in config_text


def test_compose_poc_is_pinned_bounded_and_loopback_only() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    gateway = compose["services"]["llm-gateway"]

    assert gateway["image"].startswith("docker.litellm.ai/berriai/litellm@sha256:")
    assert gateway["ports"] == ["127.0.0.1:${LLM_GATEWAY_HOST_PORT:-4000}:4000"]
    assert gateway["mem_limit"] == "${LLM_GATEWAY_MEMORY_LIMIT:-1g}"
    assert gateway["cpus"] == "${LLM_GATEWAY_CPUS:-1.0}"
    assert gateway["restart"] == "unless-stopped"
    assert gateway["command"][-2:] == ["--num_workers", "${LLM_GATEWAY_WORKERS:-1}"]
    assert (
        gateway["environment"]["LITELLM_REDIS_HOST"] == "${LITELLM_REDIS_HOST:-redis}"
    )
    assert gateway["environment"]["LITELLM_REDIS_PORT"] == "${LITELLM_REDIS_PORT:-6379}"
    assert (
        gateway["environment"]["LITELLM_REDIS_PASSWORD"]
        == "${LITELLM_REDIS_PASSWORD:-}"
    )
    assert (
        gateway["environment"]["LLM_PROVIDER_KEY_COOLDOWN_SECONDS"]
        == "${LLM_PROVIDER_KEY_COOLDOWN_SECONDS:-30}"
    )
    assert (
        "./infra/litellm/provider_key_telemetry.py:/app/provider_key_telemetry.py:ro"
        in gateway["volumes"]
    )
    assert gateway["depends_on"]["redis"]["condition"] == "service_healthy"
    assert "healthcheck" in gateway

    contract_test = compose["services"]["llm-gateway-contract-test"]
    assert contract_test["image"] == gateway["image"]
    assert contract_test["profiles"] == ["llm-gateway-contract-test"]
    assert contract_test["entrypoint"] == [
        "python3",
        "/app/router_retry_contract.py",
    ]
    assert contract_test["environment"] == {
        "LITELLM_REDIS_HOST": "llm-gateway-contract-redis",
        "LITELLM_REDIS_PORT": 6379,
        "LLM_PROVIDER_KEY_COOLDOWN_SECONDS": 1,
    }
    assert (
        "./infra/litellm/provider_key_telemetry.py:/app/provider_key_telemetry.py:ro"
        in contract_test["volumes"]
    )
    assert contract_test["depends_on"]["llm-gateway-contract-redis"]["condition"] == (
        "service_healthy"
    )
    contract_redis = compose["services"]["llm-gateway-contract-redis"]
    assert contract_redis["profiles"] == ["llm-gateway-contract-test"]
    assert "volumes" not in contract_redis
    assert "ports" not in contract_redis
    assert "env_file" not in contract_test


def test_provider_service_owns_gateway_credentials_and_retry_policy() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    backend_environment = compose["services"]["backend"]["environment"]
    provider_environment = compose["services"]["llm-provider-service"]["environment"]

    backend_variables = {
        entry.removeprefix("- ").split("=", maxsplit=1)[0]
        for entry in backend_environment
    }
    assert not any("LITELLM_MASTER_KEY" in entry for entry in backend_environment)
    assert "LLM_GATEWAY_API_KEY" not in backend_variables
    assert not any(name.startswith("LLM_GATEWAY_") for name in backend_variables)
    assert not any(name.startswith("OPENROUTER_") for name in backend_variables)

    assert provider_environment["LLM_GATEWAY_API_KEY"] == "${LITELLM_MASTER_KEY:-}"
    assert provider_environment["LLM_GATEWAY_BASE_URL"] == (
        "${LLM_GATEWAY_BASE_URL:-http://llm-gateway:4000}"
    )
    assert provider_environment["LLM_GATEWAY_REQUIRE_PRINCIPAL"] == (
        "${LLM_GATEWAY_REQUIRE_PRINCIPAL:-true}"
    )
    assert provider_environment["LLM_GATEWAY_MAX_ATTEMPTS"] == (
        "${LLM_GATEWAY_MAX_ATTEMPTS:-3}"
    )
    assert provider_environment["LLM_GATEWAY_MAX_ATTEMPTS_INTERACTIVE"] == (
        "${LLM_GATEWAY_MAX_ATTEMPTS_INTERACTIVE:-2}"
    )
    assert provider_environment["LLM_GATEWAY_MAX_ATTEMPTS_BACKGROUND"] == (
        "${LLM_GATEWAY_MAX_ATTEMPTS_BACKGROUND:-3}"
    )
    assert provider_environment["LLM_GATEWAY_BACKOFF_SECONDS"] == (
        "${LLM_GATEWAY_BACKOFF_SECONDS:-0.25}"
    )
    assert provider_environment["LLM_GATEWAY_MAX_BACKOFF_SECONDS"] == (
        "${LLM_GATEWAY_MAX_BACKOFF_SECONDS:-8}"
    )
    assert provider_environment["LLM_GATEWAY_JITTER_SECONDS"] == (
        "${LLM_GATEWAY_JITTER_SECONDS:-0.25}"
    )
    assert provider_environment["OPENROUTER_HTTP_REFERER"] == (
        "${OPENROUTER_HTTP_REFERER:-}"
    )
    assert provider_environment["OPENROUTER_X_TITLE"] == (
        "${OPENROUTER_X_TITLE:-Value Investment Agent}"
    )


def test_smoke_script_checks_authenticated_management_surfaces() -> None:
    script = (ROOT / "scripts/litellm_poc_smoke.sh").read_text()

    assert "/health/liveliness" in script
    assert "/v1/models" in script
    assert "/model/info" in script
    assert "POC_MODEL_ALIAS" in script

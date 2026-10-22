from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]


def test_litellm_poc_uses_database_managed_openrouter_deployments() -> None:
    config = yaml.safe_load((ROOT / "infra/litellm/config.yaml").read_text())
    assert "model_list" not in config
    router_settings = config["router_settings"]
    assert router_settings["num_retries"] == 1
    assert router_settings["allowed_fails"] == 2
    assert router_settings["cooldown_time"] == 30


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
    assert gateway["depends_on"]["redis"]["condition"] == "service_healthy"
    assert "healthcheck" in gateway


def test_backend_requires_request_principal_for_gateway_data_plane() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    environment = compose["services"]["backend"]["environment"]

    assert (
        "LLM_GATEWAY_REQUIRE_PRINCIPAL=${LLM_GATEWAY_REQUIRE_PRINCIPAL:-true}"
        in environment
    )


def test_smoke_script_checks_authenticated_management_surfaces() -> None:
    script = (ROOT / "scripts/litellm_poc_smoke.sh").read_text()

    assert "/health/liveliness" in script
    assert "/v1/models" in script
    assert "/model/info" in script
    assert "POC_MODEL_ALIAS" in script

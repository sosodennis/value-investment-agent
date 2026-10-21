from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]


def test_litellm_poc_uses_database_managed_openrouter_deployments() -> None:
    config = yaml.safe_load((ROOT / "infra/litellm/config.yaml").read_text())
    assert "model_list" not in config
    assert config["router_settings"]["num_retries"] == 1


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

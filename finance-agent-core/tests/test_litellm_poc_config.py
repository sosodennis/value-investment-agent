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

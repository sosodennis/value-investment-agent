from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]


def test_litellm_poc_targets_openrouter_with_two_credential_slots() -> None:
    config = yaml.safe_load((ROOT / "infra/litellm/config.yaml").read_text())
    models = config["model_list"]

    assert len(models) == 2
    assert {item["model_name"] for item in models} == {"openrouter-default"}
    assert all(item["litellm_params"]["model"] == "openrouter/auto" for item in models)
    assert [item["litellm_params"]["api_key"] for item in models] == [
        "os.environ/OPENROUTER_API_KEY_1",
        "os.environ/OPENROUTER_API_KEY_2",
    ]
    assert config["router_settings"]["num_retries"] == 1


def test_poc_does_not_store_literal_provider_credentials() -> None:
    config_text = (ROOT / "infra/litellm/config.yaml").read_text()

    assert "sk-" not in config_text
    assert "OPENROUTER_API_KEY_1" in config_text
    assert "OPENROUTER_API_KEY_2" in config_text

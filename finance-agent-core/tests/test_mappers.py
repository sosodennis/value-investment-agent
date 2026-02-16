from src.interface.events.mappers import NodeOutputMapper


def _artifact(kind: str) -> dict[str, object]:
    return {
        "kind": kind,
        "version": "v1",
        "summary": "ok",
        "preview": {"ticker": "AAPL"},
        "reference": None,
    }


def test_transform_nested_artifact_payload() -> None:
    nested_output = {
        "fundamental_analysis": {"artifact": _artifact("fundamental_analysis.output")}
    }

    result = NodeOutputMapper.transform("fundamental_analysis", nested_output)

    assert result is not None
    assert result["kind"] == "fundamental_analysis.output"
    assert result["version"] == "v1"
    assert result["summary"] == "ok"


def test_transform_direct_artifact_payload() -> None:
    direct_output = {"artifact": _artifact("technical_analysis.output")}

    result = NodeOutputMapper.transform("technical_analysis", direct_output)

    assert result is not None
    assert result["kind"] == "technical_analysis.output"


def test_transform_rejects_invalid_output_contract() -> None:
    invalid_output = {
        "artifact": {
            "summary": "missing kind/version",
            "preview": {"ticker": "AAPL"},
            "reference": None,
        }
    }

    try:
        NodeOutputMapper.transform("fundamental_analysis", invalid_output)
        raise AssertionError(
            "Expected transform to fail on invalid artifact output contract"
        )
    except TypeError as exc:
        assert "validation failed" in str(exc)

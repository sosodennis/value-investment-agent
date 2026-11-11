import subprocess
from types import ModuleType, SimpleNamespace

import pytest

from fundamental_service import (
    history_mapping_proposals,
    history_market_evidence,
    history_policy_proposal,
    history_replay,
    history_replay_inputs,
)


@pytest.mark.parametrize(
    "module,args",
    (
        (history_replay_inputs, ["capture"]),
        (history_market_evidence, ["--source-manifest", "unused"]),
        (history_policy_proposal, ["--market-evidence", "unused"]),
        (history_mapping_proposals, ["--review-manifest", "unused"]),
    ),
)
def test_replay_command_rejects_dirty_source_before_any_input_or_network_io(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType, args: list[str]
) -> None:
    calls: list[str] = []

    def dirty(required_source: str) -> None:
        calls.append(required_source)
        raise history_replay.ReplayPreflightError("dirty source fixture")

    monkeypatch.setattr(module, "_ensure_tracked_tree_clean", dirty)
    assert module._main(args) == 2
    assert len(calls) == 1
    assert calls[0].endswith(module.__name__.rsplit(".", 1)[-1] + ".py")


def test_untracked_command_source_cannot_claim_a_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def run(args: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(args)
        return SimpleNamespace(returncode=1 if "ls-files" in args else 0)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(history_replay.ReplayPreflightError, match="must be clean"):
        history_replay._ensure_tracked_tree_clean("untracked-command.py")
    assert calls[-1][-1] == "untracked-command.py"

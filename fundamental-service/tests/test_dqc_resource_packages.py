import hashlib
from pathlib import Path
from zipfile import ZipFile

import pytest

import fundamental_service.dqc_resource_packages as resources


class Registry:
    def __init__(self, accepted: bool = True):
        self.path: Path | None = None
        self.accepted = accepted
        self.rebuilt = False

    def add(self, path: str) -> object | None:
        self.path = Path(path)
        assert self.path.is_file()
        return object() if self.accepted else None

    def rebuild(self) -> None:
        assert self.path is not None and self.path.is_file()
        self.rebuilt = True


def _ruleset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    payload = b"official resource package bytes"
    monkeypatch.setattr(
        resources, "V18_PACKAGE_SHA256", hashlib.sha256(payload).hexdigest()
    )
    path = tmp_path / "rules.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("packages/resources.zip", payload)
    return path


@pytest.mark.parametrize("failure", [None, RuntimeError, KeyboardInterrupt])
def test_package_survives_validation_and_is_released_on_success_error_or_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: type[BaseException] | None
):
    ruleset = _ruleset(tmp_path, monkeypatch)
    registry = Registry()
    try:
        with resources.activate_v18_package(registry, ruleset) as marker:
            assert registry.rebuilt
            assert registry.path is not None and registry.path.read_bytes()
            assert marker.endswith(resources.V18_PACKAGE_SHA256)
            if failure:
                raise failure()
    except BaseException as error:
        assert failure is not None and isinstance(error, failure)
    assert registry.path is not None
    assert not registry.path.parent.exists()


def test_failed_activation_releases_staged_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    ruleset = _ruleset(tmp_path, monkeypatch)
    registry = Registry(accepted=False)
    with pytest.raises(ValueError, match="could not be activated"):
        with resources.activate_v18_package(registry, ruleset):
            pytest.fail("failed package activation must not start validation")
    assert registry.path is not None and not registry.path.parent.exists()


def test_changed_package_is_rejected_before_registration(tmp_path: Path):
    ruleset = tmp_path / "rules.zip"
    with ZipFile(ruleset, "w") as archive:
        archive.writestr("packages/resources.zip", b"changed")
    registry = Registry()
    with pytest.raises(ValueError, match="hash does not match"):
        with resources.activate_v18_package(registry, ruleset):
            pytest.fail("changed package must not start validation")
    assert registry.path is None

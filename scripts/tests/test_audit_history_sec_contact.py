from __future__ import annotations

import os
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

from audit_history_sec_contact import SEC_USER_AGENT, load_sec_user_agent

CONTACT = "Audit Project/1.0 research@issuer.invalid"


def environment_digest() -> str:
    return hashlib.sha256(repr(sorted(os.environ.items())).encode()).hexdigest()


@pytest.mark.parametrize("quote", ("", "'", '"'))
def test_preserves_complete_contact_with_spaces_and_optional_quotes(tmp_path, quote):
    path = tmp_path / ".env"
    path.write_text(f"{SEC_USER_AGENT}={quote}{CONTACT}{quote}\n")
    assert load_sec_user_agent([path], environ={}) == CONTACT


def test_accepts_export_whitespace_crlf_and_equals_without_shell_execution(tmp_path):
    path = tmp_path / ".env"
    value = CONTACT + " label=a=b $(not-executed)"
    path.write_bytes(
        f"# SEC identity\r\nexport {SEC_USER_AGENT} = {value}\r\n".encode()
    )
    before = path.read_bytes(), path.stat().st_mtime_ns, environment_digest()
    assert load_sec_user_agent([path], environ={}) == value
    assert (path.read_bytes(), path.stat().st_mtime_ns, environment_digest()) == before


def test_process_override_is_complete_and_does_not_read_files(tmp_path):
    invalid_file = tmp_path / ".env"
    invalid_file.write_bytes(b"\xff")
    assert (
        load_sec_user_agent([invalid_file], environ={SEC_USER_AGENT: CONTACT})
        == CONTACT
    )


def test_first_defining_file_wins_and_missing_key_falls_through(tmp_path):
    absent = tmp_path / "absent.env"
    unrelated = tmp_path / "unrelated.env"
    first = tmp_path / "first.env"
    second = tmp_path / "second.env"
    unrelated.write_text("OTHER=value\n")
    first.write_text(f"{SEC_USER_AGENT}={CONTACT}\n")
    second.write_text(f"{SEC_USER_AGENT}=Another Project another@issuer.invalid\n")
    assert (
        load_sec_user_agent([absent, unrelated, first, second], environ={}) == CONTACT
    )


@pytest.mark.parametrize("invalid", ("", "Audit", "Project contact@example.com"))
def test_invalid_selected_value_cannot_silently_switch_files(tmp_path, invalid):
    first = tmp_path / "first.env"
    second = tmp_path / "second.env"
    first.write_text(f"{SEC_USER_AGENT}={invalid}\n")
    second.write_text(f"{SEC_USER_AGENT}={CONTACT}\n")
    with pytest.raises(ValueError):
        load_sec_user_agent([first, second], environ={})
    with pytest.raises(ValueError):
        load_sec_user_agent([second], environ={SEC_USER_AGENT: invalid})


def test_missing_contact_fails_without_network_or_environment_changes(tmp_path):
    before = environment_digest()
    with pytest.raises(ValueError, match="identifiable User-Agent"):
        load_sec_user_agent([tmp_path / ".env"], environ={})
    assert environment_digest() == before

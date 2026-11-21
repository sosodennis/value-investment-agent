"""Bounded HTTP worker; the caller process owns its absolute time budget."""

import json
import sys
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING or __package__:
    from .process_output import write_stdout
else:
    from process_output import write_stdout

MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_response(wire: dict) -> bytes:
    request = urllib.request.Request(
        wire["url"],
        data=wire["body"].encode("utf-8"),
        method=wire["method"],
        headers=wire["headers"],
    )
    with urllib.request.build_opener(_NoRedirect()).open(
        request, timeout=wire["timeout_seconds"]
    ) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("response byte budget exceeded")
    return raw


def main() -> int:
    try:
        raw = read_response(json.load(sys.stdin))
        write_stdout(raw)
    except urllib.error.HTTPError as error:
        sys.stderr.write(json.dumps({"http_status": error.code}))
        return 3
    except Exception:
        # The wire request contains a credential. Neither exception repr nor
        # arbitrary provider response bytes may reach the parent's diagnostics.
        sys.stderr.write(json.dumps({"transport_failed": True}))
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

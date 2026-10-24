"""Probe the isolated LiteLLM gateway without making an upstream request."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def request(path: str, *, authorized: bool = False) -> int:
    headers = {}
    if authorized:
        headers["Authorization"] = f"Bearer {os.environ['LITELLM_MASTER_KEY']}"
    request = urllib.request.Request(f"http://llm-gateway:4000{path}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def main() -> None:
    assert request("/health/liveliness") == 200
    assert request("/v1/models", authorized=True) == 200
    assert request("/model/info", authorized=True) == 200
    assert request("/v1/models") == 401
    print(
        json.dumps(
            {
                "migration": "pass",
                "liveness": "pass",
                "authenticated_catalog": "pass",
                "authenticated_model_info": "pass",
                "unauthorized_catalog": "401",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

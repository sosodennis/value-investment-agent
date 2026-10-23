from __future__ import annotations


class ProviderSettingsError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class OpenRouterKeyTestError(RuntimeError):
    """A sanitized key validation failure."""


class OpenRouterModelsError(RuntimeError):
    """The public OpenRouter model catalogue is unavailable or malformed."""

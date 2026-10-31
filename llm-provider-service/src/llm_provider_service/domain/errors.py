from __future__ import annotations


class ProviderSettingsError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class OpenRouterKeyTestError(RuntimeError):
    def __init__(self, code: str, *, retry_after_seconds: float | None = None) -> None:
        self.code = code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code)


class OpenRouterModelsError(RuntimeError):
    pass

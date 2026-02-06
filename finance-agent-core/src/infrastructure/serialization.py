import json
from decimal import Decimal
from typing import Any


class FinancialSafeSerializer:
    """
    Safely serializes and deserializes financial data,
    specifically handling Decimal types without precision loss.
    Prevents RCE by being explicit about supported types.
    """

    def dumps(self, obj: Any) -> bytes:
        return json.dumps(obj, default=self._default).encode("utf-8")

    def loads(self, data: bytes) -> Any:
        return json.loads(data.decode("utf-8"), object_hook=self._load)

    def _default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return {"__type__": "Decimal", "value": str(obj)}
        raise TypeError(
            f"Object of type {obj.__class__.__name__} is not JSON serializable"
        )

    def _load(self, obj: Any) -> Any:
        if isinstance(obj, dict) and obj.get("__type__") == "Decimal":
            return Decimal(obj["value"])
        return obj

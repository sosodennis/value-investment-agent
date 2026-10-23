from __future__ import annotations

import sys
from pathlib import Path

finance_core = Path(__file__).resolve().parents[2] / "finance-agent-core"
sys.path.insert(0, str(finance_core))

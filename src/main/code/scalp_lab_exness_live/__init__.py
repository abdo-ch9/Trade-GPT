"""Exness live runtime, sharing strategy code with isolated live state."""
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
__path__.extend((str(BASE / "scalp_lab_exness"), str(BASE / "scalp_lab")))

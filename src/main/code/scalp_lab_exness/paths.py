"""Separate Exness records from IC Markets records."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[4]
LIB_DIR = PROJECT_ROOT / "lib" / "exness"
ENV_FILE = PROJECT_ROOT / ".env"
LIB_DIR.mkdir(parents=True, exist_ok=True)

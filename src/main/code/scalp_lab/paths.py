"""Project locations shared by the dashboard, workers, and research tools."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
LIB_DIR = PROJECT_ROOT / "lib"
ENV_FILE = PROJECT_ROOT / ".env"

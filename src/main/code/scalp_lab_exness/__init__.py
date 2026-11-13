"""Exness broker implementation sharing broker-neutral research modules."""
from pathlib import Path

# Unchanged research modules load under this package, so their relative .paths
# imports use Exness storage while broker-specific modules override them here.
__path__.append(str(Path(__file__).resolve().parent.parent / "scalp_lab"))

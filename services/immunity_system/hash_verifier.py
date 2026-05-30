"""
Immunity system integrity verifier.
Computes SHA-256 of immunity.py at startup and re-verifies on demand.
"""
import hashlib
import os

_IMMUNITY_PATH = os.path.join(os.path.dirname(__file__), "immunity.py")
_BASELINE_HASH: str | None = None


def _hash_file(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def record_baseline():
    """Call once at startup to record the trusted hash."""
    global _BASELINE_HASH
    _BASELINE_HASH = _hash_file(_IMMUNITY_PATH)
    return _BASELINE_HASH


def verify_integrity() -> tuple[bool, str]:
    """Returns (ok, message). Call periodically to detect tampering."""
    if _BASELINE_HASH is None:
        return False, "Baseline not recorded — call record_baseline() first"
    current = _hash_file(_IMMUNITY_PATH)
    if current != _BASELINE_HASH:
        return False, f"INTEGRITY VIOLATION: immunity.py modified (expected={_BASELINE_HASH[:16]}…)"
    return True, "ok"

import hashlib, inspect, importlib

def compute_hash(module_name: str) -> str:
    mod = importlib.import_module(module_name)
    src = inspect.getsource(mod)
    return hashlib.sha256(src.encode()).hexdigest()

IMMUNITY_HASH = compute_hash("immunity")

def verify_immunity_integrity() -> bool:
    current = compute_hash("immunity")
    return current == IMMUNITY_HASH

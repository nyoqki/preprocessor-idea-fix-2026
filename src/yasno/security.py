import hashlib
import hmac
import time


def derive_key(secret: str, purpose: str) -> bytes:
    return hmac.new(secret.encode(), purpose.encode(), hashlib.sha256).digest()


def _signature(key: bytes, message: str) -> str:
    return hmac.new(key, message.encode(), hashlib.sha256).hexdigest()[:24]


def sign_token(key: bytes, subject: int, ttl_seconds: int, *, now: float | None = None) -> str:
    expires = int((now if now is not None else time.time()) + ttl_seconds)
    message = f"{subject}_{expires}"
    return f"{message}_{_signature(key, message)}"


def verify_token(key: bytes, token: str, *, now: float | None = None) -> int | None:
    if len(token) > 128 or not token.isascii():
        return None
    parts = token.split("_")
    if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    message = f"{parts[0]}_{parts[1]}"
    if not hmac.compare_digest(parts[2], _signature(key, message)):
        return None
    if int(parts[1]) < (now if now is not None else time.time()):
        return None
    return int(parts[0])

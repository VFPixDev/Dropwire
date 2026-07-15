import base64
import hashlib
import hmac
import json
import time
from pathlib import PurePosixPath


class TokenError(Exception):
    pass


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + pad).encode("ascii"))


def generate_download_token(relative_path: str, secret: str, ttl_seconds: int) -> str:
    payload = {
        "p": relative_path,
        "e": int(time.time()) + int(ttl_seconds),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_part = _b64url_encode(payload_bytes)
    signature = hmac.new(secret.encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_part}.{_b64url_encode(signature)}"


def verify_download_token(token: str, secret: str) -> dict[str, object]:
    if not isinstance(token, str) or not token or len(token) > 4096:
        raise TokenError("Некорректный токен")
    if not secret:
        raise TokenError("Секрет подписи не настроен")
    try:
        payload_part, signature_part = token.split(".", maxsplit=1)
    except ValueError as exc:
        raise TokenError("Некорректный токен") from exc

    expected_signature = hmac.new(secret.encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256).digest()
    try:
        got_signature = _b64url_decode(signature_part)
    except Exception as exc:
        raise TokenError("Некорректная подпись токена") from exc

    if len(got_signature) != hashlib.sha256().digest_size or not hmac.compare_digest(expected_signature, got_signature):
        raise TokenError("Подпись токена невалидна")

    try:
        payload = json.loads(_b64url_decode(payload_part).decode("utf-8"))
    except Exception as exc:
        raise TokenError("Некорректный payload токена") from exc

    if not isinstance(payload, dict):
        raise TokenError("Некорректный payload токена")
    try:
        expires_at = int(payload.get("e", 0))
    except (TypeError, ValueError) as exc:
        raise TokenError("Некорректный срок действия токена") from exc
    if time.time() > expires_at:
        raise TokenError("Ссылка истекла")

    relative_path = payload.get("p")
    if not isinstance(relative_path, str) or not relative_path.strip() or len(relative_path) > 512:
        raise TokenError("Путь в токене отсутствует")
    if "\\" in relative_path or "\x00" in relative_path:
        raise TokenError("Некорректный путь в токене")
    raw_parts = relative_path.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise TokenError("Некорректный путь в токене")
    path = PurePosixPath(relative_path)
    if path.is_absolute():
        raise TokenError("Некорректный путь в токене")

    return payload

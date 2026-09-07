import base64
import hashlib
import hmac
import json
import time

from passlib.context import CryptContext

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(value: str) -> str:
    return pwd.hash(value)


def verify_password(value: str, hashed: str) -> bool:
    return pwd.verify(value, hashed)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_token(user_id: int, secret: str, ttl_minutes: int) -> str:
    # 令牌只保存身份和过期时间，权限仍以数据库为准。
    payload = _b64(json.dumps({"sub": user_id, "exp": int(time.time()) + ttl_minutes * 60}, separators=(",", ":")).encode())
    signature = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def decode_token(token: str, secret: str) -> int:
    payload, signature = token.split(".", 1)
    expected = _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, signature):
        raise ValueError("登录凭证签名无效")
    data = json.loads(_unb64(payload))
    if int(data["exp"]) < int(time.time()):
        raise TimeoutError("登录凭证已过期")
    return int(data["sub"])

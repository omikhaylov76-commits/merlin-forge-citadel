"""Криптопримитивы auth (ADR-0008v2, решение D Куратора).

Разделяем намеренно: argon2 — ТОЛЬКО пароль человека (медленный, против брутфорса);
opaque-токены (256 бит энтропии) — быстрый SHA-256 (argon2 на них избыточен, токен и так случаен).
TOTP — заготовка (pyotp), в v1 выключен; включить до go-live (roadmap-гвоздь).
"""

import hashlib
import secrets

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph = PasswordHasher()


def new_token() -> str:
    return secrets.token_urlsafe(32)  # 32 байта = 256 бит


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except VerifyMismatchError:
        return False


# Заранее посчитанный argon2-хэш для КОНСТАНТНОГО времени логина (#1): verify против него,
# когда пользователя нет — задержка не выдаёт «есть/нет email» (enumeration).
DUMMY_PASSWORD_HASH = hash_password("constant-time-guard")


def verify_totp(secret: str, code: str) -> bool:
    # Заготовка: в v1 не вызывается из логина (TOTP off). Готова к включению до go-live.
    return pyotp.TOTP(secret).verify(code)

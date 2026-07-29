from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import Admin, AdminSession


class AuthenticationError(ValueError):
    pass


class PasswordPolicyError(ValueError):
    pass


_DUMMY_PASSWORD_HASH = b"$2b$12$WAFJHgTRsp1qIy4vukJ4puT7KHxT.7I6mGkK2b4YbX3f3AvkkLhnK"


@dataclass(frozen=True)
class AdminPrincipal:
    admin_id: int
    username: str
    role: str
    session_id: int


@dataclass(frozen=True)
class SessionTokens:
    access_token: str
    refresh_token: str
    csrf_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


def normalize_username(value: str) -> tuple[str, str]:
    raw = value.strip()
    if raw.startswith("@"):
        raw = raw[1:]
    if not raw or len(raw) > 32 or not raw.replace("_", "").isalnum():
        raise ValueError("Username must contain 1 to 32 letters, numbers, or underscores")
    key = raw.casefold()
    return "@" + key, key


def validate_password(value: str) -> None:
    if len(value) < 12 or len(value) > 72:
        raise PasswordPolicyError("Password must be between 12 and 72 characters")
    if not any(character.islower() for character in value):
        raise PasswordPolicyError("Password must include a lowercase letter")
    if not any(character.isupper() for character in value):
        raise PasswordPolicyError("Password must include an uppercase letter")
    if not any(character.isdigit() for character in value):
        raise PasswordPolicyError("Password must include a number")


def hash_password_sync(value: str) -> str:
    validate_password(value)
    return bcrypt.hashpw(value.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


async def hash_password(value: str) -> str:
    return await asyncio.to_thread(hash_password_sync, value)


async def verify_password(value: str, password_hash: str | None) -> bool:
    candidate = password_hash.encode("utf-8") if password_hash else _DUMMY_PASSWORD_HASH
    valid = await asyncio.to_thread(bcrypt.checkpw, value.encode("utf-8"), candidate)
    return bool(valid and password_hash)


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_base64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _signing_key(settings: Settings) -> bytes:
    if settings.admin_session_secret is None:
        raise AuthenticationError("Admin sessions are not configured")
    return settings.admin_session_secret.get_secret_value().encode("utf-8")


def issue_access_token(admin: Admin, session_id: int, settings: Settings, now: datetime | None = None) -> tuple[str, datetime]:
    now = now or datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.admin_access_token_minutes)
    header = _base64url(b'{"alg":"HS256","typ":"JWT"}')
    payload = _base64url(
        json.dumps(
            {
                "sub": str(admin.id),
                "sid": session_id,
                "role": admin.role,
                "usr": admin.username,
                "iss": "crous-admin",
                "aud": "crous-admin-panel",
                "iat": int(now.timestamp()),
                "exp": int(expires_at.timestamp()),
                "jti": secrets.token_urlsafe(16),
            },
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signature = _base64url(hmac.new(_signing_key(settings), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest())
    return f"{header}.{payload}.{signature}", expires_at


def decode_access_token(token: str, settings: Settings, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    try:
        header, payload, signature = token.split(".")
        header_json = json.loads(_decode_base64url(header))
        claims = json.loads(_decode_base64url(payload))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuthenticationError("Invalid access token") from error
    expected = _base64url(hmac.new(_signing_key(settings), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected) or header_json != {"alg": "HS256", "typ": "JWT"}:
        raise AuthenticationError("Invalid access token")
    if claims.get("iss") != "crous-admin" or claims.get("aud") != "crous-admin-panel":
        raise AuthenticationError("Invalid access token")
    if not isinstance(claims.get("exp"), int) or claims["exp"] <= int(now.timestamp()):
        raise AuthenticationError("Access token expired")
    if not isinstance(claims.get("sub"), str) or not isinstance(claims.get("sid"), int):
        raise AuthenticationError("Invalid access token")
    return claims


async def create_session(session: AsyncSession, admin: Admin, settings: Settings, now: datetime | None = None) -> SessionTokens:
    now = now or datetime.now(UTC)
    refresh_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    refresh_expires_at = now + timedelta(days=settings.admin_refresh_token_days)
    admin_session = AdminSession(
        admin_id=admin.id,
        refresh_token_hash=hash_token(refresh_token),
        csrf_token_hash=hash_token(csrf_token),
        expires_at=refresh_expires_at,
        last_used_at=now,
    )
    session.add(admin_session)
    await session.flush()
    access_token, access_expires_at = issue_access_token(admin, admin_session.id, settings, now)
    return SessionTokens(access_token, refresh_token, csrf_token, access_expires_at, refresh_expires_at)


async def rotate_session(session: AsyncSession, refresh_token: str, settings: Settings, now: datetime | None = None) -> tuple[Admin, SessionTokens]:
    now = now or datetime.now(UTC)
    previous = await session.scalar(
        select(AdminSession).where(
            AdminSession.refresh_token_hash == hash_token(refresh_token),
            AdminSession.revoked_at.is_(None),
            AdminSession.expires_at > now,
        )
    )
    if previous is None:
        raise AuthenticationError("Invalid refresh token")
    admin = await session.get(Admin, previous.admin_id)
    if admin is None or not admin.is_active:
        previous.revoked_at = now
        raise AuthenticationError("Administrator account is unavailable")
    previous.revoked_at = now
    previous.last_used_at = now
    tokens = await create_session(session, admin, settings, now)
    return admin, tokens


async def resolve_principal(session: AsyncSession, token: str, settings: Settings) -> AdminPrincipal:
    claims = decode_access_token(token, settings)
    try:
        admin_id = int(claims["sub"])
        session_id = int(claims["sid"])
    except (TypeError, ValueError) as error:
        raise AuthenticationError("Invalid access token") from error
    admin_session = await session.get(AdminSession, session_id)
    admin = await session.get(Admin, admin_id)
    if (
        admin_session is None
        or admin_session.admin_id != admin_id
        or admin_session.revoked_at is not None
        or _as_utc(admin_session.expires_at) <= datetime.now(UTC)
        or admin is None
        or not admin.is_active
        or admin.role not in {"admin", "superadmin"}
    ):
        raise AuthenticationError("Administrator session is unavailable")
    return AdminPrincipal(admin.id, admin.username, admin.role, admin_session.id)


async def csrf_is_valid(session: AsyncSession, principal: AdminPrincipal, csrf_token: str | None) -> bool:
    if not csrf_token:
        return False
    admin_session = await session.get(AdminSession, principal.session_id)
    return bool(admin_session and hmac.compare_digest(admin_session.csrf_token_hash, hash_token(csrf_token)))


async def refresh_csrf_is_valid(session: AsyncSession, refresh_token: str, csrf_token: str | None) -> bool:
    if not csrf_token:
        return False
    admin_session = await session.scalar(
        select(AdminSession).where(
            AdminSession.refresh_token_hash == hash_token(refresh_token),
            AdminSession.revoked_at.is_(None),
        )
    )
    return bool(admin_session and hmac.compare_digest(admin_session.csrf_token_hash, hash_token(csrf_token)))

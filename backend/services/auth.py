"""Autenticación multi-usuario ligera y sin dependencias externas (PBKDF2-SHA256 + tokens firmados HMAC)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time

from fastapi import HTTPException, Request

from .. import database, settings

COOKIE_NAME = "gh_session"
SESSION_TTL_SECONDS = 30 * 24 * 3600  # 30 días
PBKDF2_ITERATIONS = 310_000
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,30}$")


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(text: str) -> bytes:
    pad = "=" * ((4 - len(text) % 4) % 4)
    return base64.urlsafe_b64decode((text + pad).encode("ascii"))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64u_encode(salt)}${_b64u_encode(dk)}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algo, iters_str, salt_b64, dk_b64 = (stored_hash or "").split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iters = int(iters_str)
        salt = _b64u_decode(salt_b64)
        expected = _b64u_decode(dk_b64)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        return hmac.compare_digest(candidate, expected)
    except Exception:
        return False


def create_session_token(user: dict, ttl_seconds: int = SESSION_TTL_SECONDS) -> str:
    payload = {
        "uid": int(user["id"]),
        "usr": str(user["username"]).lower(),
        "exp": int(time.time() + ttl_seconds),
    }
    body = _b64u_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    key = settings.get_secret_key().encode("utf-8")
    sig = _b64u_encode(hmac.new(key, body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def _sanitize_user(row: dict) -> dict:
    username = str(row["username"]).lower()
    is_admin = bool(row.get("is_admin")) or bool(
        settings.ADMIN_USERNAME and username == settings.ADMIN_USERNAME
    )
    return {
        "id": int(row["id"]),
        "username": username,
        "display_name": row.get("display_name") or username,
        "is_admin": is_admin,
        "created_at": row.get("created_at"),
    }


def verify_session_token(token: str) -> dict | None:
    if not token or "." not in token:
        return None
    try:
        body, sig = token.split(".", 1)
        key = settings.get_secret_key().encode("utf-8")
        expected_sig = _b64u_encode(hmac.new(key, body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected_sig):
            return None
        payload = json.loads(_b64u_decode(body).decode("utf-8"))
        if int(payload.get("exp", 0)) < time.time():
            return None
        uid = int(payload["uid"])
        row = database.get_user_by_id(uid)
        if not row or str(row["username"]).lower() != str(payload.get("usr", "")).lower():
            return None
        return _sanitize_user(row)
    except Exception:
        return None


def register_user(
    username: str,
    password: str,
    display_name: str = "",
    invite_code: str = "",
) -> dict:
    clean_user = (username or "").strip().lower()
    if not USERNAME_RE.match(clean_user):
        raise ValueError(
            "El nombre de usuario debe tener entre 3 y 30 caracteres (letras, números, guiones o puntos)."
        )
    if not password or len(password) < 6:
        raise ValueError("La contraseña debe tener al menos 6 caracteres.")
    if len(password) > 128:
        raise ValueError("La contraseña es demasiado larga.")

    if settings.INVITE_CODE:
        provided = (invite_code or "").strip()
        if not provided or not hmac.compare_digest(provided, settings.INVITE_CODE):
            raise ValueError("Código de invitación incorrecto o no proporcionado.")

    if database.get_user_by_username(clean_user):
        raise ValueError(f"El usuario «{clean_user}» ya está registrado. Inicia sesión con tu contraseña.")

    is_first = database.count_users() == 0
    is_configured_admin = bool(settings.ADMIN_USERNAME and clean_user == settings.ADMIN_USERNAME)
    is_admin = is_first or is_configured_admin

    pw_hash = hash_password(password)
    disp = (display_name or username).strip()[:40] or clean_user
    created = database.create_user(
        username=clean_user,
        display_name=disp,
        password_hash=pw_hash,
        is_admin=is_admin,
    )
    return _sanitize_user(created)


def authenticate_user(username: str, password: str) -> dict:
    clean_user = (username or "").strip().lower()
    row = database.get_user_by_username(clean_user)
    if not row or not verify_password(password or "", row.get("password_hash") or ""):
        raise ValueError("Usuario o contraseña incorrectos.")
    return _sanitize_user(row)


def extract_token_from_request(request: Request) -> str | None:
    auth_header = (request.headers.get("Authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        tok = auth_header[7:].strip()
        if tok:
            return tok
    cookie_tok = request.cookies.get(COOKIE_NAME)
    if cookie_tok:
        return cookie_tok.strip()
    return None


def get_optional_user(request: Request) -> dict | None:
    tok = extract_token_from_request(request)
    if not tok:
        return None
    return verify_session_token(tok)


def require_user(request: Request) -> dict | None:
    user = get_optional_user(request)
    if user:
        return user
    if settings.REQUIRE_AUTH:
        raise HTTPException(
            status_code=401,
            detail="Inicia sesión o crea tu cuenta para acceder a GameHub.",
        )
    return None


def require_admin_or_local(request: Request) -> dict | None:
    user = get_optional_user(request)
    if not settings.IS_WEB_MODE and not settings.REQUIRE_AUTH:
        if user is None or user.get("is_admin"):
            return user
        raise HTTPException(
            status_code=403,
            detail="Solo la cuenta administradora puede modificar las fuentes.",
        )
    if not user:
        raise HTTPException(status_code=401, detail="Inicia sesión para continuar.")
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=403,
            detail="Solo el administrador de GameHub puede añadir o modificar las fuentes globales.",
        )
    return user

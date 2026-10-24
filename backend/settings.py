"""Rutas, modos de despliegue (Local vs Web Cloud) y ajustes globales de GameHub.

Variables de entorno soportadas (también desde archivo .env en la raíz):
  GAMEHUB_MODE           : 'local' (por defecto en PC) o 'web' (automático en Render / HF Spaces / Docker)
  GAMEHUB_REQUIRE_AUTH   : 'true' / 'false' (por defecto 'true' en modo web, 'false' en modo local)
  GAMEHUB_SECRET_KEY     : Clave secreta HMAC para firmar sesiones de usuario
  GAMEHUB_INVITE_CODE    : Código de invitación opcional para registrar nuevas cuentas de amigos
  GAMEHUB_ADMIN_USER     : Nombre de usuario que tendrá siempre permisos de Administrador
  GITHUB_STATE_TOKEN     : Token privado opcional para persistir usuarios/favoritos/fuentes en la nube a coste 0
  GITHUB_STATE_REPO      : Repositorio privado 'usuario/repo' donde guardar el estado cloud
  GITHUB_STATE_BRANCH    : Rama dedicada de estado (por defecto 'gamehub-state')
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    try:
        for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception:
        pass


_load_dotenv(ROOT_DIR / ".env")

FRONTEND_DIR = ROOT_DIR / "frontend"
CONFIG_DIR = Path(os.environ.get("GAMEHUB_CONFIG_DIR", ROOT_DIR / "config"))
DATA_DIR = Path(os.environ.get("GAMEHUB_DATA_DIR", ROOT_DIR / "data"))
DB_PATH = Path(os.environ.get("GAMEHUB_DB", DATA_DIR / "gamehub.db"))

SOURCES_FILE = CONFIG_DIR / "sources.json"
DEPENDENCIES_FILE = CONFIG_DIR / "dependencies.json"

# Detectar automáticamente entorno Cloud (Render, Hugging Face Spaces, Koyeb, Railway)
_CLOUD_ENV_DETECTED = any(
    os.environ.get(k)
    for k in ("RENDER", "SPACE_ID", "KOYEB_PUBLIC_DOMAIN", "RAILWAY_ENVIRONMENT", "FLY_APP_NAME")
)
DEPLOYMENT_MODE = os.environ.get("GAMEHUB_MODE", "web" if _CLOUD_ENV_DETECTED else "local").strip().lower()
if DEPLOYMENT_MODE not in ("local", "web"):
    DEPLOYMENT_MODE = "local"

IS_WEB_MODE = DEPLOYMENT_MODE == "web"

_req_auth_raw = os.environ.get("GAMEHUB_REQUIRE_AUTH", "").strip().lower()
if _req_auth_raw in ("1", "true", "yes"):
    REQUIRE_AUTH = True
elif _req_auth_raw in ("0", "false", "no"):
    REQUIRE_AUTH = False
else:
    REQUIRE_AUTH = IS_WEB_MODE

INVITE_CODE = os.environ.get("GAMEHUB_INVITE_CODE", "").strip()
ADMIN_USERNAME = os.environ.get("GAMEHUB_ADMIN_USER", "").strip().lower()

GITHUB_STATE_TOKEN = os.environ.get("GITHUB_STATE_TOKEN", "").strip()
GITHUB_STATE_REPO = os.environ.get("GITHUB_STATE_REPO", "").strip()
GITHUB_STATE_BRANCH = os.environ.get("GITHUB_STATE_BRANCH", "gamehub-state").strip() or "gamehub-state"


def get_secret_key() -> str:
    env_key = os.environ.get("GAMEHUB_SECRET_KEY", "").strip()
    if env_key:
        return env_key
    secret_file = DATA_DIR / ".secret_key"
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if secret_file.exists():
            val = secret_file.read_text(encoding="utf-8").strip()
            if len(val) >= 32:
                return val
        generated = secrets.token_hex(32)
        secret_file.write_text(generated, encoding="utf-8")
        return generated
    except Exception:
        return "gamehub-fallback-ephemeral-secret-key"


HOST = os.environ.get("GAMEHUB_HOST", "0.0.0.0" if IS_WEB_MODE else "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("PORT", os.environ.get("GAMEHUB_PORT", "8765")))
AUTO_SYNC = os.environ.get("GAMEHUB_NO_AUTOSYNC", "") not in ("1", "true", "yes")
SYNC_INTERVAL_SECONDS = 30 * 60  # Refresco automático de feeds cada 30 min
FEED_KEEP_PER_SOURCE = 600       # Nº máx. de entradas guardadas por feed (histórico para el buscador)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

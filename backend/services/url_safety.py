"""Validación anti-SSRF y seguridad de URLs/rutas locales antes de peticiones salientes."""
from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .. import settings

_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "metadata.google.internal",
    "metadata.goog",
    "metadata",
    "169.254.169.254",
    "0.0.0.0",
    "::1",
    "::",
}

_BLOCKED_SUFFIXES = (
    ".localhost",
    ".local",
    ".localdomain",
    ".internal",
    ".home.arpa",
)


def _is_forbidden_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
        ip_obj = ip_obj.ipv4_mapped
    return bool(
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    )


def validate_external_url(url: str, *, resolve_dns: bool = True) -> str:
    """Valida que una URL sea HTTP(S) pública y no apunte a localhost ni rangos internos (SSRF).

    Lanza ValueError si la URL es inválida o apunta a una red privada/reservada.
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError("URL vacía")

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ValueError("Solo se permiten URLs con esquema http:// o https://")

    if parsed.username or parsed.password:
        raise ValueError("No se permiten credenciales incrustadas en la URL")

    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError("La URL no contiene un dominio válido")

    if host in _BLOCKED_HOSTS or any(host.endswith(suf) for suf in _BLOCKED_SUFFIXES):
        raise ValueError("Por seguridad no se permiten direcciones locales o internas")

    # Comprobar si el host es una IP literal (IPv4 / IPv6)
    try:
        ip_lit = ipaddress.ip_address(host)
    except ValueError:
        ip_lit = None

    if ip_lit is not None:
        if _is_forbidden_ip(ip_lit):
            raise ValueError("Por seguridad no se permiten direcciones IP privadas o locales")
        return raw

    # Resolución DNS para bloquear dominios que apunten a 127.0.0.1 / 169.254.169.254 / LAN
    if resolve_dns:
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if scheme == "https" else 80), type=socket.SOCK_STREAM)
        except socket.gaierror:
            # Si el DNS falla (ej. entorno sin red o MockTransport de tests), dejamos que httpx gestione el error de red
            return raw
        except OSError:
            return raw

        for _fam, _type, _proto, _canon, sockaddr in infos:
            ip_str = sockaddr[0]
            try:
                resolved = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if _is_forbidden_ip(resolved):
                raise ValueError("El dominio resuelve a una dirección IP interna no permitida")

    return raw


def validate_local_json_path(raw_path: str) -> Path:
    """Resuelve un archivo JSON local de forma segura (en modo Web restringe a carpetas config)."""
    cleaned = (raw_path or "").strip()
    if cleaned.lower().startswith("file://"):
        raise ValueError("Por seguridad no se admite el esquema file://")

    p = Path(cleaned)
    resolved = (p if p.is_absolute() else (settings.ROOT_DIR / p)).resolve()

    if resolved.suffix.lower() != ".json":
        raise ValueError("Solo se permiten archivos locales con extensión .json")

    if settings.IS_WEB_MODE:
        allowed_roots = [
            settings.CONFIG_DIR.resolve(),
            settings.BUNDLED_CONFIG_DIR.resolve(),
        ]
        if not any(resolved.is_relative_to(root) for root in allowed_roots):
            raise ValueError("En modo Web no se permite leer rutas locales fuera de config/")

    return resolved


async def ssrf_request_hook(request: httpx.Request) -> None:
    """Hook asíncrono de httpx para validar cada petición saliente y cualquier redirección HTTP."""
    validate_external_url(str(request.url), resolve_dns=True)

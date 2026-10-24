"""Acciones de descarga local: Magnet (Windows startfile) y JDownloader 2 (Click'n'Load :9666)."""
from __future__ import annotations

import os
import subprocess
import sys
from typing import Callable
from urllib.parse import urlparse

import httpx

JD_BASE = "http://127.0.0.1:9666"

# Hook reemplazable en tests para verificar llamadas sin abrir el cliente Torrent real
_url_opener: Callable[[str], None] | None = None


def validate_download_uri(uri: str) -> str:
    if not isinstance(uri, str):
        raise ValueError("URI inválido")
    cleaned = uri.strip()
    low = cleaned.lower()
    if low.startswith("magnet:?xt="):
        return cleaned
    if low.startswith(("http://", "https://")):
        parsed = urlparse(cleaned)
        if parsed.netloc:
            return cleaned
    raise ValueError("Solo se permiten enlaces magnet:?xt=, http:// o https://")


def _default_open_uri(uri: str) -> None:
    if sys.platform == "win32":
        os.startfile(uri)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", uri])
    else:
        subprocess.Popen(["xdg-open", uri])


def open_magnet(uri: str) -> dict:
    cleaned = validate_download_uri(uri)
    if not cleaned.lower().startswith("magnet:?xt="):
        raise ValueError("El enlace debe comenzar por magnet:?xt=")
    opener = _url_opener or _default_open_uri
    opener(cleaned)
    return {"opened": True, "uri": cleaned}


def copy_to_windows_clipboard(text: str) -> bool:
    if sys.platform != "win32" or not text:
        return False
    try:
        subprocess.run(
            ["clip.exe"],
            input=text.encode("utf-16le"),
            check=False,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    except Exception:
        return False


async def check_jd_status(client: httpx.AsyncClient | None = None) -> dict:
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=0.35)
    assert client is not None
    try:
        r = await client.get(f"{JD_BASE}/jdcheck.js", timeout=0.35)
        online = r.status_code == 200 and ("jdownloader" in r.text.lower() or len(r.text) > 0)
        return {"online": online, "endpoint": JD_BASE}
    except Exception:
        return {"online": False, "endpoint": JD_BASE}
    finally:
        if own:
            await client.aclose()


async def send_to_jdownloader(
    urls: list[str],
    package_name: str = "GameHub Download",
    client: httpx.AsyncClient | None = None,
) -> dict:
    validated = [validate_download_uri(u) for u in urls if u and str(u).strip()]
    if not validated:
        raise ValueError("No se han proporcionado enlaces válidos para enviar")

    joined = "\r\n".join(validated)
    clean_pkg = (package_name or "GameHub").strip()[:120]

    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=2.5)
    assert client is not None
    try:
        status = await check_jd_status(client)
        if status["online"]:
            r = await client.post(
                f"{JD_BASE}/flash/add",
                data={
                    "package": clean_pkg,
                    "urls": joined,
                    "source": "http://127.0.0.1:8765",
                },
                headers={"Referer": "http://127.0.0.1:8765/"},
                timeout=2.5,
            )
            if r.status_code == 200:
                return {
                    "sent": True,
                    "online": True,
                    "clipboard_copied": False,
                    "count": len(validated),
                    "urls_text": joined,
                    "message": f"Paquete «{clean_pkg}» ({len(validated)} enlace/s) enviado a JDownloader 2.",
                }

        copied = copy_to_windows_clipboard(joined)
        return {
            "sent": False,
            "online": False,
            "clipboard_copied": copied,
            "count": len(validated),
            "urls_text": joined,
            "message": (
                "JDownloader 2 no está abierto ahora mismo. Los enlaces se han copiado al portapapeles "
                "para que su capturador los detecte en cuanto lo abras."
            ),
        }
    finally:
        if own:
            await client.aclose()

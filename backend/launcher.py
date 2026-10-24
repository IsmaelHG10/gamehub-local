"""Arranque amigable en Windows: detecta instancia previa, puerto libre y abre el navegador al instante."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from . import settings

# Evita que variables HTTP_PROXY del sistema intercepten peticiones locales a 127.0.0.1
_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _open_url_in_browser(url: str) -> None:
    """Abre el navegador predeterminado en Windows de forma inmediata y fiable."""
    if sys.platform == "win32":
        try:
            os.startfile(url)  # type: ignore[attr-defined]
            return
        except Exception:
            try:
                subprocess.Popen(
                    ["cmd.exe", "/c", "start", "", url],
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return
            except Exception:
                pass
    webbrowser.open(url, new=2)


def _is_gamehub_running(host: str, port: int) -> bool:
    for path, timeout in (("/api/ping", 0.6), ("/api/health", 1.8)):
        try:
            with _LOCAL_OPENER.open(f"http://{host}:{port}{path}", timeout=timeout) as resp:
                if resp.status == 200 and b"GameHub" in resp.read():
                    return True
        except Exception:
            continue
    return False


def _port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.25)
        return s.connect_ex((host, port)) != 0


def pick_port(host: str = settings.HOST, preferred: int = settings.DEFAULT_PORT) -> tuple[int, bool]:
    """Devuelve (puerto, ya_estaba_corriendo)."""
    if _is_gamehub_running(host, preferred):
        return preferred, True
    for candidate in range(preferred, preferred + 25):
        if _port_is_free(host, candidate):
            return candidate, False
    raise RuntimeError("No se encontró ningún puerto local libre entre 8765 y 8790")


def _open_browser_when_ready(url: str) -> None:
    for _ in range(50):
        try:
            with _LOCAL_OPENER.open(f"{url}/api/ping", timeout=0.5) as resp:
                if resp.status == 200:
                    break
        except Exception:
            time.sleep(0.1)
    print(f"  [OK] Abriendo navegador en {url} ...", flush=True)
    _open_url_in_browser(url)


def main() -> None:
    host = settings.HOST
    port, already_running = pick_port(host, settings.DEFAULT_PORT)
    url = f"http://{host}:{port}"

    if already_running:
        print(f"[GameHub Local] Ya está en ejecución en {url}. Abriendo navegador...", flush=True)
        _open_url_in_browser(url)
        return

    print("=" * 62, flush=True)
    print("  GameHub Local - Centro de Mando PC Gaming", flush=True)
    print(f"  URL local : {url}", flush=True)
    print("  Cierra esta ventana cuando termines de usar GameHub.", flush=True)
    print("=" * 62, flush=True)

    threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()
    uvicorn.run("backend.main:app", host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()

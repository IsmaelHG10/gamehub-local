"""Arranque amigable en Windows: detecta instancia previa, puerto libre y abre el navegador."""
from __future__ import annotations

import socket
import threading
import time
import urllib.request
import webbrowser

import uvicorn

from . import settings


def _is_gamehub_running(host: str, port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=0.8) as resp:
            return resp.status == 200 and b"GameHub" in resp.read()
    except Exception:
        return False


def _port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
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
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=0.6) as resp:
                if resp.status == 200:
                    break
        except Exception:
            time.sleep(0.2)
    webbrowser.open(url)


def main() -> None:
    host = settings.HOST
    port, already_running = pick_port(host, settings.DEFAULT_PORT)
    url = f"http://{host}:{port}"

    if already_running:
        print(f"[GameHub Local] Ya está en ejecución en {url}. Abriendo navegador...")
        webbrowser.open(url)
        return

    print("=" * 62)
    print("  GameHub Local - Centro de Mando PC Gaming")
    print(f"  URL local : {url}")
    print("  Cierra esta ventana cuando termines de usar GameHub.")
    print("=" * 62)

    threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()
    uvicorn.run("backend.main:app", host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()

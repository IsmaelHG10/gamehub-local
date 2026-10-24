"""Gestor de dependencias y herramientas de PC Gaming mediante Windows Winget."""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys

from .. import settings

WINGET_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_winget_id(pkg_id: str) -> str:
    cleaned = (pkg_id or "").strip()
    if not cleaned or not WINGET_ID_RE.match(cleaned):
        raise ValueError(f"Identificador de winget no permitido: {pkg_id!r}")
    return cleaned


def load_dependencies_config() -> dict:
    if not settings.DEPENDENCIES_FILE.exists():
        return {"runtimes": [], "tools": [], "safety_rules": []}
    return json.loads(settings.DEPENDENCIES_FILE.read_text(encoding="utf-8"))


def allowed_winget_ids() -> dict[str, dict]:
    cfg = load_dependencies_config()
    allowed: dict[str, dict] = {}
    for group in ("runtimes", "tools"):
        for entry in cfg.get(group) or []:
            wid = entry.get("winget_id")
            if wid and WINGET_ID_RE.match(wid):
                allowed[wid] = entry
    return allowed


def _find_winget() -> str | None:
    found = shutil.which("winget")
    if found:
        return found
    if sys.platform == "win32":
        local = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe")
        if os.path.exists(local):
            return local
    return None


import os  # noqa: E402


async def _run_exec(args: list[str], timeout: float = 30.0) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "Tiempo de espera agotado al consultar winget"
    text = (stdout or b"").decode("utf-8", errors="replace")
    return proc.returncode or 0, text


async def check_installed_status() -> dict:
    """Comprueba qué paquetes del catálogo están instalados actualmente en Windows."""
    allowed = allowed_winget_ids()
    winget_bin = _find_winget()
    if not winget_bin:
        return {
            "winget_available": False,
            "installed": {wid: False for wid in allowed},
            "message": "Winget no está disponible en este sistema; puedes usar los botones de descarga oficial.",
        }

    # Una única llamada global a `winget list` es ~6x más rápida que consultar paquete a paquete.
    code, output = await _run_exec(
        [winget_bin, "list", "--accept-source-agreements", "--disable-interactivity"],
        timeout=25.0,
    )
    lower_out = output.lower()
    installed: dict[str, bool] = {}

    if code == 0 and len(lower_out) > 40:
        for wid in allowed:
            # Coincidencia por palabra completa (case-insensitive)
            pattern = rf"(?<![a-z0-9._-]){re.escape(wid.lower())}(?![a-z0-9._-])"
            installed[wid] = bool(re.search(pattern, lower_out))
    else:
        # Fallback individual si `winget list` global devuelve código inesperado
        async def _probe_one(wid: str) -> tuple[str, bool]:
            c, out = await _run_exec(
                [winget_bin, "list", "--id", wid, "-e", "--accept-source-agreements", "--disable-interactivity"],
                timeout=12.0,
            )
            return wid, (c == 0 and wid.lower() in out.lower())

        pairs = await asyncio.gather(*(_probe_one(w) for w in allowed))
        installed = dict(pairs)

    return {
        "winget_available": True,
        "installed": installed,
        "installed_count": sum(1 for v in installed.values() if v),
        "total_count": len(installed),
    }


async def install_winget_packages(package_ids: list[str], interactive_window: bool = True) -> dict:
    """Instala uno o varios paquetes verificados contra la lista blanca de dependencies.json."""
    allowed = allowed_winget_ids()
    validated: list[str] = []
    for raw_id in package_ids:
        wid = validate_winget_id(raw_id)
        if wid not in allowed:
            raise ValueError(f"El paquete {wid} no forma parte del catálogo verificado")
        if wid not in validated:
            validated.append(wid)

    if not validated:
        raise ValueError("No se indicó ningún paquete para instalar")

    winget_bin = _find_winget()
    if not winget_bin:
        return {
            "started": False,
            "winget_available": False,
            "packages": validated,
            "message": "Winget no está instalado en este equipo. Usa el botón 'Web Oficial' de la tarjeta.",
        }

    if interactive_window and sys.platform == "win32":
        # En Windows abrimos una consola dedicada visible para que el usuario vea la barra de
        # progreso oficial de winget y pueda aceptar el diálogo UAC de administrador sin bloqueos.
        ps_commands = []
        for wid in validated:
            name = allowed[wid].get("name", wid).replace("'", "")
            ps_commands.append(
                f"Write-Host '==> Instalando {name} ({wid})...' -ForegroundColor Cyan; "
                f"& winget install -e --id '{wid}' --accept-package-agreements --accept-source-agreements"
            )
        ps_commands.append(
            "Write-Host ''; Write-Host 'Proceso finalizado. Ya puedes cerrar esta ventana y pulsar Comprobar instalados en GameHub.' -ForegroundColor Green; "
            "Read-Host 'Pulsa Enter para cerrar'"
        )
        script_body = "; ".join(ps_commands)
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script_body],
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
        names = ", ".join(allowed[w].get("name", w) for w in validated)
        return {
            "started": True,
            "mode": "console",
            "packages": validated,
            "message": f"Se ha abierto el instalador oficial de Windows (Winget) para: {names}.",
        }

    # Modo directo en segundo plano
    results = []
    for wid in validated:
        code, out = await _run_exec(
            [
                winget_bin, "install", "-e", "--id", wid,
                "--accept-package-agreements", "--accept-source-agreements",
            ],
            timeout=300.0,
        )
        results.append({"id": wid, "ok": code == 0, "code": code, "tail": out[-400:]})
    ok_all = all(r["ok"] for r in results)
    return {
        "started": True,
        "mode": "background",
        "ok": ok_all,
        "results": results,
        "packages": validated,
        "message": "Instalación completada." if ok_all else "Algún paquete requirió intervención manual.",
    }

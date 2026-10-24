"""Servidor principal FastAPI de GameHub Local."""
from __future__ import annotations

import asyncio
import subprocess
import sys
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import database, settings
from .adapters.autodetect import autodetect_url
from .adapters.base import new_client
from .services import downloader, release_calendar, source_manager, steam_enricher, winget_manager


async def _periodic_sync_loop() -> None:
    try:
        await asyncio.gather(
            source_manager.sync_sources(),
            release_calendar.sync_calendar(force=False),
            return_exceptions=True,
        )
    except Exception:
        pass
    while True:
        await asyncio.sleep(settings.SYNC_INTERVAL_SECONDS)
        try:
            await asyncio.gather(
                source_manager.sync_sources(),
                release_calendar.sync_calendar(force=False),
                return_exceptions=True,
            )
        except Exception:
            pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.init_db()
    sync_task: asyncio.Task | None = None
    if settings.AUTO_SYNC:
        sync_task = asyncio.create_task(_periodic_sync_loop())
    try:
        yield
    finally:
        if sync_task:
            sync_task.cancel()


app = FastAPI(
    title="GameHub Local",
    version="1.0.0",
    docs_url="/api/docs",
    lifespan=lifespan,
)


# --------------------------------------------------------------------------- Modelos Pydantic

class SourcePayload(BaseModel):
    id: str | None = None
    name: str
    type: str = "rss"
    category: str = "Descarga Directa"
    url: str = ""
    search_url_template: str = ""
    enabled: bool = True
    sync_now: bool = True


class AutodetectRequest(BaseModel):
    url: str


class BatchAutodetectRequest(BaseModel):
    urls: list[str]
    auto_save: bool = True


class ImportSourcesRequest(BaseModel):
    sources: list[dict[str, Any]]
    merge: bool = True


class RefreshRequest(BaseModel):
    source_id: str | None = None
    only_type: str | None = None


class MagnetRequest(BaseModel):
    uri: str


class JDownloaderRequest(BaseModel):
    urls: list[str]
    package_name: str = "GameHub Download"


class WingetInstallRequest(BaseModel):
    package_ids: list[str] = Field(min_length=1)
    interactive_window: bool = True


class BookmarkRequest(BaseModel):
    item: dict[str, Any]


class CalendarFavoriteRequest(BaseModel):
    item: dict[str, Any]


class CalendarTrackRequest(BaseModel):
    query: str
    favorite: bool = True


# --------------------------------------------------------------------------- Salud y Estado

@app.get("/api/ping")
async def api_ping():
    return {"ok": True, "app": "GameHub Local"}


@app.get("/api/health")
async def api_health():
    sources = source_manager.load_sources()
    jd = await downloader.check_jd_status()
    return {
        "ok": True,
        "app": "GameHub Local",
        "sources_total": len(sources),
        "sources_enabled": sum(1 for s in sources if s.get("enabled", True)),
        "jdownloader": jd,
        "stats": database.db_stats(),
    }


# --------------------------------------------------------------------------- Novedades y Búsqueda

@app.get("/api/releases/latest")
async def api_latest_releases(
    source_id: str | None = Query(default=None),
    category: str | None = Query(default=None),
    magnet_only: bool = Query(default=False),
    limit: int = Query(default=48, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    enrich: bool = Query(default=True),
):
    active_sources = [s for s in source_manager.load_sources() if s.get("enabled", True)]
    if source_id:
        source_ids = [s["id"] for s in active_sources if s["id"] == source_id]
    else:
        source_ids = [s["id"] for s in active_sources]

    items, total = database.query_latest(
        source_ids=source_ids,
        category=category or None,
        magnet_only=magnet_only,
        limit=limit,
        offset=offset,
    )

    # Si es la primera apertura y aún no hay datos cacheados para fuentes activas, sincroniza al vuelo
    if total == 0 and offset == 0 and source_ids and not category and not magnet_only:
        sync_status = database.get_sync_status()
        if any(sid not in sync_status for sid in source_ids):
            await source_manager.sync_sources(source_id=source_id)
            items, total = database.query_latest(
                source_ids=source_ids,
                category=None,
                magnet_only=False,
                limit=limit,
                offset=0,
            )

    if enrich and items:
        async with new_client(timeout=8.0) as client:
            await steam_enricher.enrich_items(items, client, max_network_lookups=20)

    bmarks = database.bookmark_ids()
    for it in items:
        it["bookmarked"] = it["id"] in bmarks

    sync_map = database.get_sync_status()
    last_sync = max((v.get("last_sync") or 0 for v in sync_map.values()), default=None)
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "last_sync": last_sync,
    }


@app.post("/api/releases/refresh")
async def api_refresh_releases(req: RefreshRequest | None = None):
    req = req or RefreshRequest()
    return await source_manager.sync_sources(only_type=req.only_type, source_id=req.source_id)


@app.get("/api/search")
async def api_search(
    q: str = Query(default="", max_length=160),
    enrich: bool = Query(default=True),
):
    return await source_manager.unified_search(q, enrich=enrich)


@app.get("/api/steam/details/{appid}")
async def api_steam_details(appid: int):
    if appid <= 0:
        raise HTTPException(status_code=400, detail="AppID inválido")
    try:
        async with new_client(timeout=10.0) as client:
            details = await steam_enricher.get_app_details(appid, client)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo consultar Steam: {exc}") from exc
    if not details:
        raise HTTPException(status_code=404, detail="Juego no encontrado en Steam")
    return details


# --------------------------------------------------------------------------- Guardados (Favoritos)

@app.get("/api/bookmarks")
async def api_bookmarks():
    return {"items": database.bookmark_list()}


@app.post("/api/bookmarks/toggle")
async def api_bookmark_toggle(req: BookmarkRequest):
    if not req.item.get("id") or not req.item.get("raw_title"):
        raise HTTPException(status_code=400, detail="Elemento inválido para guardar")
    saved = database.bookmark_toggle(req.item)
    return {"bookmarked": saved, "id": req.item["id"]}


# --------------------------------------------------------------------------- Calendario de Lanzamientos (Releases.com style)

@app.get("/api/calendar")
async def api_calendar(
    mode: str = Query(default="hot", pattern="^(hot|classic|favorites)$"),
    genre: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=120),
    force_refresh: bool = Query(default=False),
):
    return await release_calendar.get_calendar_data(
        mode=mode,
        genre=genre or None,
        q=q or None,
        force_refresh=force_refresh,
    )


@app.post("/api/calendar/refresh")
async def api_calendar_refresh():
    return await release_calendar.sync_calendar(force=True)


@app.get("/api/calendar/favorites")
async def api_calendar_favorites():
    items = release_calendar.list_favorites()
    return {"items": items, "total": len(items)}


@app.post("/api/calendar/favorites/toggle")
async def api_calendar_favorite_toggle(req: CalendarFavoriteRequest):
    if not req.item.get("appid"):
        raise HTTPException(status_code=400, detail="Falta el identificador appid del juego")
    saved = release_calendar.toggle_favorite(req.item)
    return {"favorited": saved, "appid": int(req.item["appid"])}


@app.post("/api/calendar/track")
async def api_calendar_track(req: CalendarTrackRequest):
    try:
        item = await release_calendar.search_and_add_game_to_calendar(req.query, favorite=req.favorite)
        return {"ok": True, "item": item}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error consultando Steam: {exc}") from exc


# --------------------------------------------------------------------------- Gestión de Fuentes

@app.get("/api/sources")
async def api_list_sources():
    return {"sources": source_manager.get_sources_with_stats()}


@app.post("/api/sources")
async def api_save_source(payload: SourcePayload):
    try:
        saved = source_manager.upsert_source(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sync_res = None
    if payload.sync_now and saved.get("enabled") and saved.get("type") != "search_url":
        sync_res = await source_manager.sync_sources(source_id=saved["id"])
    return {"source": saved, "sync": sync_res}


@app.patch("/api/sources/{source_id}/toggle")
async def api_toggle_source(source_id: str):
    sources = source_manager.load_sources()
    target = next((s for s in sources if s["id"] == source_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    target["enabled"] = not target.get("enabled", True)
    source_manager.save_sources(sources)
    if target["enabled"] and target.get("type") != "search_url":
        counts = database.count_by_source()
        if counts.get(source_id, 0) == 0:
            await source_manager.sync_sources(source_id=source_id)
    return {"source": target}


@app.delete("/api/sources/{source_id}")
async def api_delete_source(source_id: str):
    if not source_manager.delete_source(source_id):
        raise HTTPException(status_code=404, detail="Fuente no encontrada")
    return {"deleted": True, "id": source_id}


@app.post("/api/sources/autodetect")
async def api_autodetect_source(req: AutodetectRequest):
    try:
        return await autodetect_url(req.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/sources/autodetect-batch")
async def api_autodetect_batch(req: BatchAutodetectRequest):
    cleaned_urls = [u.strip() for u in req.urls if u and u.strip() and not u.strip().startswith("#")]
    if not cleaned_urls:
        raise HTTPException(status_code=400, detail="No se encontraron URLs válidas en la lista")

    sem = asyncio.Semaphore(5)
    async with new_client(timeout=10.0) as client:
        async def _detect_one(u: str) -> dict:
            async with sem:
                try:
                    res = await autodetect_url(u, client=client)
                    if req.auto_save:
                        saved = source_manager.upsert_source(res)
                        res["id"] = saved["id"]
                        res["saved"] = True
                    return {"ok": True, "input": u, "source": res}
                except Exception as exc:
                    return {"ok": False, "input": u, "error": str(exc)}

        results = await asyncio.gather(*(_detect_one(u) for u in cleaned_urls[:30]))

    if req.auto_save and any(r["ok"] for r in results):
        await source_manager.sync_sources()

    return {
        "processed": len(results),
        "added": sum(1 for r in results if r["ok"]),
        "results": list(results),
    }


@app.post("/api/sources/probe")
async def api_probe_source(payload: dict[str, Any]):
    try:
        return await source_manager.probe_source(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Fallo al probar la fuente: {exc}") from exc


@app.get("/api/sources/export")
async def api_export_sources():
    return {"sources": source_manager.load_sources()}


@app.post("/api/sources/import")
async def api_import_sources(req: ImportSourcesRequest):
    res = source_manager.import_sources(req.sources, merge=req.merge)
    await source_manager.sync_sources()
    return res


# --------------------------------------------------------------------------- Descargas 1-Clic

@app.get("/api/download/jd-status")
async def api_jd_status():
    return await downloader.check_jd_status()


@app.post("/api/download/magnet")
async def api_open_magnet(req: MagnetRequest):
    try:
        return downloader.open_magnet(req.uri)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"No se pudo abrir el cliente Torrent: {exc}") from exc


@app.post("/api/download/jdownloader")
async def api_send_jdownloader(req: JDownloaderRequest):
    try:
        return await downloader.send_to_jdownloader(req.urls, package_name=req.package_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --------------------------------------------------------------------------- Dependencias y Winget

@app.get("/api/dependencies")
async def api_dependencies():
    return winget_manager.load_dependencies_config()


@app.get("/api/dependencies/status")
async def api_dependencies_status():
    return await winget_manager.check_installed_status()


@app.post("/api/dependencies/install")
async def api_dependencies_install(req: WingetInstallRequest):
    try:
        return await winget_manager.install_winget_packages(
            req.package_ids,
            interactive_window=req.interactive_window,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --------------------------------------------------------------------------- Acceso directo Escritorio

@app.post("/api/system/desktop-shortcut")
async def api_create_desktop_shortcut():
    ps_script = settings.ROOT_DIR / "Crear_Acceso_Directo_Escritorio.ps1"
    if not ps_script.exists():
        raise HTTPException(status_code=404, detail="No se encontró Crear_Acceso_Directo_Escritorio.ps1")
    if sys.platform != "win32":
        return {"ok": False, "message": "La creación de accesos directos solo está disponible en Windows."}
    proc = await asyncio.create_subprocess_exec(
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ps_script),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    out, _ = await proc.communicate()
    msg = (out or b"").decode("utf-8", errors="replace").strip()
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=msg or "Error creando el acceso directo")
    return {"ok": True, "message": msg or "Acceso directo creado en el Escritorio."}


# --------------------------------------------------------------------------- Frontend Estático

if (settings.FRONTEND_DIR / "css").exists() or True:
    settings.FRONTEND_DIR.mkdir(parents=True, exist_ok=True)
    (settings.FRONTEND_DIR / "css").mkdir(parents=True, exist_ok=True)
    (settings.FRONTEND_DIR / "js").mkdir(parents=True, exist_ok=True)

app.mount("/css", StaticFiles(directory=str(settings.FRONTEND_DIR / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(settings.FRONTEND_DIR / "js")), name="js")


@app.get("/")
async def serve_spa():
    index_file = settings.FRONTEND_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Interfaz frontend no encontrada")
    return FileResponse(str(index_file), media_type="text/html; charset=utf-8")

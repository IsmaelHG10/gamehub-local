"""Gestión de fuentes (config/sources.json), sincronización y meta-búsqueda unificada."""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from typing import Any

from .. import database, settings
from ..adapters import ADAPTERS, SOURCE_TYPES, json_index, search_url
from ..adapters.base import new_client
from . import steam_enricher
from .title_cleaner import group_key

_config_lock = threading.Lock()
_sync_lock = asyncio.Lock()


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40] or "fuente"


def load_sources() -> list[dict]:
    with _config_lock:
        if not settings.SOURCES_FILE.exists():
            return []
        raw = json.loads(settings.SOURCES_FILE.read_text(encoding="utf-8"))
        sources = raw.get("sources") if isinstance(raw, dict) else raw
        return [s for s in (sources or []) if isinstance(s, dict) and s.get("id")]


def save_sources(sources: list[dict]) -> None:
    with _config_lock:
        settings.SOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = settings.SOURCES_FILE.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps({"sources": sources}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(settings.SOURCES_FILE)


def get_sources_with_stats() -> list[dict]:
    sources = load_sources()
    sync_map = database.get_sync_status()
    counts = database.count_by_source()
    enriched = []
    for s in sources:
        sid = s["id"]
        st = sync_map.get(sid) or {}
        enriched.append({
            **s,
            "cached_items": counts.get(sid, 0),
            "last_sync": st.get("last_sync"),
            "last_error": st.get("error"),
            "duration_ms": st.get("duration_ms"),
        })
    return enriched


def upsert_source(payload: dict) -> dict:
    stype = payload.get("type") or "rss"
    if stype not in SOURCE_TYPES:
        raise ValueError(f"Tipo de conector desconocido: {stype}")
    name = (payload.get("name") or "").strip()
    if not name:
        raise ValueError("El nombre de la fuente es obligatorio")
    url = (payload.get("url") or "").strip()
    template = (payload.get("search_url_template") or "").strip()
    if stype == "search_url" and not template:
        raise ValueError("Las fuentes de tipo redirección requieren una plantilla con {query}")
    if stype != "search_url" and not url:
        raise ValueError("La URL principal de la fuente es obligatoria")

    sources = load_sources()
    existing_ids = {s["id"] for s in sources}
    sid = (payload.get("id") or "").strip()
    is_update = bool(sid and sid in existing_ids)
    if not sid:
        base_id = _slugify(name)
        sid = base_id
        n = 2
        while sid in existing_ids:
            sid = f"{base_id}-{n}"
            n += 1

    record = {
        "id": sid,
        "name": name,
        "type": stype,
        "category": (payload.get("category") or "Descarga Directa").strip(),
        "url": url,
        "search_url_template": template,
        "enabled": bool(payload.get("enabled", True)),
    }

    if is_update:
        sources = [record if s["id"] == sid else s for s in sources]
    else:
        sources.append(record)
    save_sources(sources)
    return record


def delete_source(source_id: str) -> bool:
    sources = load_sources()
    filtered = [s for s in sources if s["id"] != source_id]
    if len(filtered) == len(sources):
        return False
    save_sources(filtered)
    database.delete_source_items(source_id)
    return True


def import_sources(new_sources: list[dict], merge: bool = True) -> dict:
    current = load_sources() if merge else []
    by_id = {s["id"]: s for s in current}
    added = 0
    for raw in new_sources:
        if not isinstance(raw, dict) or not raw.get("name"):
            continue
        stype = raw.get("type") if raw.get("type") in SOURCE_TYPES else "rss"
        sid = _slugify(raw.get("id") or raw["name"])
        by_id[sid] = {
            "id": sid,
            "name": str(raw["name"]).strip(),
            "type": stype,
            "category": str(raw.get("category") or "Descarga Directa").strip(),
            "url": str(raw.get("url") or "").strip(),
            "search_url_template": str(raw.get("search_url_template") or "").strip(),
            "enabled": bool(raw.get("enabled", True)),
        }
        added += 1
    save_sources(list(by_id.values()))
    return {"imported": added, "total": len(by_id)}


async def sync_single_source(source: dict, client) -> dict:
    sid = source["id"]
    stype = source.get("type") or "rss"
    t0 = time.perf_counter()
    try:
        if stype == json_index.TYPE:
            count, _ = await json_index.sync(source, client)
        elif stype == search_url.TYPE:
            count = 0
        else:
            adapter = ADAPTERS[stype]
            items = await adapter.fetch_latest(source, client)
            count = database.upsert_items(items)
            database.prune_source(sid, settings.FEED_KEEP_PER_SOURCE)
        ms = int((time.perf_counter() - t0) * 1000)
        database.set_sync_status(sid, count, None, ms)
        return {"id": sid, "name": source.get("name"), "ok": True, "count": count, "duration_ms": ms}
    except Exception as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        err = str(exc)[:240]
        database.set_sync_status(sid, 0, err, ms)
        return {"id": sid, "name": source.get("name"), "ok": False, "count": 0, "error": err, "duration_ms": ms}


async def sync_sources(only_type: str | None = None, source_id: str | None = None) -> dict:
    async with _sync_lock:
        sources = [s for s in load_sources() if s.get("enabled", True)]
        if source_id:
            sources = [s for s in load_sources() if s["id"] == source_id]
        if only_type:
            sources = [s for s in sources if s.get("type") == only_type]

        if not sources:
            return {"synced": 0, "results": [], "timestamp": time.time()}

        async with new_client(timeout=20.0) as client:
            results = await asyncio.gather(*(sync_single_source(s, client) for s in sources))
        return {
            "synced": sum(1 for r in results if r["ok"]),
            "total": len(results),
            "results": list(results),
            "timestamp": time.time(),
        }


async def probe_source(payload: dict) -> dict:
    """Prueba una fuente en vivo y devuelve latencia + muestra de juegos detectados."""
    stype = payload.get("type") or "rss"
    if stype not in SOURCE_TYPES:
        raise ValueError(f"Tipo inválido: {stype}")
    temp_source = {
        "id": payload.get("id") or "probe",
        "name": payload.get("name") or "Prueba",
        "type": stype,
        "category": payload.get("category") or "Descarga Directa",
        "url": payload.get("url") or "",
        "search_url_template": payload.get("search_url_template") or "",
    }
    t0 = time.perf_counter()
    if stype == search_url.TYPE:
        link = search_url.external_link(temp_source, "Hollow Knight")
        if not link:
            raise ValueError("La plantilla debe ser http(s) e incluir {query}")
        return {
            "ok": True,
            "latency_ms": 1,
            "count": 0,
            "sample": [],
            "sample_search_url": link["url"],
            "message": f"Plantilla válida. Ejemplo: {link['url']}",
        }

    async with new_client(timeout=15.0) as client:
        adapter = ADAPTERS[stype]
        items = await adapter.fetch_latest(temp_source, client)
        ms = int((time.perf_counter() - t0) * 1000)
        return {
            "ok": True,
            "latency_ms": ms,
            "count": len(items),
            "sample": [
                {
                    "raw_title": i["raw_title"],
                    "clean_title": i["clean_title"],
                    "file_size": i.get("file_size"),
                    "has_magnet": any(u.startswith("magnet:") for u in (i.get("uris") or [])),
                }
                for i in items[:5]
            ],
            "message": f"Conexión correcta ({ms} ms): {len(items)} entradas detectadas.",
        }


async def unified_search(query: str, enrich: bool = True) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"query": "", "items": [], "groups": [], "external_links": []}

    active_sources = [s for s in load_sources() if s.get("enabled", True)]
    active_ids = [s["id"] for s in active_sources]

    # 1. Enlaces directos a webs externas con search_url_template
    external_links = []
    for s in active_sources:
        ext = search_url.external_link(s, q)
        if ext:
            external_links.append(ext)

    # 2. Búsqueda instantánea FTS5 en todo lo cacheado e indexado localmente
    local_hits = database.search_catalog(q, active_ids, limit=120)

    # 3. Búsqueda en vivo en fuentes wp_api activas (en paralelo, timeout corto para no frenar)
    wp_sources = [s for s in active_sources if s.get("type") == "wp_api"]
    live_hits: list[dict] = []
    async with new_client(timeout=8.0) as client:
        if wp_sources:
            async def _safe_wp_search(src: dict) -> list[dict]:
                try:
                    found = await ADAPTERS["wp_api"].search(src, client, q)
                    if found:
                        database.upsert_items(found)
                    return found
                except Exception:
                    return []

            batches = await asyncio.gather(*(_safe_wp_search(s) for s in wp_sources))
            for b in batches:
                live_hits.extend(b)

        # Deduplicación conservando prioridad de coincidencias
        merged_map: dict[str, dict] = {}
        for item in [*live_hits, *local_hits]:
            dedup_key = f"{item['source_id']}|{item.get('page_url') or item['raw_title']}"
            if dedup_key not in merged_map:
                merged_map[dedup_key] = item

        items = list(merged_map.values())
        if enrich and items:
            await steam_enricher.enrich_items(items, client, max_network_lookups=20)

    bmarks = database.bookmark_ids()
    for it in items:
        it["bookmarked"] = it["id"] in bmarks

    # 4. Agrupación inteligente por juego para comparar fuentes de un vistazo
    groups_map: dict[str, dict] = {}
    for it in items:
        gk = group_key(it.get("clean_title") or it["raw_title"])
        steam = it.get("steam_info")
        if steam and steam.get("appid"):
            gk = f"steam-{steam['appid']}"
        grp = groups_map.get(gk)
        if not grp:
            grp = {
                "group_id": gk,
                "title": (steam or {}).get("official_name") or it.get("clean_title") or it["raw_title"],
                "steam_info": steam,
                "releases": [],
                "sources_count": 0,
                "has_magnet": False,
            }
            groups_map[gk] = grp
        elif not grp["steam_info"] and steam:
            grp["steam_info"] = steam
            grp["title"] = steam.get("official_name") or grp["title"]

        grp["releases"].append(it)
        if any(u.startswith("magnet:") for u in (it.get("uris") or [])):
            grp["has_magnet"] = True

    groups = list(groups_map.values())
    for g in groups:
        g["sources_count"] = len({r["source_id"] for r in g["releases"]})
        g["releases"].sort(key=lambda r: r.get("published_at") or "", reverse=True)

    return {
        "query": q,
        "total": len(items),
        "items": items,
        "groups": groups,
        "external_links": external_links,
    }

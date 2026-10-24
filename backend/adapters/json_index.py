"""Adaptador de catálogos JSON masivos ({"name":..., "downloads":[...]}) indexados con SQLite FTS5."""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from .. import database, settings
from .base import extract_size, make_item, to_iso

TYPE = "json_index"


def is_local_path(url: str) -> bool:
    return not url.lower().startswith(("http://", "https://"))


def resolve_local_path(url: str) -> Path:
    p = Path(url.removeprefix("file:///").removeprefix("file://"))
    return p if p.is_absolute() else (settings.ROOT_DIR / p)


async def load_raw(url: str, client: httpx.AsyncClient) -> dict:
    if is_local_path(url):
        path = resolve_local_path(url)
        return json.loads(path.read_text(encoding="utf-8-sig"))
    r = await client.get(url, timeout=60)
    r.raise_for_status()
    return r.json()


def looks_like_catalog(data) -> bool:
    return isinstance(data, dict) and isinstance(data.get("downloads"), list)


def parse_catalog(data: dict, source: dict) -> list[dict]:
    if not looks_like_catalog(data):
        raise ValueError("El JSON no tiene el formato de catálogo esperado (clave 'downloads')")
    items: dict[str, dict] = {}
    for entry in data["downloads"]:
        if not isinstance(entry, dict) or not entry.get("title"):
            continue
        uris = entry.get("uris") or entry.get("links") or []
        if isinstance(uris, str):
            uris = [uris]
        title = str(entry["title"])
        key = f"{title}|{uris[0] if uris else ''}"
        page = entry.get("url") or entry.get("page") or entry.get("page_url")
        item = make_item(
            source,
            title,
            key=key,
            published_at=to_iso(entry.get("uploadDate") or entry.get("date")),
            page_url=page if isinstance(page, str) and page.startswith("http") else None,
            file_size=entry.get("fileSize") or extract_size(title),
            uris=uris,
            excerpt=None,
            image_url=entry.get("image") if isinstance(entry.get("image"), str) else None,
        )
        items.setdefault(item["id"], item)
    return list(items.values())


async def sync(source: dict, client: httpx.AsyncClient) -> tuple[int, str]:
    """Descarga el catálogo y reemplaza su índice en SQLite. Devuelve (nº entradas, nombre)."""
    data = await load_raw(source["url"], client)
    items = parse_catalog(data, source)
    database.replace_source_items(source["id"], items)
    return len(items), str(data.get("name") or "")


async def fetch_latest(source: dict, client: httpx.AsyncClient) -> list[dict]:
    data = await load_raw(source["url"], client)
    items = parse_catalog(data, source)
    items.sort(key=lambda i: i.get("published_at") or "", reverse=True)
    return items


async def search(source: dict, client: httpx.AsyncClient, query: str) -> list[dict]:
    return database.search_catalog(query, [source["id"]], limit=50)

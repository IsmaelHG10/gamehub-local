"""Adaptador de plantillas de búsqueda web directa (https://web.com/?s={query})."""
from __future__ import annotations

from urllib.parse import quote_plus

import httpx

TYPE = "search_url"


def build_search_url(template: str, query: str) -> str | None:
    if not template or "{query}" not in template:
        return None
    if not template.lower().startswith(("http://", "https://")):
        return None
    return template.replace("{query}", quote_plus(query.strip()))


def external_link(source: dict, query: str) -> dict | None:
    url = build_search_url(source.get("search_url_template") or "", query)
    if not url:
        return None
    return {"source_id": source["id"], "name": source.get("name") or source["id"], "url": url,
            "category": source.get("category")}


async def fetch_latest(source: dict, client: httpx.AsyncClient) -> list[dict]:
    return []  # Solo redirección: no hay listado de novedades.


async def search(source: dict, client: httpx.AsyncClient, query: str) -> list[dict]:
    return []

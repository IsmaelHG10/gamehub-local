"""Autodetector inteligente de fuentes al pegar cualquier URL."""
from __future__ import annotations

import html
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from . import json_index, rss_feed
from .base import new_client, origin_of

_REPACK_HINTS = ("repack", "fitgirl", "dodi", "elamigos", "kaos", "xatab", "cpg", "catalyst", "mechanics")
_RETRO_HINTS = ("gog", "abandonware", "retro", "archive.org", "dosgames", "oldgames", "rom")


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:40] or "fuente"


def _pretty_host(url: str) -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    base = host.split(":")[0].split(".")[0] if host else "Fuente"
    return base.replace("-", " ").title() or host


def _guess_category(url: str, name: str, stype: str) -> str:
    if stype == json_index.TYPE:
        return "Catálogo JSON"
    haystack = f"{url} {name}".lower()
    if any(h in haystack for h in _REPACK_HINTS):
        return "Repacks"
    if any(h in haystack for h in _RETRO_HINTS):
        return "Retro / DRM-Free"
    return "Descarga Directa"


def _normalize_input_url(raw: str) -> str:
    u = (raw or "").strip()
    if not u:
        raise ValueError("Debes indicar una URL")
    if json_index.is_local_path(u) and u.lower().endswith(".json"):
        return u
    if not u.lower().startswith(("http://", "https://")):
        u = f"https://{u}"
    parsed = urlparse(u)
    if not parsed.netloc:
        raise ValueError(f"URL no válida: {raw}")
    return u


async def _fetch_wp_site_name(origin: str, client: httpx.AsyncClient) -> str | None:
    try:
        r = await client.get(f"{origin}/wp-json", timeout=6.0)
        if r.status_code == 200:
            name = (r.json() or {}).get("name")
            if isinstance(name, str) and name.strip():
                return html.unescape(name.strip())
    except Exception:
        pass
    return None


async def autodetect_url(raw_url: str, client: httpx.AsyncClient | None = None) -> dict:
    """Inspecciona una URL y devuelve una propuesta lista para guardar en sources.json."""
    url = _normalize_input_url(raw_url)

    # Caso 0: el usuario ya pegó una plantilla con {query}
    if "{query}" in url:
        origin = origin_of(url)
        name = _pretty_host(origin)
        return {
            "id": _slugify(name),
            "name": name,
            "type": "search_url",
            "category": _guess_category(url, name, "search_url"),
            "url": origin,
            "search_url_template": url,
            "enabled": True,
            "detected_items": 0,
            "message": f"Plantilla de búsqueda directa detectada para {name}.",
        }

    # Caso local .json
    if json_index.is_local_path(url):
        path = json_index.resolve_local_path(url)
        if not path.exists():
            raise ValueError(f"No se encontró el archivo JSON local: {url}")
        import json as _json
        data = _json.loads(path.read_text(encoding="utf-8-sig"))
        if not json_index.looks_like_catalog(data):
            raise ValueError("El archivo JSON no contiene la clave 'downloads'")
        name = str(data.get("name") or path.stem)
        count = len(data["downloads"])
        return {
            "id": _slugify(name),
            "name": name,
            "type": "json_index",
            "category": "Catálogo JSON",
            "url": url,
            "search_url_template": "",
            "enabled": True,
            "detected_items": count,
            "message": f"Catálogo JSON local detectado ({count} entradas).",
        }

    own_client = client is None
    if own_client:
        client = new_client(timeout=10.0)

    assert client is not None
    origin = origin_of(url)
    host_name = _pretty_host(origin)

    try:
        # Paso 1: Comprobar si la propia URL devuelve un catálogo JSON o un feed RSS/Atom directo.
        initial_resp: httpx.Response | None = None
        blocked_status: int | None = None
        try:
            initial_resp = await client.get(url, timeout=9.0)
            if initial_resp.status_code in (401, 403, 429, 503):
                blocked_status = initial_resp.status_code
        except httpx.HTTPError:
            initial_resp = None

        if initial_resp is not None and initial_resp.status_code == 200:
            ctype = (initial_resp.headers.get("content-type") or "").lower()
            body_head = initial_resp.text[:600].lstrip()

            # 1a. ¿JSON de catálogo?
            if "json" in ctype or url.lower().split("?")[0].endswith(".json") or body_head.startswith("{"):
                try:
                    jdata = initial_resp.json()
                    if json_index.looks_like_catalog(jdata):
                        name = str(jdata.get("name") or host_name).strip()
                        count = len(jdata["downloads"])
                        return {
                            "id": _slugify(name),
                            "name": name,
                            "type": "json_index",
                            "category": "Catálogo JSON",
                            "url": str(initial_resp.url),
                            "search_url_template": "",
                            "enabled": True,
                            "detected_items": count,
                            "message": f"Catálogo JSON detectado con {count} juegos listos para indexar.",
                        }
                except Exception:
                    pass

            # 1b. ¿La propia URL ya es un XML RSS o Atom?
            if any(tok in ctype for tok in ("xml", "rss", "atom")) or body_head.startswith(("<?xml", "<rss", "<feed")):
                try:
                    items, feed_title = rss_feed.parse_feed(initial_resp.content, {"id": "probe", "name": host_name})
                    if items:
                        name = feed_title or host_name
                        return {
                            "id": _slugify(name),
                            "name": name,
                            "type": "rss",
                            "category": _guess_category(url, name, "rss"),
                            "url": str(initial_resp.url),
                            "search_url_template": f"{origin}/?s={{query}}",
                            "enabled": True,
                            "detected_items": len(items),
                            "message": f"Feed RSS/Atom detectado ({len(items)} entradas recientes).",
                        }
                except Exception:
                    pass

        # Paso 2: Probar WordPress REST API (/wp-json/wp/v2/posts?per_page=2)
        try:
            wp_resp = await client.get(f"{origin}/wp-json/wp/v2/posts", params={"per_page": 2}, timeout=8.0)
            if wp_resp.status_code == 200:
                posts = wp_resp.json()
                if isinstance(posts, list) and (len(posts) == 0 or isinstance(posts[0], dict)):
                    site_name = await _fetch_wp_site_name(origin, client) or host_name
                    return {
                        "id": _slugify(site_name),
                        "name": site_name,
                        "type": "wp_api",
                        "category": _guess_category(origin, site_name, "wp_api"),
                        "url": origin,
                        "search_url_template": f"{origin}/?s={{query}}",
                        "enabled": True,
                        "detected_items": len(posts),
                        "message": f"API WordPress detectada en {site_name}: incluye Novedades y Búsqueda exacta.",
                    }
        except Exception:
            pass

        # Paso 3: Buscar <link rel="alternate" type="application/rss+xml"> o probar rutas RSS típicas
        candidate_feeds: list[str] = []
        page_title: str | None = None
        if initial_resp is not None and initial_resp.status_code == 200 and "<html" in initial_resp.text[:1500].lower():
            soup = BeautifulSoup(initial_resp.text, "html.parser")
            if soup.title and soup.title.string:
                page_title = html.unescape(soup.title.string.split("–")[0].split("|")[0].split("-")[0].strip())
            for link in soup.find_all("link", href=True):
                rels = [r.lower() for r in (link.get("rel") or [])]
                ltype = (link.get("type") or "").lower()
                if "alternate" in rels and ("rss" in ltype or "atom" in ltype):
                    candidate_feeds.append(urljoin(str(initial_resp.url), link["href"]))

        for suffix in ("/feed/", "/rss.xml", "/feed.xml", "/atom.xml", "/?feed=rss2"):
            candidate = f"{origin}{suffix}"
            if candidate not in candidate_feeds:
                candidate_feeds.append(candidate)

        for feed_url in candidate_feeds[:5]:
            try:
                fr = await client.get(feed_url, timeout=7.0)
                if fr.status_code != 200:
                    continue
                head = fr.text[:500].lstrip().lower()
                if "<html" in head and "<rss" not in head and "<feed" not in head:
                    continue
                items, feed_title = rss_feed.parse_feed(fr.content, {"id": "probe", "name": host_name})
                if items:
                    name = feed_title or page_title or host_name
                    return {
                        "id": _slugify(name),
                        "name": name,
                        "type": "rss",
                        "category": _guess_category(origin, name, "rss"),
                        "url": str(fr.url),
                        "search_url_template": f"{origin}/?s={{query}}",
                        "enabled": True,
                        "detected_items": len(items),
                        "message": f"Feed RSS detectado en {name} ({len(items)} novedades).",
                    }
            except Exception:
                continue

        # Paso 4: Fallback limpio a redirección directa desde el buscador
        name = page_title or host_name
        reason = (
            f"La web protege el acceso automatizado (HTTP {blocked_status}); "
            if blocked_status
            else "No se encontró API ni feed RSS público; "
        )
        return {
            "id": _slugify(name),
            "name": name,
            "type": "search_url",
            "category": _guess_category(origin, name, "search_url"),
            "url": origin,
            "search_url_template": f"{origin}/?s={{query}}",
            "enabled": True,
            "detected_items": 0,
            "message": f"{reason}configurada para búsqueda directa en 1 clic.",
        }
    finally:
        if own_client:
            await client.aclose()

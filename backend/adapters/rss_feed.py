"""Adaptador RSS 2.0 / Atom."""
from __future__ import annotations

import feedparser
import httpx

from .base import (
    extract_first_image, extract_magnets, extract_size, extract_torrent_links, html_to_text,
    make_item, to_iso,
)

TYPE = "rss"


def entry_to_item(entry, source: dict) -> dict:
    title = entry.get("title", "") or ""
    content_html = ""
    if entry.get("content"):
        content_html = " ".join(c.get("value", "") for c in entry["content"])
    summary_html = entry.get("summary", "") or ""
    full_html = f"{content_html} {summary_html}"

    uris: list[str] = extract_magnets(full_html)
    image = None
    for link in entry.get("links", []) or []:
        href = link.get("href", "") or ""
        ltype = (link.get("type") or "").lower()
        if href.startswith("magnet:"):
            uris.append(href)
        elif ltype == "application/x-bittorrent" or href.lower().endswith(".torrent"):
            uris.append(href)
        elif ltype.startswith("image/") and not image:
            image = href
    uris += extract_torrent_links(full_html)
    if entry.get("torrent_magneturi"):
        uris.append(entry["torrent_magneturi"])

    for key in ("media_thumbnail", "media_content"):
        if not image and entry.get(key):
            first = entry[key][0]
            if (first.get("medium") in (None, "image")) and first.get("url"):
                image = first["url"]
    image = image or extract_first_image(full_html)

    published = to_iso(entry.get("published_parsed") or entry.get("updated_parsed")) or to_iso(
        entry.get("published") or entry.get("updated")
    )
    plain = html_to_text(full_html, limit=5000)
    return make_item(
        source,
        title,
        key=entry.get("id") or entry.get("link") or title,
        published_at=published,
        page_url=entry.get("link"),
        file_size=extract_size(title) or extract_size(plain) or entry.get("contentlength"),
        uris=uris,
        excerpt=html_to_text(summary_html or content_html),
        image_url=image,
    )


def parse_feed(content: bytes | str, source: dict) -> tuple[list[dict], str]:
    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"El contenido no es un feed RSS/Atom válido ({feed.get('bozo_exception')})")
    title = (feed.feed.get("title") or "").strip()
    return [entry_to_item(e, source) for e in feed.entries[:60]], title


async def fetch_latest(source: dict, client: httpx.AsyncClient) -> list[dict]:
    r = await client.get(source["url"])
    r.raise_for_status()
    items, _ = parse_feed(r.content, source)
    return items


async def search(source: dict, client: httpx.AsyncClient, query: str) -> list[dict]:
    # Los feeds RSS no tienen búsqueda: se usa la caché local (FTS5) + search_url_template.
    return []

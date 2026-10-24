"""Adaptador WordPress REST API (/wp-json/wp/v2/posts)."""
from __future__ import annotations

import html

import httpx
from bs4 import BeautifulSoup

from .base import (
    extract_first_image, extract_magnets, extract_size, extract_torrent_links, html_to_text,
    make_item, origin_of, to_iso,
)

TYPE = "wp_api"


def _api_base(source: dict) -> str:
    url = (source.get("url") or "").rstrip("/")
    if "/wp-json" in url:
        url = url.split("/wp-json")[0]
    return url or origin_of(source.get("url", ""))


def post_to_item(post: dict, source: dict) -> dict:
    title_html = (post.get("title") or {}).get("rendered", "")
    title = html.unescape(BeautifulSoup(title_html, "html.parser").get_text(" ", strip=True))
    content = (post.get("content") or {}).get("rendered", "") or ""
    excerpt_html = (post.get("excerpt") or {}).get("rendered", "") or ""

    image = None
    embedded = post.get("_embedded") or {}
    media = embedded.get("wp:featuredmedia") or []
    if media and isinstance(media[0], dict):
        image = media[0].get("source_url")
    image = image or post.get("jetpack_featured_media_url") or extract_first_image(content)

    text_for_size = BeautifulSoup(content, "html.parser").get_text(" ") if content else ""
    date = post.get("date_gmt")
    published = to_iso(date + "Z") if date else to_iso(post.get("date"))

    return make_item(
        source,
        title,
        key=str(post.get("id") or post.get("link") or title),
        published_at=published,
        page_url=post.get("link"),
        file_size=extract_size(title) or extract_size(text_for_size),
        uris=extract_magnets(content) + extract_torrent_links(content),
        excerpt=html_to_text(excerpt_html) or html_to_text(content),
        image_url=image,
    )


async def _get_posts(source: dict, client: httpx.AsyncClient, params: dict) -> list[dict]:
    r = await client.get(f"{_api_base(source)}/wp-json/wp/v2/posts", params=params)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise ValueError("La respuesta de la API de WordPress no es una lista de entradas")
    return [post_to_item(p, source) for p in data if isinstance(p, dict)]


async def fetch_latest(source: dict, client: httpx.AsyncClient) -> list[dict]:
    return await _get_posts(source, client, {"per_page": 24, "_embed": 1})


async def search(source: dict, client: httpx.AsyncClient, query: str) -> list[dict]:
    return await _get_posts(source, client, {"search": query, "per_page": 15, "_embed": 1})

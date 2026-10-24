"""Modelo normalizado y utilidades comunes de los adaptadores."""
from __future__ import annotations

import hashlib
import html
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .. import settings
from ..services.title_cleaner import clean_game_title

SIZE_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:GB|MB|GiB|MiB)\b", re.IGNORECASE)
MAGNET_RE = re.compile(r"magnet:\?xt=urn:[a-z0-9]+:[a-z0-9]{20,}[^\s\"'<>]*", re.IGNORECASE)


@dataclass
class GameReleaseItem:
    id: str
    raw_title: str
    clean_title: str
    source_id: str
    source_name: str
    source_category: str
    published_at: str | None = None
    page_url: str | None = None
    file_size: str | None = None
    uris: list[str] = field(default_factory=list)
    excerpt: str | None = None
    image_url: str | None = None
    steam_info: dict | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def make_item(source: dict, raw_title: str, *, key: str, **kwargs: Any) -> dict:
    """Crea un GameReleaseItem (como dict) con id estable y título limpio."""
    raw_title = html.unescape(raw_title or "").strip()
    item_id = hashlib.sha1(f"{source['id']}|{key}".encode("utf-8")).hexdigest()[:20]
    uris = [u for u in dict.fromkeys(kwargs.pop("uris", None) or []) if is_valid_uri(u)]
    return GameReleaseItem(
        id=item_id,
        raw_title=raw_title,
        clean_title=clean_game_title(raw_title),
        source_id=source["id"],
        source_name=source.get("name") or source["id"],
        source_category=source.get("category") or "Descarga Directa",
        uris=uris,
        **kwargs,
    ).to_dict()


def is_valid_uri(uri: str) -> bool:
    if not isinstance(uri, str):
        return False
    uri = uri.strip()
    if uri.lower().startswith("magnet:?xt="):
        return True
    if uri.lower().startswith(("http://", "https://")):
        return bool(urlparse(uri).netloc)
    return False


def html_to_text(fragment: str | None, limit: int = 320) -> str:
    if not fragment:
        return ""
    text = BeautifulSoup(fragment, "html.parser").get_text(" ", strip=True)
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    text = re.sub(r"\s*(?:\[…\]|\[\.\.\.\]|Read more|Continue reading.*)$", "…", text)
    return text[:limit] + ("…" if len(text) > limit else "")


def extract_magnets(text: str | None) -> list[str]:
    if not text:
        return []
    return list(dict.fromkeys(html.unescape(m) for m in MAGNET_RE.findall(text)))


def extract_torrent_links(fragment: str | None) -> list[str]:
    if not fragment:
        return []
    soup = BeautifulSoup(fragment, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().split("?")[0].endswith(".torrent") and is_valid_uri(href):
            links.append(href)
    return links


def extract_first_image(fragment: str | None) -> str | None:
    if not fragment:
        return None
    soup = BeautifulSoup(fragment, "html.parser")
    for img in soup.find_all("img"):
        src = img.get("data-src") or img.get("data-lazy-src") or img.get("src") or ""
        if src.startswith(("http://", "https://")) and not src.lower().endswith((".gif", ".svg")):
            return src
    return None


def extract_size(text: str | None) -> str | None:
    if not text:
        return None
    m = SIZE_RE.search(text)
    return re.sub(r"\s+", " ", m.group(0)).replace(",", ".") if m else None


def to_iso(value: Any) -> str | None:
    """Normaliza fechas variadas a ISO-8601 UTC 'YYYY-MM-DDTHH:MM:SSZ' (ordenable lexicográficamente)."""
    if not value:
        return None
    dt: datetime | None = None
    try:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value / 1000 if value > 1e12 else value, tz=timezone.utc)
        elif isinstance(value, tuple):  # time.struct_time de feedparser
            dt = datetime(*value[:6], tzinfo=timezone.utc)
        elif isinstance(value, str):
            s = value.strip()
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                dt = parsedate_to_datetime(s)
    except (ValueError, TypeError, OverflowError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def origin_of(url: str) -> str:
    p = urlparse(url if "://" in url else f"https://{url}")
    return f"{p.scheme}://{p.netloc}"


def new_client(timeout: float = 15.0, transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=settings.BROWSER_HEADERS,
        follow_redirects=True,
        timeout=httpx.Timeout(timeout, connect=8.0),
        transport=transport,
    )

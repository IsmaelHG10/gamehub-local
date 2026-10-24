"""Enriquecimiento asíncrono con Steam Store API (sin API key) y caché SQLite."""
from __future__ import annotations

import asyncio
import re
from typing import Iterable

import httpx
from bs4 import BeautifulSoup

from .. import database

POS_TTL = 30 * 86400   # 30 días para juegos encontrados en Steam
NEG_TTL = 3 * 86400    # 3 días para títulos que no existen en Steam
DETAILS_TTL = 14 * 86400

_SEMAPHORE = asyncio.Semaphore(4)

_EDITION_STRIP_RE = re.compile(
    r"\s*[:\-–—]?\s*\b(?:the\s+)?(?:digital\s+)?(?:ultimate|deluxe|complete|definitive|premium|"
    r"gold|goty|game of the year|enhanced|anniversary|special|director'?s cut|remastered)"
    r"(?:\s+edition)?\b.*$",
    re.IGNORECASE,
)


def poster_urls(appid: int) -> dict[str, str]:
    base = f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}"
    return {
        "poster_url": f"{base}/library_600x900.jpg",
        "header_url": f"{base}/header.jpg",
        "store_url": f"https://store.steampowered.com/app/{appid}/",
    }


def _candidate_queries(clean_title: str) -> list[str]:
    q = (clean_title or "").strip()
    if not q:
        return []
    candidates: list[str] = []
    no_ed = _EDITION_STRIP_RE.sub("", q).strip(" -–—:|")
    if no_ed and no_ed.lower() != q.lower() and len(no_ed) >= 2:
        candidates.append(no_ed)
    candidates.append(q)
    for sep in (":", " – ", " - ", " — "):
        if sep in q:
            head = q.split(sep)[0].strip()
            if len(head) >= 3 and head not in candidates:
                candidates.append(head)
    return candidates[:3]


def _pick_best_item(items: list[dict], target: str) -> dict | None:
    if not items:
        return None
    norm_target = database.normalize_key(target)
    target_tokens = set(norm_target.split())

    best = None
    best_score = -999.0
    for idx, it in enumerate(items):
        name = str(it.get("name") or "")
        norm_name = database.normalize_key(name)
        if not norm_name:
            continue
        score = -idx * 0.4  # respeta ligeramente el orden de relevancia de Steam
        if norm_name == norm_target:
            score += 50.0
        elif norm_name.startswith(norm_target) or norm_target.startswith(norm_name):
            score += 20.0
        tokens = set(norm_name.split())
        if target_tokens and tokens:
            overlap = len(target_tokens & tokens) / max(len(target_tokens), 1)
            score += overlap * 15.0
        # Penaliza bandas sonoras / artbooks / demos / DLCs sueltos cuando buscamos el juego base
        if any(
            bad in norm_name
            for bad in ("soundtrack", "artbook", "ost", "demo", "playtest", "wallpaper", " dlc", "upgrade pack", "season pass", "bonus content")
        ):
            if not any(bad in norm_target for bad in ("soundtrack", "ost", "demo", "dlc")):
                score -= 35.0
        if score > best_score:
            best_score = score
            best = it
    return best


async def lookup_title(clean_title: str, client: httpx.AsyncClient) -> dict | None:
    if not clean_title or len(clean_title.strip()) < 2:
        return None
    cached = database.steam_cache_get(clean_title)
    if cached is not database._MISS:
        return cached  # type: ignore[return-value]

    async with _SEMAPHORE:
        # Doble comprobación tras adquirir el semáforo
        cached = database.steam_cache_get(clean_title)
        if cached is not database._MISS:
            return cached  # type: ignore[return-value]

        for candidate in _candidate_queries(clean_title):
            try:
                r = await client.get(
                    "https://store.steampowered.com/api/storesearch/",
                    params={"term": candidate, "l": "spanish", "cc": "ES"},
                    timeout=7.0,
                )
                if r.status_code != 200:
                    continue
                payload = r.json() or {}
                chosen = _pick_best_item(payload.get("items") or [], candidate)
                if chosen and chosen.get("id"):
                    appid = int(chosen["id"])
                    info = {
                        "appid": appid,
                        "official_name": chosen.get("name") or clean_title,
                        "metascore": (chosen.get("metascore") or None) or None,
                        "tiny_image": chosen.get("tiny_image"),
                        **poster_urls(appid),
                    }
                    database.steam_cache_set(clean_title, info, POS_TTL)
                    return info
            except Exception:
                # Si hay un fallo puntual de red, no cacheamos negativo para poder reintentar luego
                return None

        database.steam_cache_set(clean_title, None, NEG_TTL)
        return None


async def enrich_items(
    items: Iterable[dict],
    client: httpx.AsyncClient,
    max_network_lookups: int = 24,
) -> list[dict]:
    """Adjunta steam_info desde caché SQLite al instante y resuelve los faltantes en paralelo."""
    item_list = list(items)
    if not item_list:
        return item_list

    titles = [i.get("clean_title") or "" for i in item_list if i.get("clean_title")]
    cached_map = database.steam_cache_get_many(titles)

    missing_titles: list[str] = []
    seen_missing: set[str] = set()
    for t in titles:
        if cached_map.get(t, database._MISS) is database._MISS:
            norm = database.normalize_key(t)
            if norm and norm not in seen_missing:
                seen_missing.add(norm)
                missing_titles.append(t)

    fetched_by_norm: dict[str, dict | None] = {}
    to_fetch = missing_titles[:max_network_lookups]
    if to_fetch:
        results = await asyncio.gather(
            *(lookup_title(t, client) for t in to_fetch),
            return_exceptions=True,
        )
        for t, res in zip(to_fetch, results):
            if isinstance(res, dict) or res is None:
                fetched_by_norm[database.normalize_key(t)] = res

    for item in item_list:
        ct = item.get("clean_title") or ""
        val = cached_map.get(ct, database._MISS)
        if val is database._MISS:
            val = fetched_by_norm.get(database.normalize_key(ct))
        item["steam_info"] = val if isinstance(val, dict) else None

    return item_list


def _clean_req_html(raw_html: str | None) -> str:
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert_before("• ")
        li.append("\n")
    lines = [ln.strip() for ln in soup.get_text().splitlines() if ln.strip()]
    return "\n".join(lines[:12])


async def get_app_details(appid: int, client: httpx.AsyncClient) -> dict | None:
    cached = database.steam_details_get(appid)
    if cached:
        return cached

    async with _SEMAPHORE:
        r = await client.get(
            "https://store.steampowered.com/api/appdetails",
            params={"appids": str(appid), "l": "spanish"},
            timeout=9.0,
        )
        r.raise_for_status()
        entry = (r.json() or {}).get(str(appid)) or {}
        if not entry.get("success") or not isinstance(entry.get("data"), dict):
            return None
        d = entry["data"]
        pc_req = d.get("pc_requirements") if isinstance(d.get("pc_requirements"), dict) else {}
        details = {
            "appid": appid,
            "name": d.get("name"),
            "short_description": d.get("short_description") or "",
            "genres": [g["description"] for g in (d.get("genres") or []) if g.get("description")],
            "developers": d.get("developers") or [],
            "publishers": d.get("publishers") or [],
            "release_date": (d.get("release_date") or {}).get("date") or "",
            "metacritic": (d.get("metacritic") or {}).get("score"),
            "screenshots": [
                {"thumb": s.get("path_thumbnail"), "full": s.get("path_full")}
                for s in (d.get("screenshots") or [])[:6]
                if s.get("path_thumbnail")
            ],
            "pc_minimum": _clean_req_html(pc_req.get("minimum")),
            "pc_recommended": _clean_req_html(pc_req.get("recommended")),
            **poster_urls(appid),
        }
        database.steam_details_set(appid, details, DETAILS_TTL)
        return details

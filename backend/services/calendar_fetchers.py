"""Consultas HTTP asíncronas de fuentes del calendario (Steam, Nintendo eShop, PlayStation y Wikipedia)."""
from __future__ import annotations

import asyncio
import html
import re
from datetime import date, timedelta
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .. import database
from .calendar_parsers import (
    clean_wiki_text,
    normalize_genres,
    normalize_platforms,
    parse_nintendo_solr_docs,
    parse_playstation_upcoming_html,
    parse_steam_date,
    parse_steam_search_html,
    parse_wikipedia_release_html,
    synthetic_game_id,
    title_similarity,
)
from .steam_enricher import poster_urls

WIKI_ART_TTL = 7 * 86400  # Caché de portadas/sinopsis de Wikipedia (7 días)
WIKI_USER_AGENT = (
    "GameHub/2.0 (https://github.com/IsmaelHG10/gamehub-local; multi-platform release calendar) httpx/0.27"
)


async def fetch_steam_batch(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    start: int,
    count: int = 100,
    is_hot: bool = False,
    only_recent_days: int | None = None,
    **extra_params: Any,
) -> list[dict]:
    async with sem:
        r = await client.get(
            "https://store.steampowered.com/search/results/",
            params={
                "query": "",
                "start": start,
                "count": count,
                "category1": 998,
                "os": "win",
                "l": "english",
                "cc": "ES",
                "infinite": 1,
                **extra_params,
            },
            timeout=12.0,
        )
        r.raise_for_status()
        data = r.json() or {}
        items = parse_steam_search_html(data.get("results_html", ""), is_hot=is_hot)
        if only_recent_days is not None:
            cutoff = (date.today() - timedelta(days=only_recent_days)).isoformat()
            items = [
                it for it in items
                if it["precision"] == "day" and (it["release_date"] or "") >= cutoff
            ]
        return items


async def fetch_nintendo_events(client: httpx.AsyncClient) -> list[dict]:
    cutoff_iso = (date.today() - timedelta(days=50)).isoformat()
    today_iso = date.today().isoformat()
    out: list[dict] = []

    queries = [
        {
            "q": "*",
            "fq": "type:GAME AND system_type:nintendoswitch2*",
            "sort": "dates_released_dts desc",
            "rows": 180,
            "wt": "json",
        },
        {
            "q": "*",
            "fq": f"type:GAME AND system_type:nintendoswitch* AND dates_released_dts:[{today_iso}T00:00:00Z TO 2049-12-31T23:59:59Z]",
            "sort": "dates_released_dts asc",
            "rows": 80,
            "wt": "json",
        },
    ]

    for params in queries:
        try:
            r = await client.get(
                "https://searching.nintendo-europe.com/es/select",
                params=params,
                timeout=12.0,
            )
            if r.status_code == 200:
                docs = ((r.json() or {}).get("response") or {}).get("docs") or []
                out.extend(parse_nintendo_solr_docs(docs, cutoff_iso=cutoff_iso))
        except Exception:
            continue
    return out


async def fetch_playstation_events(client: httpx.AsyncClient) -> list[dict]:
    try:
        r = await client.get(
            "https://www.playstation.com/es-es/ps5/games/",
            headers={"Accept-Language": "es-ES,es;q=0.9"},
            timeout=12.0,
        )
        if r.status_code == 200:
            return parse_playstation_upcoming_html(r.text)
    except Exception:
        pass
    return []


async def fetch_wikipedia_events() -> list[dict]:
    cutoff_iso = (date.today() - timedelta(days=45)).isoformat()
    cur_year = date.today().year
    pages = [
        (f"List_of_video_games_released_in_{cur_year}", cur_year),
        (f"List_of_video_games_released_in_{cur_year + 1}", cur_year + 1),
    ]
    out: list[dict] = []
    async with httpx.AsyncClient(
        headers={"User-Agent": WIKI_USER_AGENT},
        timeout=16.0,
        follow_redirects=True,
    ) as wc:
        async def _get_page(page_name: str, yr: int) -> list[dict]:
            try:
                r = await wc.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={
                        "action": "parse",
                        "page": page_name,
                        "prop": "text",
                        "format": "json",
                    },
                )
                if r.status_code != 200:
                    return []
                parsed = (r.json() or {}).get("parse") or {}
                html_body = (parsed.get("text") or {}).get("*") or ""
                if not html_body:
                    return []
                return parse_wikipedia_release_html(html_body, year=yr, cutoff_iso=cutoff_iso)
            except Exception:
                return []

        results = await asyncio.gather(*(_get_page(p, y) for p, y in pages), return_exceptions=True)
        for res in results:
            if isinstance(res, list):
                out.extend(res)
    return out


async def enrich_wiki_artwork(items: list[dict]) -> None:
    """Obtiene portadas oficiales (pilicense=any) y sinopsis desde Wikipedia en lotes de 45 títulos."""
    candidates: list[dict] = [
        it for it in items
        if it.get("appid", 0) < 0 and (
            not it.get("poster_url") or not it.get("summary") or "1x1_" in (it.get("poster_url") or "")
        )
    ]
    if not candidates:
        return

    candidates.sort(key=lambda x: (-int(x.get("is_hot", 0)), x.get("release_date") or "9999-12-31"))
    candidates = candidates[:200]

    cache_keys = [f"wiki_art:{it.get('_wiki_hint') or it['title']}" for it in candidates]
    cached_map = database.steam_cache_get_many(cache_keys)

    to_query: dict[str, list[dict]] = {}
    for it, ckey in zip(candidates, cache_keys):
        hit = cached_map.get(ckey, database._MISS)
        if hit is not database._MISS:
            if isinstance(hit, dict):
                if hit.get("poster_url") and (not it.get("poster_url") or "1x1_" in it.get("poster_url", "")):
                    if not it.get("header_url"):
                        it["header_url"] = it.get("poster_url") or hit["poster_url"]
                    it["poster_url"] = hit["poster_url"]
                if hit.get("summary") and not it.get("summary"):
                    it["summary"] = hit["summary"]
                if hit.get("url") and not it.get("store_url"):
                    it["store_url"] = hit["url"]
        else:
            hint = (it.get("_wiki_hint") or it["title"]).strip()
            if hint:
                to_query.setdefault(hint, []).append(it)

    if not to_query:
        return

    hints = list(to_query.keys())
    async with httpx.AsyncClient(
        headers={"User-Agent": WIKI_USER_AGENT},
        timeout=12.0,
        follow_redirects=True,
    ) as wc:
        for i in range(0, len(hints), 45):
            chunk = hints[i:i + 45]
            try:
                r = await wc.get(
                    "https://en.wikipedia.org/w/api.php",
                    params={
                        "action": "query",
                        "titles": "|".join(chunk),
                        "prop": "pageimages|extracts|info",
                        "inprop": "url",
                        "exintro": 1,
                        "explaintext": 1,
                        "pilicense": "any",
                        "piprop": "original|thumbnail",
                        "pithumbsize": 600,
                        "redirects": 1,
                        "format": "json",
                    },
                )
                if r.status_code != 200:
                    continue
                qdata = (r.json() or {}).get("query") or {}

                norm_map: dict[str, str] = {
                    n["from"]: n["to"] for n in (qdata.get("normalized") or [])
                }
                redir_map: dict[str, str] = {
                    rd["from"]: rd["to"] for rd in (qdata.get("redirects") or [])
                }

                pages_by_title: dict[str, dict] = {
                    p["title"]: p
                    for p in (qdata.get("pages") or {}).values()
                    if isinstance(p, dict) and p.get("title") and "missing" not in p
                }

                for orig_hint in chunk:
                    step1 = norm_map.get(orig_hint, orig_hint)
                    final_title = redir_map.get(step1, step1)
                    p = pages_by_title.get(final_title)
                    if not p:
                        p = next(
                            (v for k, v in pages_by_title.items() if k.lower() == final_title.lower()),
                            None,
                        )

                    ckey = f"wiki_art:{orig_hint}"
                    if not p:
                        database.steam_cache_set(ckey, None, WIKI_ART_TTL)
                        continue

                    thumb = (
                        (p.get("thumbnail") or {}).get("source")
                        or (p.get("original") or {}).get("source")
                        or ""
                    ).strip()
                    extract = (p.get("extract") or "").strip()
                    if extract:
                        extract = re.sub(r"\s+", " ", extract)[:550]
                    fullurl = (p.get("fullurl") or "").strip()

                    payload = {"poster_url": thumb, "summary": extract, "url": fullurl}
                    database.steam_cache_set(ckey, payload if (thumb or extract) else None, WIKI_ART_TTL)

                    for target_it in to_query.get(orig_hint, []):
                        if thumb and (not target_it.get("poster_url") or "1x1_" in target_it.get("poster_url", "")):
                            if not target_it.get("header_url"):
                                target_it["header_url"] = target_it.get("poster_url") or thumb
                            target_it["poster_url"] = thumb
                        if extract and not target_it.get("summary"):
                            target_it["summary"] = extract
                        if fullurl and not target_it.get("store_url"):
                            target_it["store_url"] = fullurl
            except Exception:
                continue


# --------------------------------------------------------------------------- Búsqueda individual para seguimiento manual

async def search_steam_candidate(client: httpx.AsyncClient, q: str) -> dict | None:
    try:
        r = await client.get(
            "https://store.steampowered.com/api/storesearch/",
            params={"term": q, "l": "english", "cc": "ES"},
        )
        if r.status_code != 200:
            return None
        candidates = (r.json() or {}).get("items") or []
        if not candidates:
            return None
        best = max(candidates[:5], key=lambda c: title_similarity(q, c.get("name") or ""))
        if title_similarity(q, best.get("name") or "") < 0.48:
            return None

        appid = int(best["id"])
        det_r = await client.get(
            "https://store.steampowered.com/api/appdetails",
            params={"appids": str(appid), "l": "spanish"},
        )
        entry = (det_r.json() or {}).get(str(appid)) or {} if det_r.status_code == 200 else {}
        data = entry.get("data") if entry.get("success") else {}
        if not isinstance(data, dict):
            data = {}

        title = data.get("name") or best.get("name") or q
        raw_date = (data.get("release_date") or {}).get("date") or ""
        rel_date, precision, window_label = parse_steam_date(raw_date)
        genres = normalize_genres([g["description"] for g in (data.get("genres") or []) if g.get("description")])
        summary = html.unescape(data.get("short_description") or "").strip()
        urls = poster_urls(appid)
        return {
            "appid": appid,
            "title": title,
            "release_date": rel_date or "9999-12-31",
            "precision": precision,
            "window_label": window_label,
            "is_hot": 1,
            "genres": genres,
            "platforms": ["PC"],
            "summary": summary[:550],
            "_score": title_similarity(q, title),
            **urls,
        }
    except Exception:
        return None


async def search_nintendo_candidate(client: httpx.AsyncClient, q: str) -> dict | None:
    try:
        r = await client.get(
            "https://searching.nintendo-europe.com/es/select",
            params={"q": q, "fq": "type:GAME", "rows": 8, "wt": "json"},
        )
        if r.status_code != 200:
            return None
        docs = ((r.json() or {}).get("response") or {}).get("docs") or []
        parsed = parse_nintendo_solr_docs(docs, cutoff_iso="1990-01-01")
        if not parsed:
            return None
        best = max(
            parsed,
            key=lambda it: title_similarity(q, it["title"]) + (0.08 if "Switch 2" in it["platforms"] else 0.0),
        )
        score = title_similarity(q, best["title"])
        if score < 0.48:
            return None
        best["is_hot"] = 1
        best["_score"] = score
        return best
    except Exception:
        return None


async def search_wikipedia_candidate(q: str) -> dict | None:
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": WIKI_USER_AGENT},
            timeout=10.0,
            follow_redirects=True,
        ) as wc:
            sr = await wc.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": f"{q} video game",
                    "srlimit": 5,
                    "format": "json",
                },
            )
            if sr.status_code != 200:
                return None
            hits = ((sr.json() or {}).get("query") or {}).get("search") or []
            if not hits:
                return None

            def _clean_hit_title(t: str) -> str:
                return re.sub(r"\s*\([^)]*video game[^)]*\)\s*$", "", t, flags=re.IGNORECASE).strip()

            best_hit = max(hits, key=lambda h: title_similarity(q, _clean_hit_title(h.get("title") or "")))
            page_title = best_hit.get("title") or ""
            clean_title = _clean_hit_title(page_title)
            score = title_similarity(q, clean_title)
            if score < 0.48:
                return None

            pr = await wc.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "parse",
                    "page": page_title,
                    "prop": "text",
                    "section": 0,
                    "format": "json",
                },
            )
            platforms: list[str] = []
            genres: list[str] = []
            rel_date, precision, window_label = "9999-12-31", "tba", "Próximamente"
            if pr.status_code == 200 and "parse" in (pr.json() or {}):
                ib_html = ((pr.json()["parse"].get("text") or {}).get("*")) or ""
                ib_soup = BeautifulSoup(ib_html, "html.parser")
                infobox = ib_soup.select_one("table.infobox")
                if infobox:
                    for tr in infobox.select("tr"):
                        th = tr.find("th")
                        td = tr.find("td")
                        if not th or not td:
                            continue
                        lbl = th.get_text(" ", strip=True).lower()
                        val = clean_wiki_text(td.get_text(" ", strip=True))
                        if "platform" in lbl:
                            platforms = normalize_platforms(val)
                        elif "genre" in lbl:
                            genres = normalize_genres(val)
                        elif "release" in lbl:
                            rel_date, precision, window_label = parse_steam_date(val)

            item = {
                "appid": synthetic_game_id(clean_title),
                "title": clean_title,
                "release_date": rel_date or "9999-12-31",
                "precision": precision,
                "window_label": window_label,
                "is_hot": 1,
                "genres": genres,
                "platforms": platforms or ["PS5", "PC"],
                "poster_url": "",
                "header_url": "",
                "store_url": f"https://en.wikipedia.org/wiki/{page_title.replace(' ', '_')}",
                "summary": "",
                "_wiki_hint": page_title,
                "_score": score,
            }
            await enrich_wiki_artwork([item])
            return item
    except Exception:
        return None

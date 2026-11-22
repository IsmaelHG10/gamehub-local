"""Orquestador del calendario multi-plataforma estilo Releases.com (fusión, persistencia, favoritos y consultas)."""
from __future__ import annotations

import asyncio
import json
import time
from datetime import date, timedelta
from typing import Any

from .. import database, settings
from ..adapters.base import new_client
from .calendar_fetchers import (
    WIKI_ART_TTL,
    WIKI_USER_AGENT,
    enrich_wiki_artwork as _enrich_wiki_artwork,
    fetch_nintendo_events as _fetch_nintendo_events,
    fetch_playstation_events as _fetch_playstation_events,
    fetch_steam_batch as _fetch_steam_batch,
    fetch_wikipedia_events as _fetch_wikipedia_events,
    search_nintendo_candidate as _search_nintendo_candidate,
    search_steam_candidate as _search_steam_candidate,
    search_wikipedia_candidate as _search_wikipedia_candidate,
)
from .calendar_parsers import (  # noqa: F401 - re-exportados para compatibilidad
    GENRE_KEYWORD_MAP,
    HOT_FRANCHISE_KEYWORDS,
    MAJOR_PUBLISHERS_KEYWORDS,
    MONTH_MAP,
    PLATFORM_ORDER,
    PRECISION_RANK,
    SEASON_MAP,
    SLUG_TITLE_ALIASES,
    SPANISH_MONTHS,
    STEAM_TAG_MAP,
    canonical_calendar_key,
    clean_wiki_text as _clean_wiki_text,
    expand_wikitable_grid,
    is_notable_release as _is_notable_release,
    normalize_genres,
    normalize_platforms,
    parse_nintendo_solr_docs,
    parse_playstation_upcoming_html,
    parse_steam_date,
    parse_steam_search_html,
    parse_wikipedia_release_html,
    synthetic_game_id,
    title_similarity as _title_similarity,
)
from .steam_enricher import poster_urls

CALENDAR_TTL = 2 * 3600  # Refresco automático cada 2 horas
_sync_lock = asyncio.Lock()


# --------------------------------------------------------------------------- Fusión Multi-Plataforma y Persistencia

def _merge_two_items(base: dict, inc: dict) -> dict:
    """Unifica dos entradas del mismo juego procedentes de distintas plataformas/fuentes."""
    if base["appid"] < 0 and inc["appid"] > 0:
        base, inc = dict(inc), base
    else:
        base = dict(base)

    merged_plats = normalize_platforms([*(base.get("platforms") or []), *(inc.get("platforms") or [])])
    base["platforms"] = merged_plats or base.get("platforms") or ["PC"]

    r_base = PRECISION_RANK.get(base.get("precision") or "tba", 1)
    r_inc = PRECISION_RANK.get(inc.get("precision") or "tba", 1)
    if r_inc > r_base or (
        r_inc == r_base
        and (inc.get("release_date") or "9999-12-31") < (base.get("release_date") or "9999-12-31")
    ):
        base["release_date"] = inc["release_date"]
        base["precision"] = inc["precision"]
        base["window_label"] = inc["window_label"]

    base["is_hot"] = max(int(base.get("is_hot", 0)), int(inc.get("is_hot", 0)))
    genres = list(base.get("genres") or [])
    for g in inc.get("genres") or []:
        if g not in genres:
            genres.append(g)
    base["genres"] = genres[:5]

    if not base.get("poster_url") and inc.get("poster_url"):
        base["poster_url"] = inc["poster_url"]
    if not base.get("header_url") and inc.get("header_url"):
        base["header_url"] = inc["header_url"]
    if (not base.get("store_url") or "wikipedia.org/wiki/List_of" in base.get("store_url", "")) and inc.get("store_url"):
        base["store_url"] = inc["store_url"]
    if not base.get("summary") and inc.get("summary"):
        base["summary"] = inc["summary"]
    if not base.get("_wiki_hint") and inc.get("_wiki_hint"):
        base["_wiki_hint"] = inc["_wiki_hint"]

    return base


def merge_calendar_items(items: list[dict]) -> list[dict]:
    """Deduplica y fusiona juegos por AppID y por clave canónica de título/alias."""
    by_key: dict[str, dict] = {}
    alias_to_key: dict[str, str] = {}

    for raw_it in items:
        it = dict(raw_it)
        it["platforms"] = normalize_platforms(it.get("platforms") or ["PC"]) or ["PC"]
        t_key = canonical_calendar_key(it.get("title") or "")
        a_key = it.get("_alias_key") or ""
        if not t_key:
            t_key = f"id:{it['appid']}"

        canonical = alias_to_key.get(t_key) or (alias_to_key.get(a_key) if a_key else None) or t_key
        if canonical in by_key:
            by_key[canonical] = _merge_two_items(by_key[canonical], it)
        else:
            by_key[canonical] = it

        alias_to_key[t_key] = canonical
        if a_key:
            alias_to_key[a_key] = canonical

    by_appid: dict[int, dict] = {}
    for it in by_key.values():
        aid = int(it["appid"])
        if aid in by_appid:
            by_appid[aid] = _merge_two_items(by_appid[aid], it)
        else:
            by_appid[aid] = it

    return list(by_appid.values())


def _save_calendar_events(items: list[dict]) -> int:
    if not items:
        return 0
    now = time.time()
    merged_list = merge_calendar_items(items)

    rows = [
        (
            int(it["appid"]),
            it["title"],
            it.get("release_date") or "9999-12-31",
            it.get("precision") or "tba",
            it.get("window_label") or "Próximamente",
            int(it.get("is_hot", 0)),
            json.dumps(it.get("genres") or [], ensure_ascii=False),
            json.dumps(it.get("platforms") or ["PC"], ensure_ascii=False),
            it.get("poster_url") or "",
            it.get("header_url") or "",
            it.get("store_url") or "",
            it.get("summary") or "",
            now,
        )
        for it in merged_list
    ]

    stale_negative_ids = [
        synthetic_game_id(it["title"])
        for it in merged_list
        if int(it["appid"]) > 0
    ]

    with database.connect() as conn:
        if stale_negative_ids:
            for i in range(0, len(stale_negative_ids), 400):
                chunk = stale_negative_ids[i:i + 400]
                conn.execute(
                    f"DELETE FROM calendar_events WHERE appid IN ({','.join('?' * len(chunk))})",
                    chunk,
                )

        conn.executemany(
            """INSERT INTO calendar_events (
                   appid, title, release_date, precision, window_label, is_hot,
                   genres, platforms, poster_url, header_url, store_url, summary, updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(appid) DO UPDATE SET
                   title=excluded.title,
                   release_date=excluded.release_date,
                   precision=excluded.precision,
                   window_label=excluded.window_label,
                   is_hot=MAX(calendar_events.is_hot, excluded.is_hot),
                   genres=CASE WHEN excluded.genres != '[]' THEN excluded.genres ELSE calendar_events.genres END,
                   platforms=excluded.platforms,
                   poster_url=CASE WHEN excluded.poster_url != '' THEN excluded.poster_url ELSE calendar_events.poster_url END,
                   header_url=CASE WHEN excluded.header_url != '' THEN excluded.header_url ELSE calendar_events.header_url END,
                   store_url=CASE WHEN excluded.store_url != '' THEN excluded.store_url ELSE calendar_events.store_url END,
                   summary=CASE WHEN excluded.summary != '' THEN excluded.summary ELSE calendar_events.summary END,
                   updated_at=excluded.updated_at
            """,
            rows,
        )
        for fav_tbl in ("calendar_favorites", "user_calendar_favorites"):
            conn.execute(
                f"""UPDATE {fav_tbl}
                    SET release_date = (SELECT release_date FROM calendar_events WHERE calendar_events.appid = {fav_tbl}.appid),
                        precision    = (SELECT precision FROM calendar_events WHERE calendar_events.appid = {fav_tbl}.appid),
                        window_label = (SELECT window_label FROM calendar_events WHERE calendar_events.appid = {fav_tbl}.appid),
                        platforms    = (SELECT platforms FROM calendar_events WHERE calendar_events.appid = {fav_tbl}.appid),
                        poster_url   = CASE
                            WHEN (SELECT poster_url FROM calendar_events WHERE calendar_events.appid = {fav_tbl}.appid) != ''
                            THEN (SELECT poster_url FROM calendar_events WHERE calendar_events.appid = {fav_tbl}.appid)
                            ELSE {fav_tbl}.poster_url
                        END,
                        summary      = CASE
                            WHEN (SELECT summary FROM calendar_events WHERE calendar_events.appid = {fav_tbl}.appid) != ''
                            THEN (SELECT summary FROM calendar_events WHERE calendar_events.appid = {fav_tbl}.appid)
                            ELSE {fav_tbl}.summary
                        END
                    WHERE appid IN (SELECT appid FROM calendar_events)"""
            )
        conn.execute(
            "INSERT OR REPLACE INTO calendar_meta(key, value) VALUES ('last_sync', ?)",
            (now,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO calendar_meta(key, value) VALUES ('schema_version', 2)",
        )
    return len(rows)


def get_last_calendar_sync() -> float | None:
    with database.connect() as conn:
        row = conn.execute("SELECT value FROM calendar_meta WHERE key='last_sync'").fetchone()
    return float(row["value"]) if row else None


def _is_schema_current() -> bool:
    with database.connect() as conn:
        row = conn.execute("SELECT value FROM calendar_meta WHERE key='schema_version'").fetchone()
    return bool(row and float(row["value"]) >= 2.0)


async def sync_calendar(force: bool = False, full_enrich: bool = False) -> dict:
    async with _sync_lock:
        last = get_last_calendar_sync()
        if not force and last and (time.time() - last) < CALENDAR_TTL and _is_schema_current():
            with database.connect() as conn:
                cnt = conn.execute("SELECT COUNT(*) FROM calendar_events").fetchone()[0]
            if cnt > 0:
                return {"synced": False, "cached": True, "count": cnt, "last_sync": last}

        light_mode = settings.IS_SERVERLESS and not full_enrich
        sem = asyncio.Semaphore(5 if settings.IS_SERVERLESS else 4)
        net_timeout = 8.0 if light_mode else 14.0
        async with new_client(timeout=net_timeout) as client:
            if light_mode:
                tasks = [
                    _fetch_steam_batch(client, sem, 0, 100, is_hot=True, filter="popularcomingsoon"),
                    _fetch_steam_batch(client, sem, 100, 100, is_hot=True, filter="popularcomingsoon"),
                    _fetch_steam_batch(client, sem, 0, 100, is_hot=True, only_recent_days=60, filter="topsellers"),
                    _fetch_steam_batch(client, sem, 0, 100, is_hot=False, filter="comingsoon"),
                    _fetch_nintendo_events(client),
                    _fetch_playstation_events(client),
                    _fetch_wikipedia_events(),
                ]
            else:
                tasks = [
                    _fetch_steam_batch(client, sem, 0, 100, is_hot=True, filter="popularcomingsoon"),
                    _fetch_steam_batch(client, sem, 100, 100, is_hot=True, filter="popularcomingsoon"),
                    _fetch_steam_batch(client, sem, 200, 100, is_hot=True, filter="popularcomingsoon"),
                    _fetch_steam_batch(client, sem, 0, 100, is_hot=True, only_recent_days=60, filter="topsellers"),
                    _fetch_steam_batch(client, sem, 100, 100, is_hot=True, only_recent_days=60, filter="topsellers"),
                    _fetch_steam_batch(client, sem, 0, 100, is_hot=False, filter="comingsoon"),
                    _fetch_steam_batch(client, sem, 100, 100, is_hot=False, filter="comingsoon"),
                    _fetch_steam_batch(client, sem, 0, 100, is_hot=False, sort_by="Released_DESC"),
                    _fetch_steam_batch(client, sem, 100, 100, is_hot=False, sort_by="Released_DESC"),
                    _fetch_nintendo_events(client),
                    _fetch_playstation_events(client),
                    _fetch_wikipedia_events(),
                ]
            batches = await asyncio.gather(*tasks, return_exceptions=True)

        collected: list[dict] = []
        for b in batches:
            if isinstance(b, list):
                collected.extend(b)

        merged = merge_calendar_items(collected)
        try:
            if light_mode:
                await asyncio.wait_for(_enrich_wiki_artwork(merged[:120]), timeout=3.5)
            elif settings.IS_SERVERLESS:
                await asyncio.wait_for(_enrich_wiki_artwork(merged), timeout=14.0)
            else:
                await _enrich_wiki_artwork(merged)
        except Exception:
            pass

        saved = _save_calendar_events(merged)
        return {"synced": True, "cached": False, "count": saved, "last_sync": time.time()}


# --------------------------------------------------------------------------- Lectura, Favoritos y Seguimiento

def _row_to_cal_item(row, fav_ids: set[int]) -> dict:
    d = dict(row)
    for k in ("genres", "platforms"):
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except Exception:
            d[k] = []
    d["summary"] = d.get("summary") or ""
    d["is_hot"] = bool(d.get("is_hot", False))
    d["favorited"] = int(d["appid"]) in fav_ids
    return d


def favorite_ids(user_id: int | None = None) -> set[int]:
    with database.connect() as conn:
        if user_id and user_id > 0:
            rows = conn.execute(
                "SELECT appid FROM user_calendar_favorites WHERE user_id=?",
                (int(user_id),),
            ).fetchall()
        else:
            rows = conn.execute("SELECT appid FROM calendar_favorites").fetchall()
    return {int(r[0]) for r in rows}


def list_favorites(user_id: int | None = None) -> list[dict]:
    with database.connect() as conn:
        if user_id and user_id > 0:
            rows = conn.execute(
                "SELECT * FROM user_calendar_favorites WHERE user_id=? "
                "ORDER BY COALESCE(release_date, '9999-12-31') ASC, saved_at DESC",
                (int(user_id),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM calendar_favorites ORDER BY COALESCE(release_date, '9999-12-31') ASC, saved_at DESC"
            ).fetchall()
    favs = {int(r["appid"]) for r in rows}
    return [_row_to_cal_item(r, favs) for r in rows]


def toggle_favorite(item: dict, user_id: int | None = None) -> bool:
    raw_id = item.get("appid")
    if raw_id is None or raw_id == "":
        appid = synthetic_game_id(str(item.get("title") or "game"))
    else:
        appid = int(raw_id)

    default_urls = poster_urls(appid) if appid > 0 else {"poster_url": "", "header_url": "", "store_url": ""}
    common_vals = (
        str(item.get("title") or f"Juego {abs(appid)}"),
        item.get("release_date") or "9999-12-31",
        item.get("precision") or "tba",
        item.get("window_label") or "Próximamente",
        json.dumps(item.get("genres") or [], ensure_ascii=False),
        json.dumps(normalize_platforms(item.get("platforms") or ["PC"]) or ["PC"], ensure_ascii=False),
        item.get("poster_url") or default_urls["poster_url"],
        item.get("header_url") or default_urls["header_url"],
        item.get("store_url") or default_urls["store_url"],
        str(item.get("summary") or ""),
        time.time(),
    )

    with database.connect() as conn:
        if user_id and user_id > 0:
            uid = int(user_id)
            exists = conn.execute(
                "SELECT 1 FROM user_calendar_favorites WHERE user_id=? AND appid=?",
                (uid, appid),
            ).fetchone()
            if exists:
                conn.execute(
                    "DELETE FROM user_calendar_favorites WHERE user_id=? AND appid=?",
                    (uid, appid),
                )
                return False
            conn.execute(
                """INSERT INTO user_calendar_favorites (
                       user_id, appid, title, release_date, precision, window_label,
                       genres, platforms, poster_url, header_url, store_url, summary, saved_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (uid, appid, *common_vals),
            )
            return True

        exists = conn.execute("SELECT 1 FROM calendar_favorites WHERE appid=?", (appid,)).fetchone()
        if exists:
            conn.execute("DELETE FROM calendar_favorites WHERE appid=?", (appid,))
            return False

        conn.execute(
            """INSERT INTO calendar_favorites (
                   appid, title, release_date, precision, window_label,
                   genres, platforms, poster_url, header_url, store_url, summary, saved_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (appid, *common_vals),
        )
        return True


async def get_calendar_data(
    mode: str = "hot",
    platform: str | None = None,
    genre: str | None = None,
    q: str | None = None,
    force_refresh: bool = False,
    user_id: int | None = None,
) -> dict:
    if force_refresh or not settings.IS_SERVERLESS:
        await sync_calendar(force=force_refresh)
    else:
        with database.connect() as conn:
            existing_count = conn.execute("SELECT COUNT(*) FROM calendar_events").fetchone()[0]
        if existing_count == 0:
            await sync_calendar(force=False)

    last_sync = get_last_calendar_sync()
    is_stale = bool(not last_sync or (time.time() - last_sync) >= CALENDAR_TTL)

    fav_list = list_favorites(user_id=user_id)
    fav_set = {f["appid"] for f in fav_list}

    if mode == "favorites":
        base_items = fav_list
    else:
        where = []
        params: list[Any] = []
        if mode == "hot":
            where.append("is_hot = 1")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with database.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM calendar_events {clause} ORDER BY COALESCE(release_date,'9999-12-31') ASC, is_hot DESC, title ASC",
                params,
            ).fetchall()
        base_items = [_row_to_cal_item(r, fav_set) for r in rows]

    platform_counts: dict[str, int] = {}
    for it in base_items:
        for p in it.get("platforms") or []:
            platform_counts[p] = platform_counts.get(p, 0) + 1

    items = base_items
    if platform:
        items = [it for it in items if platform in (it.get("platforms") or [])]
    if genre:
        items = [it for it in items if genre in (it.get("genres") or [])]
    if q and q.strip():
        needle = q.strip().lower()
        items = [it for it in items if needle in it["title"].lower()]

    today_iso = date.today().isoformat()
    recent_cutoff = (date.today() - timedelta(days=5)).isoformat()
    soon_cutoff = (date.today() + timedelta(days=7)).isoformat()
    alerts = [
        f for f in fav_list
        if f.get("precision") == "day" and recent_cutoff <= (f.get("release_date") or "") <= today_iso
    ]
    upcoming_soon = [
        f for f in fav_list
        if f.get("precision") == "day" and today_iso < (f.get("release_date") or "") <= soon_cutoff
    ]

    all_genres = sorted({g for it in base_items for g in (it.get("genres") or [])})
    available_platforms = [p for p in PLATFORM_ORDER if platform_counts.get(p, 0) > 0]

    return {
        "mode": mode,
        "today": today_iso,
        "total": len(items),
        "favorites_count": len(fav_list),
        "alerts": alerts,
        "upcoming_soon": upcoming_soon,
        "available_genres": all_genres,
        "available_platforms": available_platforms,
        "platform_counts": platform_counts,
        "last_sync": last_sync,
        "is_stale": is_stale,
        "items": items,
    }


async def search_and_add_game_to_calendar(
    query: str,
    favorite: bool = True,
    user_id: int | None = None,
) -> dict:
    """Busca cualquier juego de PC, Nintendo Switch 2 o PS5 y lo añade al calendario."""
    q = (query or "").strip()
    if not q:
        raise ValueError("Escribe el nombre de un juego")

    q_canon = canonical_calendar_key(q)
    cur_favs = favorite_ids(user_id=user_id)
    with database.connect() as conn:
        rows = conn.execute("SELECT * FROM calendar_events").fetchall()
    existing_matches = [
        _row_to_cal_item(r, cur_favs)
        for r in rows
        if canonical_calendar_key(r["title"]) == q_canon
    ]
    if existing_matches:
        item = existing_matches[0]
        item["is_hot"] = 1
        _save_calendar_events([item])
        if favorite and item["appid"] not in cur_favs:
            toggle_favorite(item, user_id=user_id)
        item["favorited"] = item["appid"] in favorite_ids(user_id=user_id)
        return item

    async with new_client(timeout=10.0) as client:
        steam_res, nin_res, wiki_res = await asyncio.gather(
            _search_steam_candidate(client, q),
            _search_nintendo_candidate(client, q),
            _search_wikipedia_candidate(q),
        )

    valid = [c for c in (steam_res, nin_res, wiki_res) if isinstance(c, dict)]
    if not valid:
        raise ValueError(f"No se encontró «{q}» en Steam, Nintendo Switch 2 ni PS5")

    valid.sort(key=lambda x: x.get("_score", 0.0), reverse=True)
    primary = valid[0]
    primary_key = canonical_calendar_key(primary["title"])

    for extra in valid[1:]:
        if canonical_calendar_key(extra["title"]) == primary_key or _title_similarity(primary["title"], extra["title"]) >= 0.88:
            primary = _merge_two_items(primary, extra)

    primary.pop("_score", None)
    primary.pop("_wiki_hint", None)
    primary.pop("_alias_key", None)
    primary["is_hot"] = 1

    _save_calendar_events([primary])
    if favorite and int(primary["appid"]) not in favorite_ids(user_id=user_id):
        toggle_favorite(primary, user_id=user_id)
    primary["favorited"] = int(primary["appid"]) in favorite_ids(user_id=user_id)
    return primary

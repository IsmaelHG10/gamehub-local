"""Calendario de lanzamientos estilo Releases.com (modos Hot y Clásico + Seguimiento de Favoritos)."""
from __future__ import annotations

import asyncio
import html
import json
import re
import time
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .. import database
from ..adapters.base import new_client
from .steam_enricher import poster_urls

CALENDAR_TTL = 2 * 3600  # Refresco automático cada 2 horas
_sync_lock = asyncio.Lock()

# IDs universales de etiquetas en Steam -> Géneros en español
STEAM_TAG_MAP: dict[int, str] = {
    19: "Acción",
    21: "Aventura",
    122: "RPG",
    9: "Estrategia",
    599: "Simulación",
    492: "Indie",
    1667: "Terror",
    1662: "Supervivencia",
    1774: "Shooter",
    1663: "Shooter",
    1625: "Plataformas",
    3959: "Roguelike",
    1716: "Roguelike",
    701: "Deportes",
    699: "Carreras",
    1695: "Mundo Abierto",
    29482: "Soulslike",
    3859: "Multijugador",
    1685: "Cooperativo",
    1664: "Puzles",
    1742: "Narrativo",
    493: "Acceso Anticipado",
}

MONTH_MAP = {
    "jan": 1, "january": 1, "ene": 1, "enero": 1,
    "feb": 2, "february": 2, "febrero": 2,
    "mar": 3, "march": 3, "marzo": 3,
    "apr": 4, "april": 4, "abr": 4, "abril": 4,
    "may": 5, "mayo": 5,
    "jun": 6, "june": 6, "junio": 6,
    "jul": 7, "july": 7, "julio": 7,
    "aug": 8, "august": 8, "ago": 8, "agosto": 8,
    "sep": 9, "sept": 9, "september": 9, "septiembre": 9,
    "oct": 10, "october": 10, "octubre": 10,
    "nov": 11, "november": 11, "noviembre": 11,
    "dec": 12, "december": 12, "dic": 12, "diciembre": 12,
}

SPANISH_MONTHS = [
    "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def parse_steam_date(raw: str | None) -> tuple[str | None, str, str]:
    """Devuelve (fecha_ordenable, precision, etiqueta_es).

    precision: 'day' | 'month' | 'quarter' | 'year' | 'tba'
    """
    s = html.unescape(raw or "").strip()
    if not s:
        return None, "tba", "Próximamente"

    low = s.lower().strip(".")
    if any(k in low for k in ("coming soon", "to be announced", "tba", "tbd", "próximamente", "cuando esté")):
        return "9999-12-31", "tba", "Próximamente"

    # 1. ISO directo YYYY-MM-DD
    m_iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m_iso:
        y, mo, d = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        return f"{y:04d}-{mo:02d}-{d:02d}", "day", f"{d} {SPANISH_MONTHS[mo]} {y}"

    # 2. Formato "28 Oct, 2026" o "28 de octubre de 2026"
    m_dmy = re.match(r"^(\d{1,2})\s+(?:de\s+)?([A-Za-zÁÉÍÓÚáéíóú]+)\.?,?\s+(?:de\s+)?(\d{4})$", s)
    if m_dmy:
        d, m_name, y = int(m_dmy.group(1)), m_dmy.group(2).lower()[:4].rstrip("."), int(m_dmy.group(3))
        mo = MONTH_MAP.get(m_dmy.group(2).lower()) or MONTH_MAP.get(m_name[:3])
        if mo and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}", "day", f"{d} {SPANISH_MONTHS[mo]} {y}"

    # 3. Formato "Oct 28, 2026"
    m_mdy = re.match(r"^([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})$", s)
    if m_mdy:
        mo = MONTH_MAP.get(m_mdy.group(1).lower()) or MONTH_MAP.get(m_mdy.group(1).lower()[:3])
        d, y = int(m_mdy.group(2)), int(m_mdy.group(3))
        if mo and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}", "day", f"{d} {SPANISH_MONTHS[mo]} {y}"

    # 4. Trimestre "Q1 2027"
    m_q = re.match(r"^Q([1-4])\s+(\d{4})$", s, re.IGNORECASE)
    if m_q:
        q, y = int(m_q.group(1)), int(m_q.group(2))
        end_month = q * 3
        return f"{y:04d}-{end_month:02d}-99", "quarter", f"T{q} {y}"

    # 5. Mes + Año "November 2026" / "Nov 2026"
    m_my = re.match(r"^([A-Za-zÁÉÍÓÚáéíóú]+)\.?,?\s+(?:de\s+)?(\d{4})$", s)
    if m_my:
        mo = MONTH_MAP.get(m_my.group(1).lower()) or MONTH_MAP.get(m_my.group(1).lower()[:3])
        y = int(m_my.group(2))
        if mo:
            return f"{y:04d}-{mo:02d}-98", "month", f"{SPANISH_MONTHS[mo]} {y}"

    # 6. Solo año "2027"
    m_y = re.match(r"^((?:20)\d{2})$", s)
    if m_y:
        y = int(m_y.group(1))
        return f"{y:04d}-12-99", "year", str(y)

    return "9999-12-31", "tba", s


def parse_steam_search_html(results_html: str, is_hot: bool = False) -> list[dict]:
    soup = BeautifulSoup(results_html or "", "html.parser")
    parsed_items: list[dict] = []

    for row in soup.select("a.search_result_row"):
        raw_appid = (row.get("data-ds-appid") or "").split(",")[0].strip()
        if not raw_appid.isdigit():
            continue
        appid = int(raw_appid)
        title_el = row.select_one("span.title")
        if not title_el:
            continue
        title = html.unescape(title_el.get_text(" ", strip=True)).strip()
        if not title:
            continue

        rel_el = row.select_one("div.search_released")
        rel_raw = rel_el.get_text(" ", strip=True) if rel_el else ""
        rel_date, precision, window_label = parse_steam_date(rel_raw)

        genres: list[str] = []
        raw_tags = row.get("data-ds-tagids")
        if raw_tags:
            try:
                tag_ids = json.loads(raw_tags)
                for tid in tag_ids:
                    g = STEAM_TAG_MAP.get(int(tid))
                    if g and g not in genres:
                        genres.append(g)
            except Exception:
                pass

        platforms = []
        for p_cls, p_name in (("win", "PC"), ("mac", "Mac"), ("linux", "Linux")):
            if row.select_one(f"span.platform_img.{p_cls}"):
                platforms.append(p_name)
        if not platforms:
            platforms = ["PC"]

        urls = poster_urls(appid)
        parsed_items.append({
            "appid": appid,
            "title": title,
            "release_date": rel_date,
            "precision": precision,
            "window_label": window_label,
            "is_hot": 1 if is_hot else 0,
            "genres": genres[:5],
            "platforms": platforms,
            **urls,
        })
    return parsed_items


async def _fetch_steam_batch(
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
                "category1": 998,  # Solo juegos completos (excluye DLCs, demos y bandas sonoras)
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


def _save_calendar_events(items: list[dict]) -> int:
    if not items:
        return 0
    now = time.time()
    # Fusionar por appid conservando is_hot=1 si aparece tanto en Hot como en Clásico
    merged: dict[int, dict] = {}
    for it in items:
        aid = it["appid"]
        if aid in merged:
            merged[aid]["is_hot"] = max(merged[aid]["is_hot"], it["is_hot"])
            if not merged[aid]["genres"] and it["genres"]:
                merged[aid]["genres"] = it["genres"]
        else:
            merged[aid] = dict(it)

    rows = [
        (
            it["appid"],
            it["title"],
            it["release_date"],
            it["precision"],
            it["window_label"],
            it["is_hot"],
            json.dumps(it["genres"], ensure_ascii=False),
            json.dumps(it["platforms"], ensure_ascii=False),
            it["poster_url"],
            it["header_url"],
            it["store_url"],
            now,
        )
        for it in merged.values()
    ]
    with database.connect() as conn:
        conn.executemany(
            """INSERT INTO calendar_events (
                   appid, title, release_date, precision, window_label, is_hot,
                   genres, platforms, poster_url, header_url, store_url, updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(appid) DO UPDATE SET
                   title=excluded.title,
                   release_date=excluded.release_date,
                   precision=excluded.precision,
                   window_label=excluded.window_label,
                   is_hot=MAX(calendar_events.is_hot, excluded.is_hot),
                   genres=CASE WHEN excluded.genres != '[]' THEN excluded.genres ELSE calendar_events.genres END,
                   platforms=excluded.platforms,
                   updated_at=excluded.updated_at
            """,
            rows,
        )
        # Sincronizar fechas actualizadas también en los favoritos guardados si cambiaron
        conn.execute(
            """UPDATE calendar_favorites
               SET release_date = (SELECT release_date FROM calendar_events WHERE calendar_events.appid = calendar_favorites.appid),
                   precision    = (SELECT precision FROM calendar_events WHERE calendar_events.appid = calendar_favorites.appid),
                   window_label = (SELECT window_label FROM calendar_events WHERE calendar_events.appid = calendar_favorites.appid)
               WHERE appid IN (SELECT appid FROM calendar_events)"""
        )
        conn.execute(
            "INSERT OR REPLACE INTO calendar_meta(key, value) VALUES ('last_sync', ?)",
            (now,),
        )
    return len(rows)


def get_last_calendar_sync() -> float | None:
    with database.connect() as conn:
        row = conn.execute("SELECT value FROM calendar_meta WHERE key='last_sync'").fetchone()
    return float(row["value"]) if row else None


async def sync_calendar(force: bool = False) -> dict:
    async with _sync_lock:
        last = get_last_calendar_sync()
        if not force and last and (time.time() - last) < CALENDAR_TTL:
            with database.connect() as conn:
                cnt = conn.execute("SELECT COUNT(*) FROM calendar_events").fetchone()[0]
            if cnt > 0:
                return {"synced": False, "cached": True, "count": cnt, "last_sync": last}

        sem = asyncio.Semaphore(4)
        async with new_client(timeout=14.0) as client:
            tasks = [
                # Hot Calendar: próximos más deseados (300 juegos) + top ventas recientes (últimos 60 días)
                _fetch_steam_batch(client, sem, 0, 100, is_hot=True, filter="popularcomingsoon"),
                _fetch_steam_batch(client, sem, 100, 100, is_hot=True, filter="popularcomingsoon"),
                _fetch_steam_batch(client, sem, 200, 100, is_hot=True, filter="popularcomingsoon"),
                _fetch_steam_batch(client, sem, 0, 100, is_hot=True, only_recent_days=60, filter="topsellers"),
                _fetch_steam_batch(client, sem, 100, 100, is_hot=True, only_recent_days=60, filter="topsellers"),
                # Classic Calendar: todos los próximos día a día + lanzamientos recientes del mes
                _fetch_steam_batch(client, sem, 0, 100, is_hot=False, filter="comingsoon"),
                _fetch_steam_batch(client, sem, 100, 100, is_hot=False, filter="comingsoon"),
                _fetch_steam_batch(client, sem, 0, 100, is_hot=False, sort_by="Released_DESC"),
                _fetch_steam_batch(client, sem, 100, 100, is_hot=False, sort_by="Released_DESC"),
            ]
            batches = await asyncio.gather(*tasks, return_exceptions=True)

        collected: list[dict] = []
        for b in batches:
            if isinstance(b, list):
                collected.extend(b)

        saved = _save_calendar_events(collected)
        return {"synced": True, "cached": False, "count": saved, "last_sync": time.time()}


def _row_to_cal_item(row, fav_ids: set[int]) -> dict:
    d = dict(row)
    for k in ("genres", "platforms"):
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except Exception:
            d[k] = []
    d["is_hot"] = bool(d.get("is_hot", False))
    d["favorited"] = int(d["appid"]) in fav_ids
    return d


def favorite_ids() -> set[int]:
    with database.connect() as conn:
        rows = conn.execute("SELECT appid FROM calendar_favorites").fetchall()
    return {int(r[0]) for r in rows}


def list_favorites() -> list[dict]:
    with database.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM calendar_favorites ORDER BY COALESCE(release_date, '9999-12-31') ASC, saved_at DESC"
        ).fetchall()
    favs = {int(r["appid"]) for r in rows}
    return [_row_to_cal_item(r, favs) for r in rows]


def toggle_favorite(item: dict) -> bool:
    appid = int(item["appid"])
    with database.connect() as conn:
        exists = conn.execute("SELECT 1 FROM calendar_favorites WHERE appid=?", (appid,)).fetchone()
        if exists:
            conn.execute("DELETE FROM calendar_favorites WHERE appid=?", (appid,))
            return False
        urls = poster_urls(appid)
        conn.execute(
            """INSERT INTO calendar_favorites (
                   appid, title, release_date, precision, window_label,
                   genres, platforms, poster_url, header_url, store_url, saved_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                appid,
                str(item.get("title") or f"App {appid}"),
                item.get("release_date") or "9999-12-31",
                item.get("precision") or "tba",
                item.get("window_label") or "Próximamente",
                json.dumps(item.get("genres") or [], ensure_ascii=False),
                json.dumps(item.get("platforms") or ["PC"], ensure_ascii=False),
                item.get("poster_url") or urls["poster_url"],
                item.get("header_url") or urls["header_url"],
                item.get("store_url") or urls["store_url"],
                time.time(),
            ),
        )
        return True


async def get_calendar_data(
    mode: str = "hot",
    genre: str | None = None,
    q: str | None = None,
    force_refresh: bool = False,
) -> dict:
    # Garantiza que la caché tenga datos iniciales
    await sync_calendar(force=force_refresh)

    fav_list = list_favorites()
    fav_set = {f["appid"] for f in fav_list}

    if mode == "favorites":
        items = fav_list
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
        items = [_row_to_cal_item(r, fav_set) for r in rows]

    if genre:
        items = [it for it in items if genre in (it.get("genres") or [])]
    if q and q.strip():
        needle = q.strip().lower()
        items = [it for it in items if needle in it["title"].lower()]

    # Avisos de juegos seguidos que salen HOY o salieron en los últimos 5 días
    today_iso = date.today().isoformat()
    recent_cutoff = (date.today() - timedelta(days=5)).isoformat()
    alerts = [
        f for f in fav_list
        if f.get("precision") == "day" and recent_cutoff <= (f.get("release_date") or "") <= today_iso
    ]

    all_genres = sorted({g for it in items for g in (it.get("genres") or [])})
    return {
        "mode": mode,
        "today": today_iso,
        "total": len(items),
        "favorites_count": len(fav_list),
        "alerts": alerts,
        "available_genres": all_genres,
        "last_sync": get_last_calendar_sync(),
        "items": items,
    }


async def search_and_add_game_to_calendar(query: str, favorite: bool = True) -> dict:
    """Permite buscar cualquier juego de Steam (aunque falten años) y añadirlo al calendario."""
    q = (query or "").strip()
    if not q:
        raise ValueError("Escribe el nombre de un juego")

    async with new_client(timeout=10.0) as client:
        r = await client.get(
            "https://store.steampowered.com/api/storesearch/",
            params={"term": q, "l": "english", "cc": "ES"},
        )
        r.raise_for_status()
        candidates = (r.json() or {}).get("items") or []
        if not candidates:
            raise ValueError(f"No se encontró «{q}» en Steam")

        appid = int(candidates[0]["id"])
        det_r = await client.get(
            "https://store.steampowered.com/api/appdetails",
            params={"appids": str(appid), "l": "english"},
        )
        det_r.raise_for_status()
        entry = (det_r.json() or {}).get(str(appid)) or {}
        data = entry.get("data") if entry.get("success") else {}
        if not isinstance(data, dict):
            data = {}

        title = data.get("name") or candidates[0].get("name") or q
        raw_date = (data.get("release_date") or {}).get("date") or ""
        rel_date, precision, window_label = parse_steam_date(raw_date)
        genres = [g["description"] for g in (data.get("genres") or []) if g.get("description")][:4]
        urls = poster_urls(appid)

        item = {
            "appid": appid,
            "title": title,
            "release_date": rel_date,
            "precision": precision,
            "window_label": window_label,
            "is_hot": 1,
            "genres": genres,
            "platforms": ["PC"],
            **urls,
        }
        _save_calendar_events([item])
        if favorite:
            # Si ya era favorito no lo desmarcamos, nos aseguramos de que quede guardado
            if appid not in favorite_ids():
                toggle_favorite(item)
        item["favorited"] = appid in favorite_ids()
        return item

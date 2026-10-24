"""SQLite: caché de feeds, catálogo con índice FTS5 y caché de Steam."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import unicodedata
from contextlib import contextmanager
from typing import Iterable, Iterator

from . import settings

_init_lock = threading.Lock()
_initialized_paths: set[str] = set()

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS releases (
    rowid INTEGER PRIMARY KEY,
    id TEXT NOT NULL UNIQUE,
    source_id TEXT NOT NULL,
    source_name TEXT,
    source_category TEXT,
    raw_title TEXT NOT NULL,
    clean_title TEXT NOT NULL,
    published_at TEXT,
    page_url TEXT,
    file_size TEXT,
    uris TEXT NOT NULL DEFAULT '[]',
    excerpt TEXT,
    image_url TEXT,
    fetched_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_releases_source ON releases(source_id);
CREATE INDEX IF NOT EXISTS idx_releases_published ON releases(published_at DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS catalog_fts USING fts5(
    clean_title, raw_title,
    content='releases', content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS releases_ai AFTER INSERT ON releases BEGIN
    INSERT INTO catalog_fts(rowid, clean_title, raw_title)
    VALUES (new.rowid, new.clean_title, new.raw_title);
END;
CREATE TRIGGER IF NOT EXISTS releases_ad AFTER DELETE ON releases BEGIN
    INSERT INTO catalog_fts(catalog_fts, rowid, clean_title, raw_title)
    VALUES ('delete', old.rowid, old.clean_title, old.raw_title);
END;
CREATE TRIGGER IF NOT EXISTS releases_au AFTER UPDATE ON releases BEGIN
    INSERT INTO catalog_fts(catalog_fts, rowid, clean_title, raw_title)
    VALUES ('delete', old.rowid, old.clean_title, old.raw_title);
    INSERT INTO catalog_fts(rowid, clean_title, raw_title)
    VALUES (new.rowid, new.clean_title, new.raw_title);
END;

CREATE TABLE IF NOT EXISTS steam_cache (
    key TEXT PRIMARY KEY,
    data TEXT,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS steam_details (
    appid INTEGER PRIMARY KEY,
    data TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS source_sync (
    source_id TEXT PRIMARY KEY,
    last_sync REAL,
    item_count INTEGER,
    error TEXT,
    duration_ms INTEGER
);
CREATE TABLE IF NOT EXISTS bookmarks (
    item_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    saved_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS calendar_events (
    appid INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    release_date TEXT,
    precision TEXT NOT NULL DEFAULT 'tba',
    window_label TEXT,
    is_hot INTEGER NOT NULL DEFAULT 0,
    genres TEXT NOT NULL DEFAULT '[]',
    platforms TEXT NOT NULL DEFAULT '[]',
    poster_url TEXT,
    header_url TEXT,
    store_url TEXT,
    summary TEXT DEFAULT '',
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cal_date ON calendar_events(release_date);
CREATE INDEX IF NOT EXISTS idx_cal_hot ON calendar_events(is_hot);

CREATE TABLE IF NOT EXISTS calendar_favorites (
    appid INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    release_date TEXT,
    precision TEXT NOT NULL DEFAULT 'tba',
    window_label TEXT,
    genres TEXT NOT NULL DEFAULT '[]',
    platforms TEXT NOT NULL DEFAULT '[]',
    poster_url TEXT,
    header_url TEXT,
    store_url TEXT,
    summary TEXT DEFAULT '',
    saved_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS calendar_meta (
    key TEXT PRIMARY KEY,
    value REAL NOT NULL
);
"""


def _connect_raw() -> sqlite3.Connection:
    settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(settings.DB_PATH), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db() -> None:
    db_key = str(settings.DB_PATH.resolve())
    with _init_lock:
        if db_key in _initialized_paths:
            return
        conn = _connect_raw()
        try:
            conn.executescript(SCHEMA)
            for tbl in ("calendar_events", "calendar_favorites"):
                cols = {r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()}
                if "summary" not in cols:
                    conn.execute(f"ALTER TABLE {tbl} ADD COLUMN summary TEXT DEFAULT ''")
            conn.commit()
        finally:
            conn.close()
        _initialized_paths.add(db_key)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    init_db()
    conn = _connect_raw()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- releases

_COLUMNS = (
    "id", "source_id", "source_name", "source_category", "raw_title", "clean_title",
    "published_at", "page_url", "file_size", "uris", "excerpt", "image_url", "fetched_at",
)


def _row_values(item: dict, now: float) -> tuple:
    return (
        item["id"], item["source_id"], item.get("source_name"), item.get("source_category"),
        item["raw_title"], item["clean_title"], item.get("published_at"), item.get("page_url"),
        item.get("file_size"), json.dumps(item.get("uris") or [], ensure_ascii=False),
        item.get("excerpt"), item.get("image_url"), now,
    )


def upsert_items(items: Iterable[dict]) -> int:
    now = time.time()
    rows = [_row_values(i, now) for i in items]
    if not rows:
        return 0
    placeholders = ",".join("?" * len(_COLUMNS))
    updates = ",".join(f"{c}=excluded.{c}" for c in _COLUMNS if c != "id")
    with connect() as conn:
        conn.executemany(
            f"INSERT INTO releases ({','.join(_COLUMNS)}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}",
            rows,
        )
    return len(rows)


def replace_source_items(source_id: str, items: Iterable[dict]) -> int:
    """Sustituye por completo las entradas de una fuente (catálogos JSON)."""
    now = time.time()
    rows = [_row_values(i, now) for i in items]
    placeholders = ",".join("?" * len(_COLUMNS))
    with connect() as conn:
        conn.execute("DELETE FROM releases WHERE source_id=?", (source_id,))
        conn.executemany(
            # OR IGNORE (no REPLACE): REPLACE no dispara triggers de borrado y desincronizaría el FTS.
            f"INSERT OR IGNORE INTO releases ({','.join(_COLUMNS)}) VALUES ({placeholders})", rows
        )
    return len(rows)


def prune_source(source_id: str, keep: int) -> None:
    with connect() as conn:
        conn.execute(
            """DELETE FROM releases WHERE source_id=? AND rowid NOT IN (
                   SELECT rowid FROM releases WHERE source_id=?
                   ORDER BY COALESCE(published_at,'') DESC, fetched_at DESC LIMIT ?)""",
            (source_id, source_id, keep),
        )


def delete_source_items(source_id: str) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM releases WHERE source_id=?", (source_id,))
        conn.execute("DELETE FROM source_sync WHERE source_id=?", (source_id,))


def row_to_item(row: sqlite3.Row) -> dict:
    d = dict(row)
    d.pop("rowid", None)
    d.pop("fetched_at", None)
    d.pop("rank", None)
    try:
        d["uris"] = json.loads(d.get("uris") or "[]")
    except json.JSONDecodeError:
        d["uris"] = []
    return d


def query_latest(
    source_ids: list[str],
    category: str | None = None,
    magnet_only: bool = False,
    limit: int = 60,
    offset: int = 0,
) -> tuple[list[dict], int]:
    if not source_ids:
        return [], 0
    where = [f"source_id IN ({','.join('?' * len(source_ids))})"]
    params: list = list(source_ids)
    if category:
        where.append("source_category=?")
        params.append(category)
    if magnet_only:
        where.append("uris LIKE '%magnet:?xt=%'")
    clause = " AND ".join(where)
    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM releases WHERE {clause}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM releases WHERE {clause} "
            f"ORDER BY COALESCE(published_at,'') DESC, fetched_at DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return [row_to_item(r) for r in rows], total


_TOKEN_RE = re.compile(r"[\w']+", re.UNICODE)


def build_fts_query(text: str) -> str | None:
    """Convierte texto libre en una consulta FTS5 segura (AND de prefijos)."""
    tokens = [t.replace("'", "") for t in _TOKEN_RE.findall(text or "")]
    tokens = [t for t in tokens if t]
    if not tokens:
        return None
    return " ".join(f'"{t}"*' for t in tokens[:12])


def search_catalog(text: str, source_ids: list[str], limit: int = 150) -> list[dict]:
    fts = build_fts_query(text)
    if not fts or not source_ids:
        return []
    with connect() as conn:
        rows = conn.execute(
            f"""SELECT r.*, bm25(catalog_fts, 10.0, 1.0) AS rank
                FROM catalog_fts JOIN releases r ON r.rowid = catalog_fts.rowid
                WHERE catalog_fts MATCH ? AND r.source_id IN ({','.join('?' * len(source_ids))})
                ORDER BY rank LIMIT ?""",
            [fts, *source_ids, limit],
        ).fetchall()
    return [row_to_item(r) for r in rows]


def count_by_source() -> dict[str, int]:
    with connect() as conn:
        rows = conn.execute("SELECT source_id, COUNT(*) FROM releases GROUP BY source_id").fetchall()
    return {r[0]: r[1] for r in rows}


# --------------------------------------------------------------------------- sync status

def set_sync_status(source_id: str, count: int, error: str | None, duration_ms: int) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO source_sync(source_id, last_sync, item_count, error, duration_ms)
               VALUES (?,?,?,?,?)
               ON CONFLICT(source_id) DO UPDATE SET last_sync=excluded.last_sync,
                 item_count=excluded.item_count, error=excluded.error, duration_ms=excluded.duration_ms""",
            (source_id, time.time(), count, error, duration_ms),
        )


def get_sync_status() -> dict[str, dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM source_sync").fetchall()
    return {r["source_id"]: dict(r) for r in rows}


# --------------------------------------------------------------------------- steam cache

def normalize_key(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


_MISS = object()


def steam_cache_get(title: str):
    """Devuelve dict (hit), None (no existe en Steam, cacheado) o _MISS (sin datos)."""
    with connect() as conn:
        row = conn.execute(
            "SELECT data, expires_at FROM steam_cache WHERE key=?", (normalize_key(title),)
        ).fetchone()
    if not row or row["expires_at"] < time.time():
        return _MISS
    return json.loads(row["data"]) if row["data"] else None


def steam_cache_get_many(titles: Iterable[str]) -> dict[str, object]:
    keys = {t: normalize_key(t) for t in titles}
    if not keys:
        return {}
    uniq = list(set(keys.values()))
    found: dict[str, object] = {}
    now = time.time()
    with connect() as conn:
        for i in range(0, len(uniq), 500):
            chunk = uniq[i:i + 500]
            rows = conn.execute(
                f"SELECT key, data, expires_at FROM steam_cache WHERE key IN ({','.join('?' * len(chunk))})",
                chunk,
            ).fetchall()
            for r in rows:
                if r["expires_at"] >= now:
                    found[r["key"]] = json.loads(r["data"]) if r["data"] else None
    return {t: found.get(k, _MISS) for t, k in keys.items()}


def steam_cache_set(title: str, data: dict | None, ttl_seconds: float) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO steam_cache(key, data, expires_at) VALUES (?,?,?)",
            (normalize_key(title), json.dumps(data, ensure_ascii=False) if data else None,
             time.time() + ttl_seconds),
        )


def steam_details_get(appid: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT data, expires_at FROM steam_details WHERE appid=?", (appid,)
        ).fetchone()
    if not row or row["expires_at"] < time.time():
        return None
    return json.loads(row["data"])


def steam_details_set(appid: int, data: dict, ttl_seconds: float) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO steam_details(appid, data, expires_at) VALUES (?,?,?)",
            (appid, json.dumps(data, ensure_ascii=False), time.time() + ttl_seconds),
        )


# --------------------------------------------------------------------------- bookmarks / stats

def bookmark_list() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT item_id, payload, saved_at FROM bookmarks ORDER BY saved_at DESC"
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        try:
            item = json.loads(r["payload"])
            item["saved_at"] = r["saved_at"]
            item["bookmarked"] = True
            out.append(item)
        except json.JSONDecodeError:
            continue
    return out


def bookmark_ids() -> set[str]:
    with connect() as conn:
        rows = conn.execute("SELECT item_id FROM bookmarks").fetchall()
    return {r[0] for r in rows}


def bookmark_toggle(item: dict) -> bool:
    """Alterna un juego en Guardados. Devuelve True si queda guardado, False si se eliminó."""
    item_id = item["id"]
    with connect() as conn:
        exists = conn.execute("SELECT 1 FROM bookmarks WHERE item_id=?", (item_id,)).fetchone()
        if exists:
            conn.execute("DELETE FROM bookmarks WHERE item_id=?", (item_id,))
            return False
        conn.execute(
            "INSERT INTO bookmarks(item_id, payload, saved_at) VALUES (?,?,?)",
            (item_id, json.dumps(item, ensure_ascii=False), time.time()),
        )
        return True


def db_stats() -> dict:
    with connect() as conn:
        total_releases = conn.execute("SELECT COUNT(*) FROM releases").fetchone()[0]
        total_steam = conn.execute("SELECT COUNT(*) FROM steam_cache WHERE data IS NOT NULL").fetchone()[0]
        total_bookmarks = conn.execute("SELECT COUNT(*) FROM bookmarks").fetchone()[0]
        total_cal_favs = conn.execute("SELECT COUNT(*) FROM calendar_favorites").fetchone()[0]
    return {
        "total_releases": total_releases,
        "cached_steam_covers": total_steam,
        "bookmarks": total_bookmarks,
        "calendar_favorites": total_cal_favs,
    }


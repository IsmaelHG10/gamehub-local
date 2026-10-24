"""Calendario multi-plataforma estilo Releases.com (PC/Steam, Nintendo Switch 2, PS5, Switch y Xbox Series)."""
from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
import hashlib
import html
import json
import re
import time
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import unquote

import httpx
from bs4 import BeautifulSoup, Tag

from .. import database
from ..adapters.base import new_client
from .steam_enricher import poster_urls

CALENDAR_TTL = 2 * 3600  # Refresco automático cada 2 horas
WIKI_ART_TTL = 7 * 86400  # Caché de portadas/sinopsis de Wikipedia (7 días)
_sync_lock = asyncio.Lock()

WIKI_USER_AGENT = (
    "GameHubLocal/1.2 (https://github.com/IsmaelHG10/gamehub-local; local Windows release calendar) httpx/0.27"
)

PLATFORM_ORDER = [
    "PC",
    "Switch 2",
    "PS5",
    "Xbox Series",
    "Switch",
    "PS4",
    "Xbox One",
    "Mac",
    "Linux",
]

PRECISION_RANK = {
    "day": 5,
    "month": 4,
    "quarter": 3,
    "year": 2,
    "tba": 1,
}

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
    1743: "Lucha",
}

GENRE_KEYWORD_MAP: list[tuple[tuple[str, ...], str]] = [
    (("soulslike", "souls-like"), "Soulslike"),
    (("roguelike", "roguelite", "rougelike", "bullet heaven"), "Roguelike"),
    (("survival horror", "horror", "terror", "psych"), "Terror"),
    (("survival", "supervivencia"), "Supervivencia"),
    (("metroidvania", "platform", "plataformas"), "Plataformas"),
    (("fps", "tps", "shoot", "disparos", "hero shooter", "extraction shooter"), "Shooter"),
    (("action rpg", "rpg", "role-playing", "rol", "jrpg", "mmorpg", "dungeon crawl", "tactical rpg"), "RPG"),
    (("fighting", "lucha", "brawler", "beat 'em up", "hack and slash"), "Lucha"),
    (("racing", "carreras", "conducción", "driving"), "Carreras"),
    (("sports", "deportes", "football", "basketball", "golf", "tennis", "fitness"), "Deportes"),
    (("strategy", "estrategia", "4x", "rts", "turn-based", "tactics", "tower defense", "deck building"), "Estrategia"),
    (("simulation", "simulación", "sim", "cms", "city builder", "farming", "cozy"), "Simulación"),
    (("puzzle", "puzle", "puzles"), "Puzles"),
    (("visual novel", "interactive film", "graphic adventure", "narrativ"), "Narrativo"),
    (("open world", "mundo abierto", "sandbox"), "Mundo Abierto"),
    (("action-adventure", "action", "acción"), "Acción"),
    (("adventure", "aventura"), "Aventura"),
    (("multiplayer", "multijugador", "party", "battle royale"), "Multijugador"),
    (("co-op", "cooperativo"), "Cooperativo"),
    (("indie",), "Indie"),
]

MAJOR_PUBLISHERS_KEYWORDS = (
    "nintendo", "sony", "playstation", "rockstar", "take-two", "2k",
    "square enix", "capcom", "bandai namco", "sega", "atlus", "konami",
    "fromsoftware", "kojima", "ubisoft", "electronic arts", "ea sports",
    "xbox game studios", "microsoft", "bethesda", "id software", "arkane",
    "activision", "blizzard", "cd projekt", "koei tecmo", "omega force",
    "marvelous", "xseed", "warner bros", "devolver", "annapurna",
    "insomniac", "naughty dog", "sucker punch", "santa monica", "guerrilla",
    "housemarque", "bungie", "remedy", "io interactive", "larian",
    "focus entertainment", "thq nordic", "deep silver", "plaion",
    "krafton", "netease", "hoyoverse", "mihoyo", "level-5", "game freak",
    "pokemon", "pokémon", "spike chunsoft", "arc system works", "falcom",
    "nis america", "snk", "team ninja", "platinumgames", "bloober",
    "supermassive", "rebellion", "505 games", "paradox", "hooded horse",
    "pocketpair", "coffee stain", "team17", "klei", "supergiant",
)

HOT_FRANCHISE_KEYWORDS = (
    "mario", "zelda", "hyrule", "metroid", "donkey kong", "pokemon", "pokémon",
    "kirby", "xenoblade", "fire emblem", "splatoon", "animal crossing", "pikmin",
    "luigi", "yoshi", "smash bros", "duskbloods", "grand theft auto", "gta ",
    "resident evil", "monster hunter", "final fantasy", "dragon quest", "kingdom hearts",
    "persona", "shin megami", "metaphor", "like a dragon", "yakuza", "sonic",
    "silent hill", "metal gear", "castlevania", "pragmata", "onimusha", "okami",
    "marvel", "wolverine", "lobezno", "spider-man", "intergalactic", "ghost of",
    "death stranding", "god of war", "horizon", "gran turismo", "astro bot", "saros",
    "fable", "forza", "halo", "gears of war", "elder scrolls", "fallout", "doom",
    "blade", "witcher", "cyberpunk", "007", "james bond", "tomb raider", "judas",
    "bioshock", "borderlands", "civilization", "mafia", "subnautica", "hades",
    "hollow knight", "silksong", "elden ring", "dark souls", "armored core",
    "phantom blade", "tides of annihilation", "crimson desert", "inazuma",
    "professor layton", "rhythm heaven", "tomodachi", "octopath", "danganronpa",
    "ace combat", "tekken", "street fighter", "mortal kombat", "guilty gear",
    "star wars", "alien: isolation", "wolf among us", "alan wake", "control",
    "max payne", "hitman", "little nightmares", "lords of the fallen", "lies of p",
    "mass effect", "dragon age", "skate", "battlefield", "call of duty", "assassins creed",
    "assassin's creed", "far cry", "splinter cell", "prince of persia", "rayman",
    "enter the gungeon", "slay the spire", "deltarune", "persona 4", "exodus",
)

# Alias conocidos ES <-> EN para unificar fichas de tiendas regionales
SLUG_TITLE_ALIASES: dict[str, str] = {
    "marvel lobezno": "marvel s wolverine",
    "marvels wolverine": "marvel s wolverine",
    "gta 6": "grand theft auto vi",
    "gta vi": "grand theft auto vi",
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

SEASON_MAP: dict[str, tuple[int, str]] = {
    "winter": (3, "Invierno"),
    "invierno": (3, "Invierno"),
    "early": (3, "Principios de"),
    "principios": (3, "Principios de"),
    "spring": (6, "Primavera"),
    "primavera": (6, "Primavera"),
    "mid": (6, "Mediados de"),
    "summer": (9, "Verano"),
    "verano": (9, "Verano"),
    "fall": (11, "Otoño"),
    "autumn": (11, "Otoño"),
    "otoño": (11, "Otoño"),
    "late": (12, "Finales de"),
    "finales": (12, "Finales de"),
    "holiday": (12, "Navidades"),
}

_CITATION_RE = re.compile(r"\[\s*(?:\d+|[a-zA-Z]|‡\s*\d+|note\s*\d+)\s*\]")
_REGION_SUFFIX_RE = re.compile(
    r"\s*\((?:(?:WW|JP|NA|EU|PAL|AS|CN|KR|INT)(?:\s*[/,]\s*(?:WW|JP|NA|EU|PAL|AS|CN|KR|INT))*|early access)\)\s*$",
    re.IGNORECASE,
)
_EDITION_CLEAN_RE = re.compile(
    r"\s*(?:[-–—:]\s*)?(?:"
    r"nintendo\s+switch\s*™?\s*2\s+edition|"
    r"edici[oó]n\s+(?:deluxe|definitiva|est[aá]ndar|coleccionista|ultimate|gold|digital)|"
    r"(?:deluxe|ultimate|definitive|complete|collector'?s|standard|gold|goty|remastered)\s+edition|"
    r"director'?s\s+cut"
    r")\s*$",
    re.IGNORECASE,
)


def canonical_calendar_key(title: str) -> str:
    """Clave normalizada para fusionar un mismo juego entre Steam, Switch 2, PS5 y Wikipedia."""
    s = html.unescape(title or "")
    s = _CITATION_RE.sub("", s)
    s = s.replace("™", "").replace("®", "").replace("©", "")
    s = _REGION_SUFFIX_RE.sub("", s)
    s = _EDITION_CLEAN_RE.sub("", s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return SLUG_TITLE_ALIASES.get(s, s)


def synthetic_game_id(title: str) -> int:
    """Genera un identificador entero negativo estable para exclusivos de consola sin AppID de Steam."""
    key = canonical_calendar_key(title) or (title or "game").lower().strip()
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=4).digest()
    val = int.from_bytes(digest, "big") & 0x7FFFFFFF
    return -(val or 1)


def normalize_platforms(raw_platforms: list[str] | str) -> list[str]:
    if isinstance(raw_platforms, str):
        tokens = re.split(r"[,;|]+|\s{2,}", raw_platforms)
    else:
        tokens = list(raw_platforms or [])

    found: set[str] = set()
    for tok in tokens:
        t = _CITATION_RE.sub("", str(tok or "")).strip().lower()
        if not t:
            continue
        if t in ("ns2", "switch 2", "nintendo switch 2") or "switch 2" in t or "nintendoswitch2" in t:
            found.add("Switch 2")
        elif t in ("ps5", "playstation 5", "psvr", "psvr2", "playstation vr2"):
            found.add("PS5")
        elif t in ("win", "windows", "pc", "steam"):
            found.add("PC")
        elif t in (
            "xbx/s", "xsx/s", "xbx", "xsx", "xbox series",
            "xbox series x/s", "xbox series x|s", "xbox series x",
        ) or "xbox series" in t:
            found.add("Xbox Series")
        elif t in ("ns", "switch", "nintendo switch") or t.startswith("nintendoswitch"):
            found.add("Switch")
        elif t in ("ps4", "playstation 4"):
            found.add("PS4")
        elif t in ("xbo", "xbox one"):
            found.add("Xbox One")
        elif t in ("osx", "mac", "macos"):
            found.add("Mac")
        elif t in ("lin", "linux", "steamos"):
            found.add("Linux")

    return [p for p in PLATFORM_ORDER if p in found]


def normalize_genres(raw_genres: list[str] | str) -> list[str]:
    if isinstance(raw_genres, str):
        parts = re.split(r"[,;/]+", raw_genres)
    else:
        parts = list(raw_genres or [])

    result: list[str] = []
    for part in parts:
        clean = _CITATION_RE.sub("", str(part or "")).strip()
        if not clean:
            continue
        low = clean.lower()
        # Si ya coincide exactamente con uno de nuestros géneros en español
        matched = None
        for kws, target in GENRE_KEYWORD_MAP:
            if any(kw in low for kw in kws):
                matched = target
                break
        if matched and matched not in result:
            result.append(matched)
        elif not matched and clean in STEAM_TAG_MAP.values() and clean not in result:
            result.append(clean)
    return result[:5]


def _clean_wiki_text(raw: str) -> str:
    s = html.unescape(raw or "")
    s = _CITATION_RE.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_steam_date(raw: str | None, default_year: int | None = None) -> tuple[str | None, str, str]:
    """Devuelve (fecha_ordenable, precision, etiqueta_es).

    precision: 'day' | 'month' | 'quarter' | 'year' | 'tba'
    Soporta formatos de Steam, Nintendo eShop España (DD-MM-YYYY), Wikipedia y ventanas estacionales.
    """
    s = _clean_wiki_text(raw or "")
    if not s:
        if default_year:
            return f"{default_year:04d}-12-99", "year", str(default_year)
        return None, "tba", "Próximamente"

    # Si contiene múltiples fechas regionales (ej. "JP: July 2 WW: October 15"), priorizar WW / EU / NA
    if ":" in s and any(r in s for r in ("WW", "EU", "NA", "PAL", "JP")):
        m_reg = re.search(r"(?:WW|EU|PAL|NA)\s*:\s*([A-Za-z]+\s+\d{1,2}(?:,\s*\d{4})?)", s)
        if m_reg:
            s = m_reg.group(1).strip()
        else:
            m_any = re.search(r":\s*([A-Za-z]+\s+\d{1,2}(?:,\s*\d{4})?)", s)
            if m_any:
                s = m_any.group(1).strip()

    low = s.lower().strip(".")
    if any(
        k in low
        for k in (
            "coming soon", "to be announced", "tba", "tbd", "próximamente",
            "por determinar", "cuando esté", "unknown", "sin confirmar",
        )
    ):
        if default_year:
            return f"{default_year:04d}-12-99", "year", str(default_year)
        return "9999-12-31", "tba", "Próximamente"

    # 1. ISO directo YYYY-MM-DD (o timestamp ISO)
    m_iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:T.*)?$", s)
    if m_iso:
        y, mo, d = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        if y >= 2049:
            return "9999-12-31", "tba", "Próximamente"
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}", "day", f"{d} {SPANISH_MONTHS[mo]} {y}"

    # 1b. Europeo DD-MM-YYYY o DD/MM/YYYY (Nintendo eShop España)
    m_eur = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$", s)
    if m_eur:
        d, mo, y = int(m_eur.group(1)), int(m_eur.group(2)), int(m_eur.group(3))
        if y >= 2049:
            return "9999-12-31", "tba", "Próximamente"
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}", "day", f"{d} {SPANISH_MONTHS[mo]} {y}"

    # 2. Formato "28 Oct, 2026" o "28 de octubre de 2026"
    m_dmy = re.match(r"^(\d{1,2})\s+(?:de\s+)?([A-Za-zÁÉÍÓÚáéíóú]+)\.?,?\s+(?:de\s+)?(\d{4})$", s)
    if m_dmy:
        d, m_name, y = int(m_dmy.group(1)), m_dmy.group(2).lower()[:4].rstrip("."), int(m_dmy.group(3))
        mo = MONTH_MAP.get(m_dmy.group(2).lower()) or MONTH_MAP.get(m_name[:3])
        if mo and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}", "day", f"{d} {SPANISH_MONTHS[mo]} {y}"

    # 3. Formato "Oct 28, 2026" o sin año "October 28" (usando default_year)
    m_mdy = re.match(r"^([A-Za-z]+)\.?\s+(\d{1,2})(?:[–-](\d{1,2}))?(?:,?\s+(\d{4}))?$", s)
    if m_mdy:
        mo = MONTH_MAP.get(m_mdy.group(1).lower()) or MONTH_MAP.get(m_mdy.group(1).lower()[:3])
        d = int(m_mdy.group(2))
        y = int(m_mdy.group(4)) if m_mdy.group(4) else default_year
        if mo and y and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}", "day", f"{d} {SPANISH_MONTHS[mo]} {y}"

    # 4. Trimestre "Q1 2027", "Q1/Q2 2027" o "Q4" con default_year
    m_q = re.match(r"^Q([1-4])(?:/Q([1-4]))?(?:\s+(\d{4}))?$", s, re.IGNORECASE)
    if m_q:
        q1 = int(m_q.group(1))
        q2 = int(m_q.group(2)) if m_q.group(2) else None
        y = int(m_q.group(3)) if m_q.group(3) else default_year
        if y:
            end_month = (q2 or q1) * 3
            label = f"T{q1}/T{q2} {y}" if q2 else f"T{q1} {y}"
            return f"{y:04d}-{end_month:02d}-99", "quarter", label

    # 4b. Estaciones / tramos ("Fall 2026", "Early 2027", "Spring")
    m_season = re.match(r"^([A-Za-zÁÉÍÓÚáéíóúñÑ]+)(?:\s+de)?(?:\s+(\d{4}))?$", s)
    if m_season:
        w = m_season.group(1).lower()
        y = int(m_season.group(2)) if m_season.group(2) else default_year
        if w in SEASON_MAP and y:
            end_m, es_lbl = SEASON_MAP[w]
            return f"{y:04d}-{end_m:02d}-99", "quarter", f"{es_lbl} {y}"

    # 5. Mes + Año "November 2026" o solo Mes "November" con default_year
    m_my = re.match(r"^([A-Za-zÁÉÍÓÚáéíóú]+)\.?(?:,?\s+(?:de\s+)?(\d{4}))?$", s)
    if m_my:
        mo = MONTH_MAP.get(m_my.group(1).lower()) or MONTH_MAP.get(m_my.group(1).lower()[:3])
        y = int(m_my.group(2)) if m_my.group(2) else default_year
        if mo and y:
            return f"{y:04d}-{mo:02d}-98", "month", f"{SPANISH_MONTHS[mo]} {y}"

    # 6. Solo año "2027"
    m_y = re.match(r"^((?:20)\d{2})$", s)
    if m_y:
        y = int(m_y.group(1))
        return f"{y:04d}-12-99", "year", str(y)

    if default_year and re.search(r"\b20\d{2}\b", s) is None:
        return f"{default_year:04d}-12-99", "year", f"{s} ({default_year})"
    return "9999-12-31", "tba", s


def _is_notable_release(title: str, publisher_or_dev: str = "", has_wiki_article: bool = False) -> bool:
    t_low = (title or "").lower()
    p_low = (publisher_or_dev or "").lower()
    if any(k in t_low for k in HOT_FRANCHISE_KEYWORDS):
        return True
    if any(p in p_low for p in MAJOR_PUBLISHERS_KEYWORDS):
        return True
    if has_wiki_article:
        return True
    return False


# --------------------------------------------------------------------------- 1. Fuente PC: Steam Store

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
            "summary": "",
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


# --------------------------------------------------------------------------- 2. Fuente Oficial Nintendo Switch 2 & Switch (Nintendo eShop Europa)

def parse_nintendo_solr_docs(docs: list[dict], cutoff_iso: str) -> list[dict]:
    items: list[dict] = []
    for d in docs or []:
        title = (d.get("title") or "").strip()
        if not title:
            continue
        # Ignorar paquetes puramente de mejora de idioma o pases menores si los hubiera
        low_title = title.lower()
        if any(skip in low_title for skip in ("paquete de mejora", "upgrade pack", "idioma ", "voice pack")):
            continue

        sys_names = d.get("system_names_txt") or []
        sys_types = d.get("system_type") or []
        platforms = normalize_platforms([*sys_names, *sys_types])
        if not platforms:
            platforms = ["Switch 2"]

        raw_dates = d.get("dates_released_dts") or []
        pretty_date = (d.get("pretty_date_s") or "").strip()
        iso_first = str(raw_dates[0])[:10] if raw_dates else ""

        if iso_first.startswith("2050") or "determinar" in pretty_date.lower():
            rel_date, precision, window_label = "9999-12-31", "tba", "Próximamente"
        elif pretty_date:
            rel_date, precision, window_label = parse_steam_date(pretty_date)
        else:
            rel_date, precision, window_label = parse_steam_date(iso_first)

        if not rel_date:
            rel_date, precision, window_label = "9999-12-31", "tba", "Próximamente"

        # Mantener lanzamientos futuros, ventanas estimadas o recientes desde cutoff_iso
        if precision == "day" and rel_date < cutoff_iso:
            continue

        cats = d.get("pretty_game_categories_txt") or d.get("game_categories_txt") or []
        genres = normalize_genres(cats)
        publisher = str(d.get("publisher") or "")
        is_hot = 1 if ("Switch 2" in platforms and _is_notable_release(title, publisher)) or _is_notable_release(title, publisher) else 0

        sq_img = (
            d.get("image_url_sq_s")
            or d.get("wishlist_email_square_image_url_s")
            or d.get("image_url")
            or ""
        )
        banner_img = (
            d.get("image_url_h2x1_s")
            or d.get("image_url_h16x9_s")
            or d.get("wishlist_email_banner640w_image_url_s")
            or sq_img
        )
        raw_url = str(d.get("url") or "")
        store_url = f"https://www.nintendo.com{raw_url}" if raw_url.startswith("/") else (raw_url or "https://www.nintendo.com/es-es/")
        summary = (d.get("excerpt") or d.get("product_catalog_description_s") or "").strip()

        items.append({
            "appid": synthetic_game_id(title),
            "title": title,
            "release_date": rel_date,
            "precision": precision,
            "window_label": window_label,
            "is_hot": is_hot,
            "genres": genres,
            "platforms": platforms,
            "poster_url": sq_img,
            "header_url": banner_img,
            "store_url": store_url,
            "summary": summary[:600],
            "_wiki_hint": _EDITION_CLEAN_RE.sub("", title).strip(),
        })
    return items


async def _fetch_nintendo_events(client: httpx.AsyncClient) -> list[dict]:
    cutoff_iso = (date.today() - timedelta(days=50)).isoformat()
    today_iso = date.today().isoformat()
    out: list[dict] = []

    queries = [
        # Todos los próximos y recientes de Nintendo Switch 2 (incluye 2050 = TBA, 2027 y finales de 2026)
        {
            "q": "*",
            "fq": "type:GAME AND system_type:nintendoswitch2*",
            "sort": "dates_released_dts desc",
            "rows": 180,
            "wt": "json",
        },
        # Próximos fechados de Nintendo Switch 1
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


# --------------------------------------------------------------------------- 3. Fuente Oficial PlayStation 5 (PlayStation España)

def parse_playstation_upcoming_html(page_html: str) -> list[dict]:
    soup = BeautifulSoup(page_html or "", "html.parser")
    items: list[dict] = []
    seen_slugs: set[str] = set()

    def _slug_to_english_hint(slug: str) -> str:
        clean_slug = slug.strip("/").split("/")[-1]
        words = [w for w in clean_slug.split("-") if w]
        return " ".join(words).title()

    # 1) Mosaicos de "Más juegos para PS5 disponibles próximamente" (incluyen packshot oficial 1200px)
    for tile in soup.select("a.game-grid-v2-tile[href*='/games/']"):
        href = (tile.get("href") or "").strip()
        if "/games/" not in href:
            continue
        # Comprobar que no pertenezca a una sección de "ya disponibles"
        sec_heading = ""
        sec = tile.find_parent("section")
        if sec:
            h_el = sec.select_one("h2, h3")
            sec_heading = (h_el.get_text(" ", strip=True) if h_el else "").lower()
        if "ya disponibles" in sec_heading or "éxitos de ps4" in sec_heading:
            continue

        slug = href.rstrip("/").split("/games/")[-1].split("/")[0].lower()
        if not slug or slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        title = tile.get_text(" ", strip=True)
        if not title:
            continue

        img_url = ""
        for im in tile.select("img, source"):
            cand = (im.get("src") or im.get("data-src") or im.get("srcset") or "").split()[0].strip()
            if cand.startswith("http"):
                img_url = cand
                break

        store_url = f"https://www.playstation.com{href}" if href.startswith("/") else href
        items.append({
            "appid": synthetic_game_id(_slug_to_english_hint(slug) if slug in ("marvels-wolverine",) else title),
            "title": title,
            "release_date": "9999-12-31",
            "precision": "tba",
            "window_label": "Próximamente",
            "is_hot": 1,
            "genres": [],
            "platforms": ["PS5"],
            "poster_url": img_url,
            "header_url": img_url,
            "store_url": store_url,
            "summary": "",
            "_alias_key": canonical_calendar_key(slug.replace("-", " ")),
            "_wiki_hint": _slug_to_english_hint(slug),
        })

    # 2) Bloques destacados de próximos lanzamientos / reservas en PS5 (con sinopsis en español)
    for a in soup.select("a[href*='/es-es/games/'], a[href*='/games/']"):
        href = (a.get("href") or "").strip()
        if "/games/" not in href or "ps5/games" in href:
            continue
        slug = href.rstrip("/").split("/games/")[-1].split("/")[0].lower()
        if not slug or slug in seen_slugs:
            continue

        # Verificar que el botón o sección sea de reserva / lista de deseos / héroe próximo
        cta_txt = a.get_text(" ", strip=True).lower()
        sec = a.find_parent("section")
        sec_h = ""
        if sec:
            h2 = sec.select_one("h2")
            sec_h = (h2.get_text(" ", strip=True) if h2 else "").lower()

        is_upcoming_cta = any(k in cta_txt for k in ("reserva", "lista de deseos", "más información"))
        is_already_out_sec = any(
            k in sec_h
            for k in (
                "ya disponibles", "éxitos de ps4", "mayores producciones",
                "descubre más", "playstation vr2", "resumen definitivo",
            )
        )
        if is_already_out_sec or not is_upcoming_cta:
            continue
        # Si dice "más información", solo aceptarlo si está en los héroes iniciales (antes de "ya disponibles") o en "próximos"
        if "más información" in cta_txt and sec_h and "próxim" not in sec_h and "reserva" not in sec_h:
            continue

        box = a.find_parent("div", class_="box") or a.find_parent("div", class_="txt-block-paragraph")
        if not box:
            continue
        h_title = box.select_one("h2, h3, h4")
        title = _clean_wiki_text(h_title.get_text(" ", strip=True)) if h_title else _slug_to_english_hint(slug)
        if not title or len(title) > 90:
            continue

        p_desc = box.select_one("p")
        summary = _clean_wiki_text(p_desc.get_text(" ", strip=True)) if p_desc else ""
        if summary.lower() == title.lower():
            summary = ""

        img_url = ""
        for im in box.select("img, source"):
            cand = (im.get("src") or im.get("data-src") or im.get("srcset") or "").split()[0].strip()
            if cand.startswith("http") and "icon" not in cand.lower():
                img_url = cand
                break

        seen_slugs.add(slug)
        store_url = f"https://www.playstation.com{href}" if href.startswith("/") else href
        alias_key = canonical_calendar_key(slug.replace("-", " "))
        items.append({
            "appid": synthetic_game_id(alias_key or title),
            "title": title,
            "release_date": "9999-12-31",
            "precision": "tba",
            "window_label": "Próximamente",
            "is_hot": 1,
            "genres": [],
            "platforms": ["PS5"],
            "poster_url": img_url,
            "header_url": img_url,
            "store_url": store_url,
            "summary": summary[:600],
            "_alias_key": alias_key,
            "_wiki_hint": _slug_to_english_hint(slug),
        })

    return items


async def _fetch_playstation_events(client: httpx.AsyncClient) -> list[dict]:
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


# --------------------------------------------------------------------------- 4. Calendario Editorial Multi-Plataforma (Wikipedia 2026 & 2027 + Box Art)

def expand_wikitable_grid(table: Tag) -> list[list[Tag]]:
    """Expande rowspan y colspan de una tabla HTML en una matriz rectangular de celdas."""
    rows = table.find_all("tr", recursive=False)
    if not rows:
        tbody = table.find("tbody", recursive=False)
        if tbody:
            rows = tbody.find_all("tr", recursive=False)
    grid: list[list[Tag | None]] = []
    for r_idx, tr in enumerate(rows):
        while len(grid) <= r_idx:
            grid.append([])
        row_list = grid[r_idx]
        c_idx = 0
        for cell in tr.find_all(["th", "td"], recursive=False):
            while c_idx < len(row_list) and row_list[c_idx] is not None:
                c_idx += 1
            try:
                rs = max(1, int(cell.get("rowspan", 1)))
            except ValueError:
                rs = 1
            try:
                cs = max(1, int(cell.get("colspan", 1)))
            except ValueError:
                cs = 1
            for dr in range(rs):
                target_r = r_idx + dr
                while len(grid) <= target_r:
                    grid.append([])
                t_row = grid[target_r]
                while len(t_row) < c_idx + cs:
                    t_row.append(None)
                for dc in range(cs):
                    t_row[c_idx + dc] = cell
            c_idx += cs
    return [[c for c in r if c is not None] for r in grid if any(c is not None for c in r)]


def parse_wikipedia_release_html(html_text: str, year: int, cutoff_iso: str) -> list[dict]:
    soup = BeautifulSoup(html_text or "", "html.parser")
    items: list[dict] = []

    for tbl in soup.select("table.wikitable"):
        grid = expand_wikitable_grid(tbl)
        if len(grid) < 2:
            continue

        headers = [_clean_wiki_text(c.get_text(" ", strip=True)).lower() for c in grid[0]]
        if not any("title" in h for h in headers) or not any("platform" in h for h in headers):
            continue
        # Ignorar tablas de juegos cancelados o cierres de servidores
        if any("cancelled" in h or "shutdown" in h or "discontinued" in h for h in headers):
            continue

        idx_title = next((i for i, h in enumerate(headers) if "title" in h), -1)
        idx_plat = next((i for i, h in enumerate(headers) if "platform" in h), -1)
        idx_date = next((i for i, h in enumerate(headers) if "date" in h or "release" in h), -1)
        idx_genre = next((i for i, h in enumerate(headers) if "genre" in h), -1)
        idx_type = next((i for i, h in enumerate(headers) if "type" in h), -1)
        idx_dev = next((i for i, h in enumerate(headers) if "developer" in h), -1)
        idx_pub = next((i for i, h in enumerate(headers) if "publisher" in h), -1)

        if idx_title < 0 or idx_plat < 0 or idx_date < 0:
            continue

        for row in grid[1:]:
            if max(idx_title, idx_plat, idx_date) >= len(row):
                continue

            if idx_type >= 0 and idx_type < len(row):
                t_val = _clean_wiki_text(row[idx_type].get_text(" ", strip=True)).lower()
                if "cancelled" in t_val:
                    continue

            title_cell = row[idx_title]
            raw_title = _clean_wiki_text(title_cell.get_text(" ", strip=True))
            title = _REGION_SUFFIX_RE.sub("", raw_title).strip()
            if not title or title.lower() == "title":
                continue

            plat_raw = _clean_wiki_text(row[idx_plat].get_text(" ", strip=True))
            platforms = normalize_platforms(plat_raw)
            if not platforms:
                continue  # Excluye lanzamientos exclusivamente móviles (iOS/Android)

            date_raw = _clean_wiki_text(row[idx_date].get_text(" ", strip=True))
            rel_date, precision, window_label = parse_steam_date(date_raw, default_year=year)
            if not rel_date:
                continue
            if precision == "day" and rel_date < cutoff_iso:
                continue

            genres_raw = _clean_wiki_text(row[idx_genre].get_text(" ", strip=True)) if 0 <= idx_genre < len(row) else ""
            genres = normalize_genres(genres_raw)

            dev_txt = _clean_wiki_text(row[idx_dev].get_text(" ", strip=True)) if 0 <= idx_dev < len(row) else ""
            pub_txt = _clean_wiki_text(row[idx_pub].get_text(" ", strip=True)) if 0 <= idx_pub < len(row) else ""

            # Enlace directo al artículo de Wikipedia si existe (sin clase 'new')
            wiki_link = title_cell.select_one("i a[href^='/wiki/']:not(.new), a[href^='/wiki/']:not(.new)")
            wiki_article = ""
            store_url = f"https://en.wikipedia.org/wiki/List_of_video_games_released_in_{year}"
            if wiki_link and wiki_link.get("href"):
                href = wiki_link["href"]
                wiki_article = unquote(href.split("/wiki/")[-1].split("#")[0]).replace("_", " ")
                store_url = f"https://en.wikipedia.org{href}"

            is_hot = 1 if _is_notable_release(title, f"{dev_txt} {pub_txt}", has_wiki_article=bool(wiki_article)) else 0

            items.append({
                "appid": synthetic_game_id(title),
                "title": title,
                "release_date": rel_date,
                "precision": precision,
                "window_label": window_label,
                "is_hot": is_hot,
                "genres": genres,
                "platforms": platforms,
                "poster_url": "",
                "header_url": "",
                "store_url": store_url,
                "summary": "",
                "_wiki_hint": wiki_article or title,
            })

    return items


async def _fetch_wikipedia_events() -> list[dict]:
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


async def _enrich_wiki_artwork(items: list[dict]) -> None:
    """Obtiene portadas oficiales (pilicense=any) y sinopsis desde Wikipedia en lotes de 50 títulos."""
    candidates: list[dict] = [
        it for it in items
        if it.get("appid", 0) < 0 and (not it.get("poster_url") or not it.get("summary") or "1x1_" in (it.get("poster_url") or ""))
    ]
    if not candidates:
        return

    # Priorizar juegos Hot y consolas principales para enriquecer hasta 200 títulos en ~4 peticiones
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

                # Reconstruir mapa de redirecciones/normalizaciones de MediaWiki
                norm_map: dict[str, str] = {}
                for n in qdata.get("normalized") or []:
                    norm_map[n["from"]] = n["to"]
                redir_map: dict[str, str] = {}
                for rd in qdata.get("redirects") or []:
                    redir_map[rd["from"]] = rd["to"]

                pages_by_title: dict[str, dict] = {}
                for p in (qdata.get("pages") or {}).values():
                    if isinstance(p, dict) and p.get("title") and "missing" not in p:
                        pages_by_title[p["title"]] = p

                for orig_hint in chunk:
                    step1 = norm_map.get(orig_hint, orig_hint)
                    final_title = redir_map.get(step1, step1)
                    p = pages_by_title.get(final_title)
                    if not p:
                        # Fallback insensible a mayúsculas
                        p = next((v for k, v in pages_by_title.items() if k.lower() == final_title.lower()), None)

                    ckey = f"wiki_art:{orig_hint}"
                    if not p:
                        database.steam_cache_set(ckey, None, WIKI_ART_TTL)
                        continue

                    thumb = ((p.get("thumbnail") or {}).get("source") or (p.get("original") or {}).get("source") or "").strip()
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


# --------------------------------------------------------------------------- Fusión Multi-Plataforma y Persistencia SQLite

def _merge_two_items(base: dict, inc: dict) -> dict:
    """Unifica dos entradas del mismo juego procedentes de distintas plataformas/fuentes."""
    # 1. Priorizar siempre AppID positivo de Steam si existe en cualquiera de los dos
    if base["appid"] < 0 and inc["appid"] > 0:
        base, inc = dict(inc), base
    else:
        base = dict(base)

    # 2. Unión ordenada de plataformas
    merged_plats = normalize_platforms([*(base.get("platforms") or []), *(inc.get("platforms") or [])])
    base["platforms"] = merged_plats or base.get("platforms") or ["PC"]

    # 3. Conservar la fecha con mayor precisión (ej. día exacto > mes > trimestre > año > TBA)
    r_base = PRECISION_RANK.get(base.get("precision") or "tba", 1)
    r_inc = PRECISION_RANK.get(inc.get("precision") or "tba", 1)
    if r_inc > r_base or (
        r_inc == r_base
        and (inc.get("release_date") or "9999-12-31") < (base.get("release_date") or "9999-12-31")
    ):
        base["release_date"] = inc["release_date"]
        base["precision"] = inc["precision"]
        base["window_label"] = inc["window_label"]

    # 4. Hot y Géneros
    base["is_hot"] = max(int(base.get("is_hot", 0)), int(inc.get("is_hot", 0)))
    genres = list(base.get("genres") or [])
    for g in inc.get("genres") or []:
        if g not in genres:
            genres.append(g)
    base["genres"] = genres[:5]

    # 5. Portadas, enlaces y sinopsis
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

    # Segunda pasada por si dos entradas comparten el mismo appid numérico
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

    # Si un juego con AppID positivo de Steam tenía antes un ID sintético negativo, limpiarlo
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
        # Sincronizar fechas, plataformas y portadas actualizadas en los favoritos guardados (locales y por cuenta)
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


async def sync_calendar(force: bool = False) -> dict:
    async with _sync_lock:
        last = get_last_calendar_sync()
        if not force and last and (time.time() - last) < CALENDAR_TTL and _is_schema_current():
            with database.connect() as conn:
                cnt = conn.execute("SELECT COUNT(*) FROM calendar_events").fetchone()[0]
            if cnt > 0:
                return {"synced": False, "cached": True, "count": cnt, "last_sync": last}

        sem = asyncio.Semaphore(4)
        async with new_client(timeout=14.0) as client:
            tasks = [
                # 1) Steam PC: Hot + Clásico
                _fetch_steam_batch(client, sem, 0, 100, is_hot=True, filter="popularcomingsoon"),
                _fetch_steam_batch(client, sem, 100, 100, is_hot=True, filter="popularcomingsoon"),
                _fetch_steam_batch(client, sem, 200, 100, is_hot=True, filter="popularcomingsoon"),
                _fetch_steam_batch(client, sem, 0, 100, is_hot=True, only_recent_days=60, filter="topsellers"),
                _fetch_steam_batch(client, sem, 100, 100, is_hot=True, only_recent_days=60, filter="topsellers"),
                _fetch_steam_batch(client, sem, 0, 100, is_hot=False, filter="comingsoon"),
                _fetch_steam_batch(client, sem, 100, 100, is_hot=False, filter="comingsoon"),
                _fetch_steam_batch(client, sem, 0, 100, is_hot=False, sort_by="Released_DESC"),
                _fetch_steam_batch(client, sem, 100, 100, is_hot=False, sort_by="Released_DESC"),
                # 2) Nintendo Switch 2 & Switch (Nintendo eShop Oficial España)
                _fetch_nintendo_events(client),
                # 3) PlayStation 5 (PlayStation España Oficial)
                _fetch_playstation_events(client),
                # 4) Calendario Editorial Multi-Plataforma 2026-2027 (PC, Switch 2, PS5, Xbox Series, Switch)
                _fetch_wikipedia_events(),
            ]
            batches = await asyncio.gather(*tasks, return_exceptions=True)

        collected: list[dict] = []
        for b in batches:
            if isinstance(b, list):
                collected.extend(b)

        merged = merge_calendar_items(collected)
        try:
            await _enrich_wiki_artwork(merged)
        except Exception:
            pass

        saved = _save_calendar_events(merged)
        return {"synced": True, "cached": False, "count": saved, "last_sync": time.time()}


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
    await sync_calendar(force=force_refresh)

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

    # Contadores por plataforma sobre el modo actual antes de filtrar plataforma
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

    # Avisos de juegos seguidos que salen HOY o salieron en los últimos 5 días
    today_iso = date.today().isoformat()
    recent_cutoff = (date.today() - timedelta(days=5)).isoformat()
    alerts = [
        f for f in fav_list
        if f.get("precision") == "day" and recent_cutoff <= (f.get("release_date") or "") <= today_iso
    ]

    all_genres = sorted({g for it in base_items for g in (it.get("genres") or [])})
    available_platforms = [p for p in PLATFORM_ORDER if platform_counts.get(p, 0) > 0]

    return {
        "mode": mode,
        "today": today_iso,
        "total": len(items),
        "favorites_count": len(fav_list),
        "alerts": alerts,
        "available_genres": all_genres,
        "available_platforms": available_platforms,
        "platform_counts": platform_counts,
        "last_sync": get_last_calendar_sync(),
        "items": items,
    }


def _title_similarity(query: str, candidate: str) -> float:
    qn = canonical_calendar_key(query)
    cn = canonical_calendar_key(candidate)
    if not qn or not cn:
        return 0.0
    if qn == cn:
        return 1.0
    ratio = SequenceMatcher(None, qn, cn).ratio()
    if qn in cn or cn in qn:
        ratio = max(ratio, 0.86)
    return ratio


async def _search_steam_candidate(client: httpx.AsyncClient, q: str) -> dict | None:
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
        best = max(candidates[:5], key=lambda c: _title_similarity(q, c.get("name") or ""))
        if _title_similarity(q, best.get("name") or "") < 0.48:
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
            "_score": _title_similarity(q, title),
            **urls,
        }
    except Exception:
        return None


async def _search_nintendo_candidate(client: httpx.AsyncClient, q: str) -> dict | None:
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
        best = max(parsed, key=lambda it: _title_similarity(q, it["title"]) + (0.08 if "Switch 2" in it["platforms"] else 0.0))
        score = _title_similarity(q, best["title"])
        if score < 0.48:
            return None
        best["is_hot"] = 1
        best["_score"] = score
        return best
    except Exception:
        return None


async def _search_wikipedia_candidate(q: str) -> dict | None:
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

            best_hit = max(hits, key=lambda h: _title_similarity(q, _clean_hit_title(h.get("title") or "")))
            page_title = best_hit.get("title") or ""
            clean_title = _clean_hit_title(page_title)
            score = _title_similarity(q, clean_title)
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
                        val = _clean_wiki_text(td.get_text(" ", strip=True))
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
            await _enrich_wiki_artwork([item])
            return item
    except Exception:
        return None


async def search_and_add_game_to_calendar(
    query: str,
    favorite: bool = True,
    user_id: int | None = None,
) -> dict:
    """Busca cualquier juego de PC, Nintendo Switch 2 o PS5 y lo añade al calendario."""
    q = (query or "").strip()
    if not q:
        raise ValueError("Escribe el nombre de un juego")

    # 1) Si ya existe una coincidencia exacta en nuestra base multi-plataforma local, usarla al instante
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

    # 2) Consultar en paralelo Steam (PC) + Nintendo eShop (Switch 2 / Switch) + Wikipedia (PS5 / Xbox / Exclusivos)
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

    # Fusionar plataformas/fechas si varios catálogos devolvieron el mismo juego
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

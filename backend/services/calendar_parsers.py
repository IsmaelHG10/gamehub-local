"""Parsers puros y normalización del calendario multi-plataforma (Steam, Nintendo eShop, PS5 y Wikipedia)."""
from __future__ import annotations

from difflib import SequenceMatcher
import hashlib
import html
import json
import re
import unicodedata
from urllib.parse import unquote

from bs4 import BeautifulSoup, Tag

from .steam_enricher import poster_urls

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


def clean_wiki_text(raw: str) -> str:
    s = html.unescape(raw or "")
    s = _CITATION_RE.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def title_similarity(query: str, candidate: str) -> float:
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


def parse_steam_date(raw: str | None, default_year: int | None = None) -> tuple[str | None, str, str]:
    """Devuelve (fecha_ordenable, precision, etiqueta_es).

    precision: 'day' | 'month' | 'quarter' | 'year' | 'tba'
    Soporta formatos de Steam, Nintendo eShop España (DD-MM-YYYY), Wikipedia y ventanas estacionales.
    """
    s = clean_wiki_text(raw or "")
    if not s:
        if default_year:
            return f"{default_year:04d}-12-99", "year", str(default_year)
        return None, "tba", "Próximamente"

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


def is_notable_release(title: str, publisher_or_dev: str = "", has_wiki_article: bool = False) -> bool:
    t_low = (title or "").lower()
    p_low = (publisher_or_dev or "").lower()
    if any(k in t_low for k in HOT_FRANCHISE_KEYWORDS):
        return True
    if any(p in p_low for p in MAJOR_PUBLISHERS_KEYWORDS):
        return True
    if has_wiki_article:
        return True
    return False


# --------------------------------------------------------------------------- Steam HTML

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


# --------------------------------------------------------------------------- Nintendo eShop Solr

def parse_nintendo_solr_docs(docs: list[dict], cutoff_iso: str) -> list[dict]:
    items: list[dict] = []
    for d in docs or []:
        title = (d.get("title") or "").strip()
        if not title:
            continue
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

        if precision == "day" and rel_date < cutoff_iso:
            continue

        cats = d.get("pretty_game_categories_txt") or d.get("game_categories_txt") or []
        genres = normalize_genres(cats)
        publisher = str(d.get("publisher") or "")
        is_hot = 1 if is_notable_release(title, publisher) else 0

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
        store_url = (
            f"https://www.nintendo.com{raw_url}"
            if raw_url.startswith("/")
            else (raw_url or "https://www.nintendo.com/es-es/")
        )
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


# --------------------------------------------------------------------------- PlayStation 5 HTML

def parse_playstation_upcoming_html(page_html: str) -> list[dict]:
    soup = BeautifulSoup(page_html or "", "html.parser")
    items: list[dict] = []
    seen_slugs: set[str] = set()

    def _slug_to_english_hint(slug: str) -> str:
        clean_slug = slug.strip("/").split("/")[-1]
        words = [w for w in clean_slug.split("-") if w]
        return " ".join(words).title()

    for tile in soup.select("a.game-grid-v2-tile[href*='/games/']"):
        href = (tile.get("href") or "").strip()
        if "/games/" not in href:
            continue
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

    for a in soup.select("a[href*='/es-es/games/'], a[href*='/games/']"):
        href = (a.get("href") or "").strip()
        if "/games/" not in href or "ps5/games" in href:
            continue
        slug = href.rstrip("/").split("/games/")[-1].split("/")[0].lower()
        if not slug or slug in seen_slugs:
            continue

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
        if "más información" in cta_txt and sec_h and "próxim" not in sec_h and "reserva" not in sec_h:
            continue

        box = a.find_parent("div", class_="box") or a.find_parent("div", class_="txt-block-paragraph")
        if not box:
            continue
        h_title = box.select_one("h2, h3, h4")
        title = clean_wiki_text(h_title.get_text(" ", strip=True)) if h_title else _slug_to_english_hint(slug)
        if not title or len(title) > 90:
            continue

        p_desc = box.select_one("p")
        summary = clean_wiki_text(p_desc.get_text(" ", strip=True)) if p_desc else ""
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


# --------------------------------------------------------------------------- Wikipedia Wikitables

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

        headers = [clean_wiki_text(c.get_text(" ", strip=True)).lower() for c in grid[0]]
        if not any("title" in h for h in headers) or not any("platform" in h for h in headers):
            continue
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

            if 0 <= idx_type < len(row):
                t_val = clean_wiki_text(row[idx_type].get_text(" ", strip=True)).lower()
                if "cancelled" in t_val:
                    continue

            title_cell = row[idx_title]
            raw_title = clean_wiki_text(title_cell.get_text(" ", strip=True))
            title = _REGION_SUFFIX_RE.sub("", raw_title).strip()
            if not title or title.lower() == "title":
                continue

            plat_raw = clean_wiki_text(row[idx_plat].get_text(" ", strip=True))
            platforms = normalize_platforms(plat_raw)
            if not platforms:
                continue

            date_raw = clean_wiki_text(row[idx_date].get_text(" ", strip=True))
            rel_date, precision, window_label = parse_steam_date(date_raw, default_year=year)
            if not rel_date:
                continue
            if precision == "day" and rel_date < cutoff_iso:
                continue

            genres_raw = clean_wiki_text(row[idx_genre].get_text(" ", strip=True)) if 0 <= idx_genre < len(row) else ""
            genres = normalize_genres(genres_raw)

            dev_txt = clean_wiki_text(row[idx_dev].get_text(" ", strip=True)) if 0 <= idx_dev < len(row) else ""
            pub_txt = clean_wiki_text(row[idx_pub].get_text(" ", strip=True)) if 0 <= idx_pub < len(row) else ""

            wiki_link = title_cell.select_one("i a[href^='/wiki/']:not(.new), a[href^='/wiki/']:not(.new)")
            wiki_article = ""
            store_url = f"https://en.wikipedia.org/wiki/List_of_video_games_released_in_{year}"
            if wiki_link and wiki_link.get("href"):
                href = wiki_link["href"]
                wiki_article = unquote(href.split("/wiki/")[-1].split("#")[0]).replace("_", " ")
                store_url = f"https://en.wikipedia.org{href}"

            is_hot = 1 if is_notable_release(title, f"{dev_txt} {pub_txt}", has_wiki_article=bool(wiki_article)) else 0

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

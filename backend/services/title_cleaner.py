"""Normalizador de títulos de releases.

Convierte títulos ruidosos como
    "Cyberpunk 2077: Ultimate Edition (v2.12 + All DLCs, MULTi18) [Repack] - 64.2 GB"
en un nombre limpio apto para buscar en Steam:
    "Cyberpunk 2077: Ultimate Edition"
"""
from __future__ import annotations

import html
import re

# Palabras que delatan que un paréntesis contiene información técnica, no parte del nombre.
_TECH_PAREN = re.compile(
    r"(?:\bv\s?\d|\bbuild\b|\bdlcs?\b|\bmulti\s?\d*\b|\brepack|\bportable\b|\bfix\b|\bhotfix|"
    r"\bupdate|\bupd\b|\bcrack|\blanguages?\b|\beng(?:lish)?\b|\bspanish\b|\bespa[ñn]ol\b|\brus\b|"
    r"\b\d+(?:[.,]\d+)?\s*(?:gb|mb|gib|mib)\b|\b(?:19|20)\d{2}\b|\bbonus|\bost\b|\bsoundtrack|"
    r"\bx64\b|\bx86\b|\bwin(?:dows)?\b|\bearly access\b|\bgog\b|\bsteam\s?rip|\bpre-?installed|"
    r"\bfitgirl|\bdodi\b|\belamigos|\bkaos|\bmechanics|\bonline[- ]fix|\bmultiplayer\b|\bdirect\b)",
    re.IGNORECASE,
)

# Etiquetas sueltas (repackers, grupos scene, formatos) que se eliminan en cualquier posición.
_TAGS = [
    r"Free\s+Download", r"Direct\s+Download", r"Torrent\s+Download", r"Download\s+Free",
    r"FitGirl(?:\s+Repacks?)?", r"DODI(?:\s+Repacks?)?", r"ElAmigos", r"KaOs\s?Krew", r"R\.?\s?G\.?\s+Mechanics",
    r"R\.?\s?G\.?\s+Catalyst", r"CPG(?:\s+Repacks?)?", r"Xatab", r"Repacks?", r"Portable", r"ISO",
    r"GOG(?:\s+Rip)?", r"Steam\s?Rip", r"Pre-?Installed", r"MULTi\s?\d+", r"x64", r"x86",
    r"Early\s+Access", r"Online[- ]Fix", r"P2P",
]
_TAG_RE = re.compile(r"(?<![\w'])(?:" + "|".join(_TAGS) + r")(?![\w'])", re.IGNORECASE)

# Grupos scene: solo se quitan como sufijo ("Juego-RUNE", "Juego - CODEX") para no romper títulos como "Rune II".
_SCENE_GROUPS = [
    "CODEX", "PLAZA", "SKIDROW", "EMPRESS", "TENOKE", "RUNE", "FLT", "TiNYiSO", "DARKSiDERS",
    "RAZOR1911", "GoldBerg", "I_KnoW", "DOGE", "HOODLUM", "CPY", "ANOMALY", "SiMPLEX",
]
_SCENE_SUFFIX_RE = re.compile(r"\s*[-.]\s*(?:" + "|".join(_SCENE_GROUPS) + r")\s*$", re.IGNORECASE)

_SIZE_RE = re.compile(r"[-–—|,~]?\s*\b\d+(?:[.,]\d+)?\s*(?:GB|MB|GiB|MiB)\b", re.IGNORECASE)
_VERSION_RE = re.compile(
    r"(?<![\w])(?:v|ver\.?\s?|version\s)\d+(?:[.\-_]\d+)*[a-z]?(?![\w])", re.IGNORECASE
)
_BUILD_RE = re.compile(r"(?<![\w])(?:build|update|upd|patch|hotfix)\s?#?\d+(?:[.\-_]\d+)*(?![\w])", re.IGNORECASE)
_PLUS_TAIL_RE = re.compile(
    r"\s\+\s*(?:\d+\s*)?(?:all\s+|bonus\s+|full\s+)?(?:dlcs?|expansions?|add-?ons?|bonus|ost|"
    r"soundtracks?|artbooks?|updates?|hotfix|fix|crack|online|multiplayer|co-?op|trainers?|"
    r"packs?|pre-?order|content|items?|weapons?|skins?|costumes?|windows\s*\d+).*$",
    re.IGNORECASE,
)
_BRACKETS_RE = re.compile(r"\[[^\]]*\]|\{[^}]*\}|【[^】]*】")
_PAREN_RE = re.compile(r"\(([^()]*)\)")
_SCENE_GROUP_RE = re.compile(r"-[A-Za-z0-9_]{2,15}$")
_STORE_PREFIX_RE = re.compile(
    r"^(?:now available on steam|new on steam|daily deal|weekend deal|midweek madness)\s*[-–—:]\s*",
    re.IGNORECASE,
)
_PROMO_SUFFIX_RE = re.compile(
    r"(?:,\s*\d+%\s*off!?|\s+(?:is\s+)?free\s+(?:to\s+keep\s+)?(?:on|at|via)\s+.*)$",
    re.IGNORECASE,
)
_EDGE_JUNK = " \t-–—|:,.+_/~"


def _strip_tech_parens(text: str) -> str:
    prev = None
    while prev != text:
        prev = text
        text = _PAREN_RE.sub(lambda m: " " if (not m.group(1).strip() or _TECH_PAREN.search(m.group(1))) else m.group(0), text)
    return text


def _scene_to_spaces(text: str) -> str:
    """'Hollow.Knight.v1.5.78-GOG' -> 'Hollow Knight'"""
    if " " in text.strip() or (text.count(".") + text.count("_")) < 2:
        return text
    text = _SCENE_GROUP_RE.sub("", text)
    text = re.sub(r"[._](?:v|build[._]?)\d+(?:[._]\d+)*.*$", "", text, flags=re.IGNORECASE)
    return text.replace(".", " ").replace("_", " ")


def clean_game_title(raw_title: str) -> str:
    if not raw_title:
        return ""
    original = html.unescape(raw_title).replace("\u00a0", " ").strip()
    text = _STORE_PREFIX_RE.sub("", original)
    text = _PROMO_SUFFIX_RE.sub("", text)
    text = _scene_to_spaces(text)
    text = _BRACKETS_RE.sub(" ", text)
    text = _strip_tech_parens(text)
    text = _SIZE_RE.sub(" ", text)
    text = _SCENE_SUFFIX_RE.sub(" ", text)
    text = _VERSION_RE.sub(" ", text)
    text = _BUILD_RE.sub(" ", text)
    text = _PLUS_TAIL_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = _strip_tech_parens(text)
    text = re.sub(r"\(\s*\)", " ", text)
    text = re.sub(r"\s+", " ", text)
    # Separadores que quedan colgando en medio ("Juego – – Edición") o al final.
    text = re.sub(r"\s+[-–—|]\s+(?:[-–—|]\s+)+", " – ", text)
    text = text.strip(_EDGE_JUNK).strip()
    # Paréntesis/corchetes desparejados residuales.
    if text.count("(") != text.count(")"):
        text = text.replace("(", "").replace(")", "").strip(_EDGE_JUNK)
    return text or original.strip()


def group_key(clean_title: str) -> str:
    """Clave para agrupar subidas del mismo juego con distintas ediciones."""
    from ..database import normalize_key  # import diferido para evitar ciclos

    key = normalize_key(clean_title)
    key = re.sub(
        r"\b(?:the\s+)?(?:digital\s+)?(?:ultimate|deluxe|complete|definitive|premium|gold|standard|"
        r"goty|game of the year|enhanced|collector s|anniversary|special|director s cut|super deluxe)"
        r"(?:\s+edition)?\b|\bedition\b",
        " ",
        key,
    )
    return re.sub(r"\s+", " ", key).strip() or normalize_key(clean_title)

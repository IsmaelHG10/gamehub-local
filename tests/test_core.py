"""Suite de verificación integral de GameHub Local."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import database, settings
from backend.adapters import json_index, rss_feed, search_url, wp_api
from backend.adapters.autodetect import autodetect_url
from backend.services import downloader, steam_enricher, winget_manager
from backend.services.title_cleaner import clean_game_title


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    db_file = tmp_path / "data" / "test_gamehub.db"

    demo_cat = cfg_dir / "demo_catalog.json"
    demo_cat.write_text(
        json.dumps(
            {
                "name": "Catálogo Test FTS5",
                "downloads": [
                    {
                        "title": "Portal 2: Complete Edition (v1.04 + All DLCs, MULTi12) [Repack] - 11.4 GB",
                        "uris": [
                            "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=Portal2",
                            "https://downloads.example.com/portal2-part1.rar",
                        ],
                        "uploadDate": "2026-10-24T12:00:00Z",
                        "fileSize": "11.4 GB",
                    },
                    {
                        "title": "Hollow Knight (v1.5.78.11833 + OST, MULTi10) - 7.4 GB",
                        "uris": ["https://downloads.example.com/hk.7z"],
                        "uploadDate": "2026-10-23T09:00:00Z",
                        "fileSize": "7.4 GB",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    (cfg_dir / "sources.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "test-json",
                        "name": "Catálogo Test FTS5",
                        "type": "json_index",
                        "category": "Catálogo JSON",
                        "url": str(demo_cat),
                        "search_url_template": "",
                        "enabled": True,
                    },
                    {
                        "id": "test-ext",
                        "name": "Web Externa Demo",
                        "type": "search_url",
                        "category": "Descarga Directa",
                        "url": "https://example.org",
                        "search_url_template": "https://example.org/?s={query}",
                        "enabled": True,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    real_deps = Path(__file__).resolve().parent.parent / "config" / "dependencies.json"
    (cfg_dir / "dependencies.json").write_text(real_deps.read_text(encoding="utf-8"), encoding="utf-8")

    monkeypatch.setattr(settings, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(settings, "SOURCES_FILE", cfg_dir / "sources.json")
    monkeypatch.setattr(settings, "DEPENDENCIES_FILE", cfg_dir / "dependencies.json")
    monkeypatch.setattr(settings, "DB_PATH", db_file)
    monkeypatch.setattr(settings, "AUTO_SYNC", False)
    database.init_db()
    return tmp_path


# --------------------------------------------------------------------------- 1. Title Cleaner (10+ casos)

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "Cyberpunk 2077: Ultimate Edition (v2.12 + All DLCs, MULTi18) [FitGirl Repack] - 64.2 GB",
            "Cyberpunk 2077: Ultimate Edition",
        ),
        (
            "Elden Ring Free Download (v1.12.3 / Build 14920312)",
            "Elden Ring",
        ),
        (
            "Baldur&#8217;s Gate 3 (Patch 7 + Bonus Content, MULTi15) [DODI Repack]",
            "Baldur’s Gate 3",
        ),
        (
            "Hollow.Knight.v1.5.78-GOG",
            "Hollow Knight",
        ),
        (
            "Stardew Valley (v1.6.15) [Portable] + Soundtrack - 680 MB",
            "Stardew Valley",
        ),
        (
            "Red Dead Redemption 2: Ultimate Edition [ElAmigos] (MULTi13) - 112,5 GB",
            "Red Dead Redemption 2: Ultimate Edition",
        ),
        (
            "Tony Hawk's Pro Skater 1 + 2 (v1.0 + All DLCs, MULTi8) [Repack]",
            "Tony Hawk's Pro Skater 1 + 2",
        ),
        (
            "Rune II: Decapitation Edition-RUNE",
            "Rune II: Decapitation Edition",
        ),
        (
            "Hades II (Early Access Update 4) [SteamRip] Free Download",
            "Hades II",
        ),
        (
            "The Witcher 3: Wild Hunt – Complete Edition (v4.04 + 18 DLCs, ENG/ESP) [KaOs Krew]",
            "The Witcher 3: Wild Hunt – Complete Edition",
        ),
    ],
)
def test_clean_game_title(raw: str, expected: str):
    assert clean_game_title(raw) == expected


# --------------------------------------------------------------------------- 2. Los 4 Adaptadores + Autodetect

def test_adapters_and_autodetect(isolated_env: Path):
    async def _run():
        # Mock transport para probar wp_api, rss y autodetect sin depender de terceros externos
        wp_posts = [
            {
                "id": 101,
                "date_gmt": "2026-10-24T10:00:00",
                "link": "https://wp.example.test/elden-ring/",
                "title": {"rendered": "Elden Ring &#8211; v1.16 [Repack] - 49.5 GB"},
                "excerpt": {"rendered": "<p> Gran RPG de acción. [&#8230;]</p>"},
                "content": {
                    "rendered": (
                        '<p>Tamaño: 49.5 GB</p>'
                        '<a href="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa&amp;dn=ER">Magnet</a>'
                    )
                },
            }
        ]
        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel><title>RSS Juegos Test</title>
          <item>
            <title>Celeste (v1.4.0.0, MULTi10) - 1.1 GB</title>
            <link>https://rss.example.test/celeste</link>
            <pubDate>Sat, 24 Oct 2026 11:00:00 GMT</pubDate>
            <description><![CDATA[<p>Plataformas indie. magnet:?xt=urn:btih:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb</p>]]></description>
          </item>
        </channel></rss>"""

        def handler(request: httpx.Request) -> httpx.Response:
            host = request.url.host
            path = request.url.path
            if host == "wp.example.test":
                if path == "/wp-json/wp/v2/posts":
                    return httpx.Response(200, json=wp_posts)
                if path == "/wp-json":
                    return httpx.Response(200, json={"name": "WP Repacks Test"})
                return httpx.Response(200, text="<html><title>WP Repacks</title></html>")
            if host == "rss.example.test":
                if path == "/wp-json/wp/v2/posts":
                    return httpx.Response(404)
                if path == "/feed/":
                    return httpx.Response(200, text=rss_xml, headers={"content-type": "application/rss+xml"})
                return httpx.Response(
                    200,
                    text='<html><head><title>Portal RSS</title><link rel="alternate" type="application/rss+xml" href="/feed/" /></head></html>',
                )
            if host == "json.example.test":
                return httpx.Response(
                    200,
                    json={
                        "name": "Índice Comunitario",
                        "downloads": [{"title": "Portal (v1.0)", "uris": ["magnet:?xt=urn:btih:cccccccccccccccccccccccccccccccccccccccc"]}],
                    },
                )
            if host == "protected.example.test":
                return httpx.Response(403, text="Cloudflare Challenge")
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            # 1) wp_api
            wp_src = {"id": "wp1", "name": "WP", "category": "Repacks", "url": "https://wp.example.test"}
            wp_items = await wp_api.fetch_latest(wp_src, client)
            assert len(wp_items) == 1
            assert wp_items[0]["clean_title"] == "Elden Ring"
            assert wp_items[0]["file_size"] == "49.5 GB"
            assert wp_items[0]["uris"][0].startswith("magnet:?xt=urn:btih:aaaa")

            # 2) rss
            rss_src = {"id": "rss1", "name": "RSS", "category": "Descarga Directa", "url": "https://rss.example.test/feed/"}
            rss_items = await rss_feed.fetch_latest(rss_src, client)
            assert len(rss_items) == 1
            assert rss_items[0]["clean_title"] == "Celeste"
            assert rss_items[0]["file_size"] == "1.1 GB"
            assert rss_items[0]["uris"][0].startswith("magnet:?xt=urn:btih:bbbb")

            # 3) json_index + FTS5
            json_src = {
                "id": "test-json",
                "name": "Catálogo Test FTS5",
                "category": "Catálogo JSON",
                "url": str(isolated_env / "config" / "demo_catalog.json"),
            }
            count, name = await json_index.sync(json_src, client)
            assert count == 2 and name == "Catálogo Test FTS5"
            hits = await json_index.search(json_src, client, "Portal")
            assert len(hits) == 1 and hits[0]["clean_title"] == "Portal 2: Complete Edition"

            # 4) search_url
            ext = search_url.external_link(
                {"id": "s1", "name": "Ext", "search_url_template": "https://ext.test/?s={query}"},
                "Hollow Knight",
            )
            assert ext and ext["url"] == "https://ext.test/?s=Hollow+Knight"

            # 5) Autodetect: JSON, WP, RSS y Cloudflare 403 fallback
            d_json = await autodetect_url("https://json.example.test/catalog.json", client=client)
            assert d_json["type"] == "json_index" and d_json["detected_items"] == 1

            d_wp = await autodetect_url("https://wp.example.test", client=client)
            assert d_wp["type"] == "wp_api" and d_wp["name"] == "WP Repacks Test"

            d_rss = await autodetect_url("https://rss.example.test", client=client)
            assert d_rss["type"] == "rss" and d_rss["url"].endswith("/feed/")

            d_cf = await autodetect_url("https://protected.example.test", client=client)
            assert d_cf["type"] == "search_url"
            assert d_cf["search_url_template"] == "https://protected.example.test/?s={query}"

    asyncio.run(_run())


# --------------------------------------------------------------------------- 3. Steam Store API + Caché SQLite

def test_steam_enrichment_live_and_cache(isolated_env: Path):
    async def _run():
        async with httpx.AsyncClient(timeout=10.0) as client:
            info = await steam_enricher.lookup_title("Portal 2", client)
            assert info is not None
            assert info["appid"] == 620
            assert "620/library_600x900.jpg" in info["poster_url"]

            # Verificar que quedó persistido en la caché SQLite local
            cached = database.steam_cache_get("Portal 2")
            assert isinstance(cached, dict) and cached["appid"] == 620

    asyncio.run(_run())


# --------------------------------------------------------------------------- 4. Endpoints FastAPI, Seguridad y Frontend UTF-8

def test_fastapi_endpoints_and_security(isolated_env: Path, monkeypatch: pytest.MonkeyPatch):
    from backend.main import app

    opened_uris: list[str] = []
    monkeypatch.setattr(downloader, "_url_opener", lambda u: opened_uris.append(u))

    with TestClient(app) as client:
        # Carga de SPA y estáticos
        r_html = client.get("/")
        assert r_html.status_code == 200
        assert "GameHub" in r_html.text

        assert client.get("/css/styles.css").status_code == 200
        assert client.get("/js/app.js").status_code == 200

        # Salud
        r_health = client.get("/api/health")
        assert r_health.status_code == 200 and r_health.json()["ok"] is True

        # Últimas novedades (autosincroniza la fuente activa en primera carga)
        r_latest = client.get("/api/releases/latest?enrich=false")
        assert r_latest.status_code == 200
        data_latest = r_latest.json()
        assert data_latest["total"] == 2

        # Búsqueda unificada (FTS5 + enlaces externos)
        r_search = client.get("/api/search?q=Hollow+Knight&enrich=false")
        assert r_search.status_code == 200
        sdata = r_search.json()
        assert sdata["total"] == 1
        assert len(sdata["groups"]) == 1
        assert any("Hollow+Knight" in l["url"] for l in sdata["external_links"])

        # Guardados (Bookmarks)
        sample_item = data_latest["items"][0]
        r_bm = client.post("/api/bookmarks/toggle", json={"item": sample_item})
        assert r_bm.status_code == 200 and r_bm.json()["bookmarked"] is True
        assert len(client.get("/api/bookmarks").json()["items"]) == 1

        # Magnet válido vs rechazo de esquemas peligrosos
        valid_mag = "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
        assert client.post("/api/download/magnet", json={"uri": valid_mag}).status_code == 200
        assert opened_uris == [valid_mag]
        assert client.post("/api/download/magnet", json={"uri": "javascript:alert(1)"}).status_code == 400
        assert client.post("/api/download/magnet", json={"uri": "C:\\Windows\\System32\\cmd.exe"}).status_code == 400

        # Seguridad Winget: rechazar IDs fuera de lista blanca o con caracteres de inyección
        assert (
            client.post("/api/dependencies/install", json={"package_ids": ["abbodi1406.vcredist; calc"]}).status_code
            == 400
        )
        assert (
            client.post("/api/dependencies/install", json={"package_ids": ["Paquete.NoAutorizado"]}).status_code
            == 400
        )
        r_deps = client.get("/api/dependencies")
        assert r_deps.status_code == 200 and len(r_deps.json()["runtimes"]) >= 5


# --------------------------------------------------------------------------- 5. Calendario de Lanzamientos + Favoritos

def test_release_calendar_parsing_and_favorites(isolated_env: Path, monkeypatch: pytest.MonkeyPatch):
    from backend.main import app
    from backend.services import release_calendar

    assert release_calendar.parse_steam_date("28 Oct, 2026") == ("2026-10-28", "day", "28 Octubre 2026")
    assert release_calendar.parse_steam_date("Oct 5, 2026") == ("2026-10-05", "day", "5 Octubre 2026")
    assert release_calendar.parse_steam_date("November 2026") == ("2026-11-98", "month", "Noviembre 2026")
    assert release_calendar.parse_steam_date("Q1 2027") == ("2027-03-99", "quarter", "T1 2027")
    assert release_calendar.parse_steam_date("Coming soon")[1] == "tba"

    sample_html = """
    <a class="search_result_row" data-ds-appid="4115450" data-ds-tagids="[19,122,29482]">
      <span class="title">Phantom Blade Zero</span>
      <span class="platform_img win"></span>
      <div class="search_released">28 Oct, 2026</div>
    </a>
    """
    parsed = release_calendar.parse_steam_search_html(sample_html, is_hot=True)
    assert len(parsed) == 1
    assert parsed[0]["appid"] == 4115450
    assert parsed[0]["release_date"] == "2026-10-28"
    assert "Acción" in parsed[0]["genres"] and "RPG" in parsed[0]["genres"]

    release_calendar._save_calendar_events(parsed)

    with TestClient(app) as client:
        r_cal = client.get("/api/calendar?mode=hot")
        assert r_cal.status_code == 200
        cdata = r_cal.json()
        assert cdata["total"] == 1
        assert cdata["items"][0]["title"] == "Phantom Blade Zero"

        # Guardar como favorito del calendario y consultar pestaña Mis Seguidos
        r_fav = client.post("/api/calendar/favorites/toggle", json={"item": cdata["items"][0]})
        assert r_fav.status_code == 200 and r_fav.json()["favorited"] is True

        r_only_favs = client.get("/api/calendar?mode=favorites")
        assert r_only_favs.status_code == 200
        assert r_only_favs.json()["total"] == 1
        assert r_only_favs.json()["favorites_count"] == 1


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
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "SOURCES_FILE", cfg_dir / "sources.json")
    monkeypatch.setattr(settings, "DEPENDENCIES_FILE", cfg_dir / "dependencies.json")
    monkeypatch.setattr(settings, "DB_PATH", db_file)
    monkeypatch.setattr(settings, "AUTO_SYNC", False)
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "local")
    monkeypatch.setattr(settings, "IS_WEB_MODE", False)
    monkeypatch.setattr(settings, "REQUIRE_AUTH", False)
    monkeypatch.setattr(settings, "INVITE_CODE", "")
    monkeypatch.setattr(settings, "GITHUB_STATE_TOKEN", "")
    monkeypatch.setattr(settings, "GITHUB_STATE_REPO", "")
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


# --------------------------------------------------------------------------- 6. Calendario Multi-Plataforma (Nintendo Switch 2, PS5 y Fusión)

def test_multiplatform_calendar_switch2_ps5_and_merge(isolated_env: Path):
    from backend.main import app
    from backend.services import release_calendar

    # Fechas europeas Nintendo eShop y tablas Wikipedia
    assert release_calendar.parse_steam_date("07-04-2027") == ("2027-04-07", "day", "7 Abril 2027")
    assert release_calendar.parse_steam_date("2050-12-31")[1] == "tba"
    assert release_calendar.parse_steam_date("October 29 [ 12 ]", default_year=2026) == (
        "2026-10-29",
        "day",
        "29 Octubre 2026",
    )
    assert release_calendar.parse_steam_date("Q4", default_year=2026) == ("2026-12-99", "quarter", "T4 2026")

    # 1) Nintendo Switch 2 Solr docs (ej. exclusivo Switch 2 + multi-plataforma)
    ns2_docs = [
        {
            "title": "The Duskbloods",
            "system_names_txt": ["Nintendo Switch 2"],
            "system_type": ["nintendoswitch2"],
            "dates_released_dts": ["2026-12-31T00:00:00Z"],
            "pretty_date_s": "2026",
            "pretty_game_categories_txt": ["Acción", "Rol (RPG)"],
            "publisher": "FromSoftware",
            "image_url_sq_s": "https://www.nintendo.com/eu/duskbloods_sq.jpg",
            "image_url_h2x1_s": "https://www.nintendo.com/eu/duskbloods_banner.jpg",
            "url": "/es-es/Juegos/Juegos-de-Nintendo-Switch-2/The-Duskbloods.html",
            "excerpt": "Acción multijugador gótica exclusiva de Nintendo Switch 2.",
        },
        {
            "title": "007 First Light - Edición Deluxe",
            "system_names_txt": ["Nintendo Switch 2"],
            "system_type": ["nintendoswitch2"],
            "dates_released_dts": ["2027-03-18T00:00:00Z"],
            "pretty_date_s": "18-03-2027",
            "pretty_game_categories_txt": ["Acción", "Aventura"],
            "publisher": "IO Interactive",
            "image_url_sq_s": "https://www.nintendo.com/eu/007_sq.jpg",
            "url": "/es-es/Juegos/Juegos-de-Nintendo-Switch-2/007-First-Light.html",
        },
    ]
    ns2_items = release_calendar.parse_nintendo_solr_docs(ns2_docs, cutoff_iso="2026-09-01")
    assert len(ns2_items) == 2
    assert ns2_items[0]["appid"] < 0
    assert "Switch 2" in ns2_items[0]["platforms"]

    # 2) PlayStation 5 HTML (mosaico con packshot + bloque con alias ES/EN)
    ps5_html = """
    <section>
      <h2>Más juegos para PS5 disponibles próximamente*</h2>
      <a class="game-grid-v2-tile" href="/es-es/games/intergalactic-the-heretic-prophet/">
        <img src="https://gmedia.playstation.com/is/image/SIEPDC/intergalactic.jpg" />
        <p>Intergalactic: The Heretic Prophet</p>
      </a>
    </section>
    <section>
      <h2>Reserva y añade a la lista de deseos los próximos lanzamientos para PS5*</h2>
      <div class="box">
        <h3>Grand Theft Auto VI</h3>
        <p>Regresa a Vice City en PlayStation 5.</p>
        <a href="/es-es/games/grand-theft-auto-vi/">Reserva ya</a>
      </div>
    </section>
    """
    ps5_items = release_calendar.parse_playstation_upcoming_html(ps5_html)
    assert len(ps5_items) == 2
    assert all("PS5" in it["platforms"] for it in ps5_items)

    # 3) Wikipedia tabla con rowspan + multi-plataforma (WIN, NS2, PS5, XBX/S)
    wiki_html = """
    <table class="wikitable">
      <tr><th>Release date</th><th>Title</th><th>Platform(s)</th><th>Type(s)</th><th>Genre(s)</th><th>Developer(s)</th><th>Publisher(s)</th></tr>
      <tr>
        <td rowspan="2">March 18</td>
        <td><i><a href="/wiki/007_First_Light">007 First Light</a></i></td>
        <td>WIN, NS2, PS5, XBX/S</td>
        <td>Original</td>
        <td>Action-adventure</td>
        <td>IO Interactive</td>
        <td>IO Interactive</td>
      </tr>
      <tr>
        <td><i><a href="/wiki/Ghost_of_Yotei">Ghost of Yōtei</a></i></td>
        <td>PS5</td>
        <td>Original</td>
        <td>Action-adventure</td>
        <td>Sucker Punch</td>
        <td>Sony Interactive Entertainment</td>
      </tr>
    </table>
    """
    wiki_items = release_calendar.parse_wikipedia_release_html(wiki_html, year=2027, cutoff_iso="2026-09-01")
    assert len(wiki_items) == 2
    assert wiki_items[1]["release_date"] == "2027-03-18"
    assert wiki_items[1]["platforms"] == ["PS5"]

    # 4) Fusión con versión de Steam de 007 First Light (conserva AppID positivo de Steam + une PC/Switch 2/PS5/Xbox Series + fecha exacta)
    steam_007 = {
        "appid": 2999007,
        "title": "007 First Light",
        "release_date": "9999-12-31",
        "precision": "tba",
        "window_label": "Próximamente",
        "is_hot": 1,
        "genres": ["Acción"],
        "platforms": ["PC"],
        "poster_url": "https://cdn.cloudflare.steamstatic.com/steam/apps/2999007/library_600x900.jpg",
        "header_url": "https://cdn.cloudflare.steamstatic.com/steam/apps/2999007/header.jpg",
        "store_url": "https://store.steampowered.com/app/2999007/",
        "summary": "",
    }
    release_calendar._save_calendar_events([steam_007, *ns2_items, *ps5_items, *wiki_items])

    with TestClient(app) as client:
        r_all = client.get("/api/calendar?mode=hot")
        assert r_all.status_code == 200
        body = r_all.json()
        assert "Switch 2" in body["available_platforms"]
        assert "PS5" in body["available_platforms"]

        by_title = {it["title"]: it for it in body["items"]}
        merged_007 = by_title["007 First Light"]
        assert merged_007["appid"] == 2999007
        assert merged_007["release_date"] == "2027-03-18"
        assert set(merged_007["platforms"]) >= {"PC", "Switch 2", "PS5", "Xbox Series"}

        # Filtrar exclusivamente Nintendo Switch 2 y PS5
        r_ns2 = client.get("/api/calendar?mode=hot&platform=Switch+2")
        assert r_ns2.status_code == 200
        ns2_titles = {it["title"] for it in r_ns2.json()["items"]}
        assert "The Duskbloods" in ns2_titles and "007 First Light" in ns2_titles
        assert "Ghost of Yōtei" not in ns2_titles

        r_ps5 = client.get("/api/calendar?mode=hot&platform=PS5")
        assert r_ps5.status_code == 200
        ps5_titles = {it["title"] for it in r_ps5.json()["items"]}
        assert {"Intergalactic: The Heretic Prophet", "Grand Theft Auto VI", "Ghost of Yōtei"} <= ps5_titles

        # Guardar un exclusivo de Nintendo Switch 2 (ID negativo sin Steam) en Favoritos
        duskbloods = next(it for it in r_ns2.json()["items"] if it["title"] == "The Duskbloods")
        assert duskbloods["appid"] < 0
        r_fav = client.post("/api/calendar/favorites/toggle", json={"item": duskbloods})
        assert r_fav.status_code == 200 and r_fav.json()["favorited"] is True

        favs = client.get("/api/calendar/favorites").json()["items"]
        assert any(f["title"] == "The Duskbloods" and "Switch 2" in f["platforms"] for f in favs)


# --------------------------------------------------------------------------- 7. Modo Web Cloud, Multi-Cuenta, Favoritos Persistentes y RBAC

def test_web_mode_multiuser_accounts_persistent_favorites_and_rbac(
    isolated_env: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from backend.main import app
    from backend.services import release_calendar

    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "web")
    monkeypatch.setattr(settings, "IS_WEB_MODE", True)
    monkeypatch.setattr(settings, "REQUIRE_AUTH", True)
    monkeypatch.setattr(settings, "INVITE_CODE", "amigos2026")

    release_calendar._save_calendar_events([
        {
            "appid": -9001,
            "title": "Grand Theft Auto VI",
            "release_date": "2026-11-19",
            "precision": "day",
            "window_label": "19 Noviembre 2026",
            "is_hot": 1,
            "genres": ["Acción"],
            "platforms": ["PS5", "Xbox Series"],
            "poster_url": "https://example.org/gtavi.jpg",
            "header_url": "https://example.org/gtavi.jpg",
            "store_url": "https://www.playstation.com/es-es/games/grand-theft-auto-vi/",
            "summary": "Vice City.",
        },
        {
            "appid": -9002,
            "title": "The Duskbloods",
            "release_date": "9999-12-31",
            "precision": "tba",
            "window_label": "Próximamente",
            "is_hot": 1,
            "genres": ["Acción", "RPG"],
            "platforms": ["Switch 2"],
            "poster_url": "https://example.org/dusk.jpg",
            "header_url": "https://example.org/dusk.jpg",
            "store_url": "https://www.nintendo.com/es-es/",
            "summary": "Switch 2 exclusive.",
        },
    ])

    with TestClient(app) as client:
        # Healthcheck público siempre accesible para Render / HF Spaces
        assert client.get("/api/ping").status_code == 200

        # Rutas protegidas exigen sesión en modo Web
        assert client.get("/api/releases/latest").status_code == 401
        assert client.get("/api/bookmarks").status_code == 401
        assert client.get("/api/calendar").status_code == 401

        # Código de invitación obligatorio
        r_bad_inv = client.post(
            "/api/auth/register",
            json={"username": "intruso", "password": "password123", "invite_code": "incorrecto"},
        )
        assert r_bad_inv.status_code == 400

        # 1) Crear cuenta de Ismael (primera cuenta -> Administrador)
        r_reg1 = client.post(
            "/api/auth/register",
            json={
                "username": "Ismael",
                "display_name": "Ismael HG",
                "password": "supersecret1",
                "invite_code": "amigos2026",
            },
        )
        assert r_reg1.status_code == 200
        tok_ismael = r_reg1.json()["token"]
        assert r_reg1.json()["user"]["is_admin"] is True
        h_ismael = {"Authorization": f"Bearer {tok_ismael}"}

        # 2) Crear cuenta de un amigo (segunda cuenta -> Miembro sin permisos sobre fuentes globales)
        client.cookies.clear()
        r_reg2 = client.post(
            "/api/auth/register",
            json={
                "username": "alex",
                "display_name": "Alex",
                "password": "amigoPassword2",
                "invite_code": "amigos2026",
            },
        )
        assert r_reg2.status_code == 200
        tok_alex = r_reg2.json()["token"]
        assert r_reg2.json()["user"]["is_admin"] is False
        h_alex = {"Authorization": f"Bearer {tok_alex}"}
        client.cookies.clear()

        # Cargar catálogo inicial
        items = client.get("/api/releases/latest?enrich=false", headers=h_ismael).json()["items"]
        portal_item = next(i for i in items if "Portal 2" in i["clean_title"])
        hk_item = next(i for i in items if "Hollow Knight" in i["clean_title"])

        cal_items = client.get("/api/calendar?mode=hot", headers=h_ismael).json()["items"]
        gta_cal = next(c for c in cal_items if c["title"] == "Grand Theft Auto VI")
        dusk_cal = next(c for c in cal_items if c["title"] == "The Duskbloods")

        # Ismael guarda Portal 2 y sigue GTA VI
        assert client.post("/api/bookmarks/toggle", json={"item": portal_item}, headers=h_ismael).json()["bookmarked"] is True
        assert client.post("/api/calendar/favorites/toggle", json={"item": gta_cal}, headers=h_ismael).json()["favorited"] is True

        # Alex guarda Hollow Knight y sigue The Duskbloods
        assert client.post("/api/bookmarks/toggle", json={"item": hk_item}, headers=h_alex).json()["bookmarked"] is True
        assert client.post("/api/calendar/favorites/toggle", json={"item": dusk_cal}, headers=h_alex).json()["favorited"] is True

        # RBAC: Alex NO puede borrar ni añadir fuentes globales; Ismael (Admin) sí puede
        assert client.delete("/api/sources/test-ext", headers=h_alex).status_code == 403
        assert (
            client.post(
                "/api/sources",
                json={"name": "Nueva Web", "type": "search_url", "search_url_template": "https://nueva.test/?s={query}"},
                headers=h_ismael,
            ).status_code
            == 200
        )

        # Seguridad Modo Web: bloqueo de ejecución de comandos OS en el servidor compartido
        assert (
            client.post(
                "/api/download/magnet",
                json={"uri": "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"},
                headers=h_ismael,
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/dependencies/install",
                json={"package_ids": ["Microsoft.DirectX"]},
                headers=h_ismael,
            ).status_code
            == 403
        )

        # Cerrar sesión y volver a iniciar sesión: cada usuario conserva intactos SUS propios favoritos
        client.post("/api/auth/logout", headers=h_ismael)
        relogin_ismael = client.post(
            "/api/auth/login",
            json={"username": "ismael", "password": "supersecret1"},
        )
        assert relogin_ismael.status_code == 200
        new_h_ismael = {"Authorization": f"Bearer {relogin_ismael.json()['token']}"}
        client.cookies.clear()

        bm_ismael = client.get("/api/bookmarks", headers=new_h_ismael).json()["items"]
        cal_ismael = client.get("/api/calendar/favorites", headers=new_h_ismael).json()["items"]
        assert [b["clean_title"] for b in bm_ismael] == ["Portal 2: Complete Edition"]
        assert [c["title"] for c in cal_ismael] == ["Grand Theft Auto VI"]

        bm_alex = client.get("/api/bookmarks", headers=h_alex).json()["items"]
        cal_alex = client.get("/api/calendar/favorites", headers=h_alex).json()["items"]
        assert [b["clean_title"] for b in bm_alex] == ["Hollow Knight"]
        assert [c["title"] for c in cal_alex] == ["The Duskbloods"]

    # 8) Simular reinicio completo de contenedor efímero (Render / HF Spaces) y restauración Cloud
    snapshot = database.export_persistent_state()
    fresh_db = isolated_env / "data" / "restarted_container.db"
    monkeypatch.setattr(settings, "DB_PATH", fresh_db)
    database.init_db()
    assert database.count_users() == 0

    database.import_persistent_state(snapshot)
    assert database.count_users() == 2

    with TestClient(app) as client2:
        r_login_after_wipe = client2.post(
            "/api/auth/login",
            json={"username": "alex", "password": "amigoPassword2"},
        )
        assert r_login_after_wipe.status_code == 200
        h_alex_restored = {"Authorization": f"Bearer {r_login_after_wipe.json()['token']}"}
        client2.cookies.clear()

        restored_bm = client2.get("/api/bookmarks", headers=h_alex_restored).json()["items"]
        restored_cal = client2.get("/api/calendar/favorites", headers=h_alex_restored).json()["items"]
        assert [b["clean_title"] for b in restored_bm] == ["Hollow Knight"]
        assert [c["title"] for c in restored_cal] == ["The Duskbloods"]


# --------------------------------------------------------------------------- 8. Punto de Entrada Serverless (Vercel) + Persistencia Síncrona

def test_vercel_serverless_entrypoint_and_sync(isolated_env: Path, monkeypatch: pytest.MonkeyPatch):
    from app import app as vercel_app
    from backend.services import cloud_sync

    pushed_calls: list[int] = []

    async def _fake_push() -> bool:
        pushed_calls.append(1)
        return True

    monkeypatch.setattr(settings, "IS_SERVERLESS", True)
    monkeypatch.setattr(settings, "DEPLOYMENT_MODE", "web")
    monkeypatch.setattr(settings, "IS_WEB_MODE", True)
    monkeypatch.setattr(settings, "REQUIRE_AUTH", True)
    monkeypatch.setattr(settings, "GITHUB_STATE_TOKEN", "ghp_test_token_for_deterministic_hmac")
    monkeypatch.setattr(settings, "GITHUB_STATE_REPO", "IsmaelHG10/gamehub-local")
    monkeypatch.setattr(cloud_sync, "push_state_now", _fake_push)
    monkeypatch.setattr(cloud_sync, "ensure_pulled", lambda *_a, **_kw: asyncio.sleep(0))

    # Clave secreta determinista derivada del token (sin depender de archivos efímeros)
    k1 = settings.get_secret_key()
    k2 = settings.get_secret_key()
    assert len(k1) == 64 and k1 == k2

    with TestClient(vercel_app) as client:
        assert client.get("/").status_code == 200
        r_reg = client.post(
            "/api/auth/register",
            json={"username": "ismael_vercel", "password": "vercelPassword1"},
        )
        assert r_reg.status_code == 200
        # En modo Serverless (Vercel), el guardado en GitHub se ejecuta antes de cerrar la petición HTTP
        assert len(pushed_calls) == 1





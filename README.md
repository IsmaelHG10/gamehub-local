# GameHub — Hub de Páginas Gaming & Calendario de Lanzamientos

Tu centro de mando personal y compartido para organizar todas tus **páginas de videojuegos en un menú visual por categorías**, consultar el **calendario multi-plataforma estilo Releases.com** (PC, Switch 2, PS5, Xbox Series y Switch) con cuenta atrás en vivo y exportación `.ics`, buscar de forma unificada en tus fuentes con **portadas automáticas de Steam** y preparar utilidades de PC Gaming vía `winget`.

---

## Características Principales

### 1. Hub de Páginas (Directorio Personalizable)
- Agrupa todas tus páginas activas por categoría en tarjetas visuales con **favicon automático**, tipo de conector (`WP API`, `RSS`, `JSON`, `Buscador`), notas y accesos directos (**Abrir**, **Buscar aquí**, **Ver feed**).
- En **Mis Fuentes** puedes pegar una URL individual o una lista completa de golpe (una URL por línea o en formato `Nombre | https://... | Categoría`) y GameHub autodetecta el mejor conector disponible:
  - **WordPress API (`wp_api`):** novedades + búsqueda en tiempo real.
  - **Feed RSS / Atom (`rss`):** sincronización de últimas entradas + búsqueda directa.
  - **Catálogo JSON (`json_index`):** indexación en **SQLite / Turso FTS5** para búsqueda instantánea.
  - **Buscador Directo (`search_url`):** lanzamiento en 1 clic con plantilla `{query}`.

### 2. Calendario de Lanzamientos (Estilo Releases.com)
- **Cuenta atrás en tiempo real** para los próximos lanzamientos destacados o seguidos.
- **4 vistas:** **Agenda** (tarjetas por día), **Lista compacta** (estilo Releases.com), **Mes** y **Semana**.
- **Navegación rápida:** pestañas *Recientes (-30d)*, *Próximos 30d*, *Todo el horizonte* y barra de salto directo por mes con contadores.
- **Filtros avanzados:** multi-selección de plataformas (`PC`, `Switch 2`, `PS5`, `Xbox Series`, `Switch`…), géneros, interruptor *Solo fecha exacta* y ordenación.
- **Exportación y avisos:** descarga `.ics` de tu lista o de cualquier juego, acceso directo a **Google Calendar** y avisos cuando salen juegos que sigues.

### 3. Modo Web Cloud Serverless (Vercel + Turso 0 €) + Cuentas
- Persistencia serverless completa mediante **Turso (libSQL HTTP)** sin dependencias binarias pesadas: usuarios, guardados, seguidos del calendario, páginas del Hub, feeds FTS5, portadas de Steam y eventos del calendario.
- Sincronización programada en segundo plano mediante `/api/cron/sync` (Vercel Cron diario + workflow opcional de GitHub Actions cada 6 horas) para cargas instantáneas sin *cold starts* lentos.
- Seguridad endurecida: sesiones firmadas `HMAC-SHA256`, contraseñas `PBKDF2-SHA256`, *rate limiting* en login/registro, protección **anti-SSRF** en peticiones salientes y cabeceras HTTP de seguridad.
- Consulta la guía paso a paso en **[`DESPLIEGUE_WEB_GRATIS.md`](DESPLIEGUE_WEB_GRATIS.md)**.

---

## Ejecución Local en Windows (1 clic)

Haz doble clic en **`Iniciar_GameHub.bat`**:
- Prepara automáticamente el entorno `.venv` e instala las dependencias de `requirements.txt`.
- Levanta el servidor local en `http://127.0.0.1:8765` usando SQLite local (`data/gamehub.db`).

---

## Arquitectura del Proyecto

```text
backend/
  main.py                  # API FastAPI, middleware de seguridad y /api/cron/sync
  settings.py              # Configuración Local / Vercel / Turso / Cron
  database.py              # Capa dual SQLite local ↔ Turso libSQL + FTS5
  turso_client.py          # Cliente HTTP Hrana v2 (/v2/pipeline)
  adapters/                # wp_api, rss_feed, json_index, search_url, autodetect
  services/
    calendar_parsers.py    # Parsers puros (Steam, Switch 2, PS5, Wikipedia)
    calendar_fetchers.py   # Fetchers asíncronos y enriquecimiento de carátulas
    release_calendar.py    # Orquestador, fusión multi-plataforma y favoritos
    source_manager.py      # Gestión de fuentes (archivo local o Turso app_config)
    url_safety.py          # Protección anti-SSRF y validación de rutas locales
    auth.py, steam_enricher.py, cloud_sync.py, downloader.py, winget_manager.py
frontend/
  index.html               # SPA responsive (Escritorio + Barra inferior móvil)
  css/styles.css           # Sistema de diseño oscuro editorial + skeletons
  js/                      # Módulos ES: app.js, hub.js, calendar.js, sources.js, state.js, icons.js
```

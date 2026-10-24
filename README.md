# 🎮 GameHub Local

Tu centro de mando personal y ligero en Windows para seguir **novedades de lanzamientos**, buscar juegos en múltiples fuentes con **portadas automáticas de Steam**, enviar descargas en **1 clic** (*Magnet* o *JDownloader 2*) e instalar todas las **dependencias esenciales de PC Gaming** mediante `winget`.

---

## 🚀 Cómo abrirlo (1 clic)

Haz doble clic en **`Iniciar_GameHub.bat`**.

- La primera vez prepara automáticamente el entorno `.venv` si hiciera falta.
- Levanta el servidor local privado en `http://127.0.0.1:8765` (solo accesible desde tu propio PC) y abre tu navegador.
- Desde la barra lateral izquierda puedes pulsar **📌 Crear icono en Escritorio** para tenerlo siempre a mano.

---

## ⚙️ Cómo añadir tus páginas y catálogos (Sin tocar código)

Ve a la pestaña **⚙️ Mis Fuentes**:

1. **Una sola web o JSON:** Pega la dirección principal de la página (ej. `https://ejemplo.com` o `https://ejemplo.org/catalogo.json`) y pulsa **✨ Autodetectar y Añadir**.
2. **Varias webs de golpe:** Pulsa **📋 Pegar varias URLs de golpe**, pega tu lista de sitios de confianza (una URL por línea) y pulsa **🚀 Detectar y Guardar Lista Completa**.

El motor autodetecta automáticamente el mejor conector disponible para cada web:
- **WordPress API (`wp_api`):** Obtiene últimas subidas y búsqueda exacta en tiempo real sin anuncios.
- **Feed RSS / Atom (`rss`):** Sincroniza las últimas subidas + redirección rápida de búsqueda.
- **Catálogo JSON (`json_index`):** Indexa miles de juegos en SQLite **FTS5** para búsqueda instantánea (<15 ms) y descarga en 1 clic.
- **Buscador Directo (`search_url`):** Si una web tiene anti-bot estricto, habilita un botón de búsqueda directa filtrada en 1 clic.

---

## 🧰 Dependencias y Descargas Rápidas

- **🧲 Magnet (1 clic):** Abre directamente el enlace en qBittorrent o tu cliente Torrent predeterminado de Windows.
- **📦 JDownloader 2 (1 clic):** Si tienes JDownloader 2 abierto, envía el paquete con el nombre limpio del juego a `127.0.0.1:9666`. Si está cerrado, copia los enlaces al portapapeles automáticamente.
- **⚡ Runtimes Winget:** Comprueba e instala *Visual C++ AIO*, *DirectX*, *.NET 8*, *XNA Framework*, *OpenAL*, *7-Zip*, *qBittorrent*, *JDownloader 2* y *Cloudflare WARP* desde repositorios oficiales.

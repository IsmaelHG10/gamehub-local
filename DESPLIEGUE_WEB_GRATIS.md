# 🌐 Publicar GameHub Gratis (0 € · Sin Tarjeta · Base de Datos Persistente)

GameHub está preparado para ejecutarse en **Vercel Serverless** con **Turso (libSQL)** como base de datos SQLite persistente en la nube (plan gratuito: 5 GB, 500M lecturas/mes, sin tarjeta) y sincronización programada en segundo plano para que la web abra al instante sin *cold starts* lentos.

---

## Paso 1 (2 min · Recomendado): Base de datos persistente gratuita en Turso

Al conectar Turso, **todo** se guarda de forma permanente y rápida en la nube: cuentas de usuario, guardados, seguidos del calendario, tus páginas del Hub, el caché de feeds, el índice FTS5 y las portadas de Steam.

1. Entra en **[turso.tech](https://turso.tech)** y regístrate gratis con tu cuenta de GitHub (*Plan Free · 0 € · sin tarjeta*).
2. Crea una base de datos llamada **`gamehub`** (elige la región más cercana, ej. `fra` / Frankfurt para Europa).
3. En el panel de tu base de datos `gamehub`, pulsa **Generate Token** (permisos *Read & Write*, sin caducidad o 1 año) y copia estos dos valores:
   - **Database URL:** `libsql://gamehub-tuusuario.turso.io`
   - **Auth Token:** `eyJhbGciOi...`

---

## Paso 2: Configurar variables de entorno en Vercel

1. Entra en tu proyecto de **[Vercel](https://vercel.com/dashboard)** → **Settings** → **Environment Variables**.
2. Añade estas variables:
   - **`TURSO_DATABASE_URL`** = tu `libsql://gamehub-....turso.io`
   - **`TURSO_AUTH_TOKEN`** = tu token JWT de Turso
   - **`CRON_SECRET`** = una clave aleatoria larga (ej. `gh_cron_9f3k2m8x7q1w5z`) para proteger el cron automático `/api/cron/sync`
   - **`GAMEHUB_INVITE_CODE`** = *(opcional)* contraseña de invitación si quieres restringir quién se registra (ej. `amigos2026`)
   - **`GAMEHUB_ADMIN_USER`** = *(opcional)* tu usuario administrador (ej. `ismael`)
3. Haz **Redeploy** (o sube los cambios a `main`).
4. Cuando termine, puedes comprobar que Turso está activo abriendo `/api/health`: verás `"storage": { "backend": "turso", "persistent": true }`.

> [!TIP]
> Si ya tenías cuentas guardadas con el modo antiguo de `GITHUB_STATE_TOKEN`, puedes desactivar `GITHUB_STATE_TOKEN` una vez configures Turso: Turso sustituye por completo los commits a la rama `gamehub-state` con latencia mucho menor y sin conflictos de escritura.

---

## Paso 3: Sincronización automática (Cron gratis)

- **Incluido en Vercel (`vercel.json`):** Vercel ejecuta automáticamente `GET /api/cron/sync` todos los días a las **06:00 UTC** usando tu `CRON_SECRET`, actualizando feeds, portadas de Steam y el calendario multi-plataforma en Turso.
- **Opcional — Sync cada 6 horas gratis con GitHub Actions:** ya tienes listo el workflow [`.github/workflows/sync-gamehub.yml`](.github/workflows/sync-gamehub.yml). Para activarlo solo tienes que ir a tu repositorio en GitHub → **Settings → Secrets and variables → Actions** y crear 2 *Repository secrets*:
  - `GAMEHUB_URL` = `https://gamehub-local.vercel.app`
  - `CRON_SECRET` = exactamente el mismo valor que pusiste en Vercel
- También puedes lanzar una sincronización manual en cualquier momento desde el botón **Actualizar** de la web o desde la pestaña **Actions** en GitHub.

---

## Alternativas (Modo Local / Docker)

- **En tu propio PC Windows (1 clic):** haz doble clic en [`Iniciar_GameHub.bat`](Iniciar_GameHub.bat). Usa SQLite local en `data/gamehub.db` automáticamente sin necesidad de Turso.
- **Contenedor Docker (Back4app / Leapcell / VPS):** usa el [`Dockerfile`](Dockerfile) incluido con las mismas variables `TURSO_DATABASE_URL` y `TURSO_AUTH_TOKEN` (o volumen persistente en `/app/data`).
- **Compartir temporalmente desde tu PC sin cuentas cloud:** ejecuta [`Compartir_Web_Amigos.bat`](Compartir_Web_Amigos.bat).

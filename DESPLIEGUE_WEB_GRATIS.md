# 🌐 Publicar GameHub en la Nube 24/7 Gratis (0 €)

GameHub ya está preparado con **Modo Web Cloud**, **cuentas de usuario (Crear cuenta / Iniciar sesión)**, **código de invitación privado para tus amigos** y **persistencia eterna a coste 0 €**.

> [!IMPORTANT]
> Seguirás pudiendo abrir `Iniciar_GameHub.bat` en tu PC exactamente igual que antes. El mismo proyecto detecta automáticamente si corre en tu escritorio (`local`) o en un servidor web (`web`).

---

## 🧠 ¿Cómo se guardan las cuentas y favoritos sin pagar bases de datos?

Los servidores gratuitos (Render, Hugging Face Spaces, Koyeb) reinician su disco temporal de vez en cuando, y las bases de datos gratuitas como *Render Postgres* se borran a los 30 días o *Supabase Free* se pausa a los 7 días.

Para evitarlo **para siempre a coste 0 €**, GameHub incluye [`cloud_sync.py`](backend/services/cloud_sync.py):
- Guarda automáticamente usuarios (con contraseñas cifradas `PBKDF2-SHA256`), `⭐ Guardados`, `📅 Favoritos del Calendario` y `⚙️ Mis Fuentes` en una rama separada llamada **`gamehub-state`** dentro de tu propio repositorio privado `IsmaelHG10/gamehub-local`.
- Al ir en una rama independiente de `main`, **nunca provoca bucles de redespliegue**, nunca caduca y las lecturas siguen siendo instantáneas (`<1 ms`) en SQLite.

---

## Paso 1 (1 min): Crear el Token de Persistencia en GitHub

1. Entra en [GitHub → Fine-grained Personal Access Tokens](https://github.com/settings/personal-access-tokens/new).
2. **Token name:** `gamehub-cloud-state`
3. **Expiration:** *No expiration* (o *1 year*).
4. **Repository access:** Selecciona **Only select repositories** → elige **`IsmaelHG10/gamehub-local`**.
5. Despliega **Repository permissions** → busca **Contents** → cámbialo a **Read and write**.
6. Pulsa **Generate token** y copia el código `github_pat_...` (lo pegarás en el Paso 2).

---

## Paso 2 (2 min): Elegir dónde alojarlo Gratis (0 €)

### Opción A1 — Render.com (La más directa desde tu GitHub privado)

1. Crea cuenta gratis (con tu propio botón *Continue with GitHub*) en **[render.com](https://render.com)** *(no pide tarjeta para el plan Free)*.
2. Pulsa **New +** → **Blueprint** (o **Web Service**) y selecciona tu repositorio **`IsmaelHG10/gamehub-local`**.
3. Render leerá automáticamente el archivo [`render.yaml`](render.yaml) (`Runtime: Docker`, `Plan: Free`).
4. Rellena las variables que te pide en pantalla:
   - `GITHUB_STATE_TOKEN`: pega el token `github_pat_...` del Paso 1.
   - `GAMEHUB_INVITE_CODE`: pon una clave para tus amigos (ej. `amigos2026`). Si la dejas vacía, cualquiera con el enlace podrá registrarse.
5. Pulsa **Deploy**. En ~2 minutos tendrás tu URL `https://gamehub-xxxx.onrender.com` lista para pasar por Discord/WhatsApp.

> [!TIP]
> En el plan gratuito de Render, si nadie entra durante 15 minutos el servidor entra en reposo y tarda ~25 segundos en despertar la primera vez que alguien abre el enlace (conservando intactas todas las cuentas y favoritos gracias al Paso 1). Si quieres evitar ese sueño de 15 min gratis, puedes añadir tu URL `https://.../api/ping` en [cron-job.org](https://cron-job.org) cada 10 minutos, o usar Hugging Face Spaces abajo.

---

### Opción A2 — Hugging Face Spaces (16 GB RAM gratis y sin apagarse cada 15 min)

1. Crea cuenta gratis en **[huggingface.co](https://huggingface.co)** y ve a **[New Space](https://huggingface.co/new-space)**.
2. Elige un nombre (ej. `gamehub`), selecciona **Space SDK: Docker** → **Blank**, hardware **CPU basic (Free · 2 vCPU · 16 GB RAM)** y visibilidad **Public** *(tu app estará igualmente protegida por pantalla de Login + `GAMEHUB_INVITE_CODE`)*.
3. En la pestaña **Settings → Variables and secrets** de tu Space, añade como **New secret**:
   - `GAMEHUB_SECRET_KEY` = una frase larga aleatoria cualquiera
   - `GAMEHUB_INVITE_CODE` = la clave que quieras compartir con tus amigos
   - `GITHUB_STATE_REPO` = `IsmaelHG10/gamehub-local`
   - `GITHUB_STATE_BRANCH` = `gamehub-state`
   - `GITHUB_STATE_TOKEN` = el token `github_pat_...` del Paso 1
4. Sube los archivos del proyecto al Space (o añade el Space como segundo `git remote` desde esta carpeta) y arrancará automáticamente en `https://<tu-usuario>-gamehub.hf.space`.

---

## 👥 Cómo funciona para ti y tus amigos

1. **Tú creas la primera cuenta:** La primera persona que se registra se convierte automáticamente en **👑 Administrador** (puede añadir, editar o importar fuentes en **⚙️ Mis Fuentes** para todo el grupo).
2. **Tus amigos crean su propia cuenta:** Entran al enlace, pulsan **✨ Crear cuenta**, escriben su usuario, contraseña y el código de invitación (si configuraste `GAMEHUB_INVITE_CODE`).
3. **Favoritos 100% independientes y permanentes:** Lo que cada amigo guarde en **⭐ Guardados** o siga con **★** en el **📅 Calendario (PC, Switch 2, PS5...)** es privado de su cuenta y se mantiene cada vez que vuelva a iniciar sesión desde cualquier dispositivo.
4. **Descargas directas en su propio PC:** Al pulsar **🧲 Magnet** o **📦 JD2** en la web, el navegador de tu amigo abre directamente su cliente Torrent local o envía los enlaces al JDownloader 2 (`127.0.0.1:9666`) de **su propio ordenador**.

# 🌐 Publicar GameHub Gratis (0 € · Sin Tarjeta)

Hemos adaptado el código de GameHub para que funcione de forma nativa en **Vercel Serverless** (además de contenedores Docker y enlace directo desde tu PC), evitando los bloqueos recientes de Hugging Face (que pasó Docker a pago PRO) y los falsos positivos anti-VPN de Render.

> [!WARNING]
> **Consejo clave antes de registrarte en cualquier plataforma gratuita:**
> Si estás en un portátil con **Zscaler / VPN corporativa** activa, los sistemas antifraude automáticos (como le ocurrió a Render) suelen suspender las cuentas nuevas al detectar IPs de proxy/VPN junto con una cuenta de GitHub recién creada. **Haz el registro desde tu móvil con 4G/5G (o desconectando la VPN un momento)** y no tendrás ningún bloqueo.

---

## Paso Previo (1 min · Solo para Nube 24/7): Token de GitHub para Guardar Cuentas

Para que las cuentas de tus amigos y sus favoritos no se borren nunca a coste 0 €:

1. Entra en [GitHub → Fine-grained Personal Access Tokens](https://github.com/settings/personal-access-tokens/new).
2. **Token name:** `gamehub-cloud-state` · **Expiration:** *No expiration* (o *1 year*).
3. **Repository access:** **Only select repositories** → elige **`IsmaelHG10/gamehub-local`**.
4. **Repository permissions** → despliega y pon **Contents: Read and write**.
5. Pulsa **Generate token** y copia el código `github_pat_...`.

---

## 🥇 Opción 1 (Recomendada · Nube 24/7 · 0 € · Sin Tarjeta): Vercel

GameHub ya incluye [`app.py`](app.py) y [`vercel.json`](vercel.json) listos para el plan **Hobby (Gratis)** de Vercel: no pide tarjeta, no se apaga 30 segundos cada cuarto de hora y despliega directo desde tu GitHub privado.

1. Entra en **[vercel.com/signup](https://vercel.com/signup)** → elige plan **Hobby** (*Personal / Free*) → **Continue with GitHub**.
2. Pulsa **Add New... → Project** y dale a **Import** en tu repositorio **`IsmaelHG10/gamehub-local`** *(si no sale, pulsa "Adjust GitHub App Permissions" para darle permiso a ese repo)*.
3. Despliega la sección **Environment Variables** antes de pulsar Deploy y añade:
   - **`GITHUB_STATE_TOKEN`** = pega tu `github_pat_...` del paso anterior.
   - **`GAMEHUB_INVITE_CODE`** = *(opcional)* una contraseña de grupo para tus amigos, ej. `amigos2026`.
   *(No necesitas añadir nada más: el repositorio `IsmaelHG10/gamehub-local`, la rama `gamehub-state`, el modo `web` y la firma criptográfica de sesión se configuran automáticamente).*
4. Pulsa **Deploy**. En ~45 segundos tendrás tu web pública `https://gamehub-local-xxxx.vercel.app` activa 24/7.

---

## 🥈 Opción 2 (Alternativa Nube Docker · 0 € · Sin Tarjeta): Back4app Containers o Leapcell

Si prefieres un contenedor Docker tradicional gratuito sin tarjeta usando el [`Dockerfile`](Dockerfile) incluido:

- **[Back4app Containers](https://www.back4app.com/lander/containers-caas)** (*Plan Free: 1 contenedor gratis sin tarjeta*): Conecta GitHub → elige `IsmaelHG10/gamehub-local` → añade `GITHUB_STATE_TOKEN` y `GAMEHUB_INVITE_CODE` → Deploy.
- **[Leapcell](https://leapcell.io)** (*Plan Free Python/FastAPI sin tarjeta*): Importa `IsmaelHG10/gamehub-local` → comando `uvicorn backend.main:app --host 0.0.0.0 --port 8080` → añade `GITHUB_STATE_TOKEN` → Deploy.

---

## ⚡ Opción 3 (Cero Registros en Ninguna Web · Instantáneo): `Compartir_Web_Amigos.bat`

Si quieres enseñárselo a tus amigos **ahora mismo en 10 segundos sin crearte cuenta en ningún sitio**:

1. Haz doble clic en **`Compartir_Web_Amigos.bat`**.
2. Escribe un código de invitación si quieres (o pulsa `Enter`).
3. La consola usará el cliente `ssh` integrado de Windows para darte al instante una dirección pública temporal **`https://xxxx.lhr.life`**.
4. Tus amigos entran a ese enlace, **crean su cuenta**, guardan sus juegos favoritos en la base de datos de tu propio PC (`data/gamehub.db`, permanente sin necesidad siquiera de token) y cuando cierres la ventana negra el enlace se apaga solo.

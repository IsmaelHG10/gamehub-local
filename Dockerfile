FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GAMEHUB_MODE=web \
    GAMEHUB_REQUIRE_AUTH=true \
    PORT=7860

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Usuario sin privilegios UID 1000 (compatible con Hugging Face Spaces y Render)
RUN useradd -m -u 1000 gamehub && \
    mkdir -p /app/data /app/config && \
    chown -R gamehub:gamehub /app

COPY --chown=gamehub:gamehub backend ./backend
COPY --chown=gamehub:gamehub frontend ./frontend
COPY --chown=gamehub:gamehub config ./config

USER gamehub

EXPOSE 7860

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-7860}"]

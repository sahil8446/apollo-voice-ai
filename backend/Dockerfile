# ---- Apollo Voice AI backend ----
# Slim, single-stage image. Gunicorn manages uvicorn workers so a single
# container uses all CPU cores; scale horizontally by running more containers.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The admin UI lives one level up from backend/ in the repo; copy it in if present.
# (docker-compose mounts it; on platform builds set the build context to repo root.)

EXPOSE 8000

# entrypoint runs migrations + seed (idempotent) then launches the server.
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "2", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "60", \
     "--access-logfile", "-"]

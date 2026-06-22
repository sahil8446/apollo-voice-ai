#!/usr/bin/env sh
# Apply schema migrations, then idempotently seed Apollo data, then exec the
# server command. Safe to run on every deploy/restart.
set -e

echo "[entrypoint] running migrations..."
alembic upgrade head || echo "[entrypoint] alembic not configured or already current"

echo "[entrypoint] seeding (idempotent)..."
python -m app.seed.seed || echo "[entrypoint] seed skipped"

echo "[entrypoint] starting server: $*"
exec "$@"

#!/usr/bin/env sh
# Apply schema migrations, then idempotently seed Apollo data, then exec the
# server command. Safe to run on every deploy/restart.
set -e

echo "[entrypoint] running migrations..."
# Migrations are fatal: never start the server against a broken/old schema.
alembic upgrade head

echo "[entrypoint] seeding (idempotent)..."
# Seeding is non-fatal (avoid crash-loops) but LOUD: if it fails we print a
# clear banner so it can't fail silently and leave an empty DB unnoticed.
if python -m app.seed.seed; then
  echo "[entrypoint] seed OK"
else
  echo "============================================================"
  echo "[entrypoint] !!! SEED FAILED — see the traceback above.    "
  echo "[entrypoint] !!! The API will start but the DB may be EMPTY."
  echo "============================================================"
fi

echo "[entrypoint] starting server: $*"
exec "$@"

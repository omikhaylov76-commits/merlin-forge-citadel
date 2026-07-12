#!/bin/sh
# Запуск ядра в облаке (Railway, #15): миграции Alembic → uvicorn. БД — Railway Postgres.
# Railway отдаёт DATABASE_URL как postgresql:// (или postgres://); ядро ждёт драйвер psycopg3
# (postgresql+psycopg://) — нормализуем схему, если она голая.
set -e

case "$DATABASE_URL" in
  postgresql+psycopg://*) : ;;                                   # уже правильно
  postgresql://*) export DATABASE_URL="postgresql+psycopg://${DATABASE_URL#postgresql://}" ;;
  postgres://*)   export DATABASE_URL="postgresql+psycopg://${DATABASE_URL#postgres://}" ;;
esac

echo "[core] alembic upgrade head"
alembic upgrade head
echo "[core] uvicorn на :${PORT:-8000}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"

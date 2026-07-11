#!/bin/sh
# Запуск картриджа Пифагора: движок (dry-run demo) + read-only адаптер по Контракту, в ОДНОМ контейнере.
# Оба процесса делят локальную SQLite воркера (config.ops.DB_PATH) — адаптер читает её как дашборд
# (owner=False, без singleton-лока). БЕЗОПАСНЫЙ РЕЖИМ: LIVE_TRADING_ENABLED=0 (брокера не трогаем),
# BYBIT_DEMO=1. Реальные ключи/торговля — отдельный гейт go-live.
set -e

if [ -n "$BYBIT_API_KEY" ] && [ -n "$BYBIT_API_SECRET" ]; then
  echo "[cartridge] движок Пифагора (dry-run demo) в фоне: config.validate требует demo-ключи (не боевые)"
  ( cd /pifagor && exec python app/main.py ) &
else
  echo "[cartridge] BYBIT_* не заданы → адаптер-only. Движок НЕ поднят (config.validate требует ключи);"
  echo "[cartridge] телеметрия пойдёт из состояния БД, если оно засеяно внешне. Для полной копии — demo-ключи."
fi

# Адаптер — foreground (PID 1-логика). stop_close встаёт → процесс выходит (restartPolicy=never).
exec python -m app.main

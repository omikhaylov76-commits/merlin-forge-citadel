#!/bin/sh
# Запуск картриджа Пифагора в ОДНОМ контейнере: движок + read-only адаптер по Контракту.
# Опционально ТРЕТИЙ процесс — keyless-скаут (fail-closed по SCOUT_ENABLED, ОТДЕЛЬНАЯ scout.db,
# супервизор liveness+RSS). Движок и адаптер делят SQLite воркера; скаут — свою scout.db (ADR-0016).
# БЕЗОПАСНЫЙ РЕЖИМ по умолчанию: LIVE_TRADING_ENABLED=0 (брокера не трогаем), BYBIT_DEMO=1.
set -e

# ── баннер режима движка (хвост A #48: динамический по LIVE_TRADING_ENABLED, НЕ хардкод) ──
engine_mode() {
  if [ "$LIVE_TRADING_ENABLED" = "1" ]; then
    echo "LIVE demo (ставит реальные демо-ордера)"
  else
    echo "dry-run demo (считает, ордеров НЕ ставит)"
  fi
}

start_engine() {
  if [ -n "$BYBIT_API_KEY" ] && [ -n "$BYBIT_API_SECRET" ]; then
    echo "[cartridge] движок Пифагора [$(engine_mode)] в фоне: config.validate требует demo-ключи (не боевые)"
    ( cd /pifagor && exec python app/main.py ) &
  else
    echo "[cartridge] BYBIT_* не заданы → адаптер-only. Движок НЕ поднят (config.validate требует ключи);"
    echo "[cartridge] телеметрия пойдёт из состояния БД, если оно засеяно внешне. Для полной копии — demo-ключи."
  fi
}

# ── супервизор скаута (ADR-0016 в.4): liveness по scout_control.heartbeat + RSS-кап через ──
# ── app.scout_health; рестарт ТОЛЬКО процесса скаута. Движок/адаптер не трогаются; ──
# ── restartPolicy=never контейнера цел (OOM контейнера убил бы движок с позициями). ──
scout_supervise() {
  set +e                                   # устойчивость: единичный non-zero не роняет супервизор
  _restarts=0
  while true; do
    _started=$(date +%s)
    # -u DATABASE_URL: скаут ВСЕГДА на своей SQLite (DB_PATH), даже если движок на Postgres —
    # иначе config.ops берёт DATABASE_URL и скаут делит БД движка (ADR-0016 в.2, решение #51-приёмки).
    env -u DATABASE_URL DB_PATH="$SCOUT_DB" SCOUT_ENABLED=1 \
        SCOUT_RPS="$SCOUT_RPS" SCOUT_LIST_MAX="$SCOUT_LIST_MAX" \
        SCOUT_CAL_UTC_HOUR="$SCOUT_CAL_UTC_HOUR" SCOUT_TFS="$SCOUT_TFS" \
        $SCOUT_CMD &
    _pid=$!
    echo "[scout-sup] скаут запущен pid=$_pid (рестартов: $_restarts, db=$SCOUT_DB, rss-кап=${SCOUT_RSS_CAP_MB}MB)"
    while kill -0 "$_pid" 2>/dev/null; do
      sleep "$SCOUT_CHECK_SEC"
      kill -0 "$_pid" 2>/dev/null || break                    # умер сам во сне → на рестарт
      # RSS скаута (КБ): /proc (slim-контейнер БЕЗ procps) → ps (локальный dev). Портируемо, без deps.
      _rss=$(awk '/^VmRSS:/{print $2}' /proc/"$_pid"/status 2>/dev/null)
      [ -n "$_rss" ] || _rss=$(ps -o rss= -p "$_pid" 2>/dev/null | tr -d ' ')
      _elapsed=$(( $(date +%s) - _started ))
      _v=$(python -m app.scout_health --db "$SCOUT_DB" --rss-kb "${_rss:-0}" \
            --cap-mb "$SCOUT_RSS_CAP_MB" --max-silence-sec "$SCOUT_MAX_SILENCE_SEC" \
            --elapsed-sec "$_elapsed" --grace-sec "$SCOUT_GRACE_SEC" 2>/dev/null)
      # рестарт ТОЛЬКО на явный вердикт restart:* — сбой health-CLI (пустой вывод) НЕ убивает
      # живой скаут (fail-safe: ошибка инструмента ≠ смерть скаута; смерть ловит kill -0 выше).
      case "$_v" in
        restart:*)
          echo "[scout-sup] нездоров: $_v → kill -9 $_pid, рестарт ТОЛЬКО скаута"
          kill -9 "$_pid" 2>/dev/null || true
          break ;;
      esac
    done
    wait "$_pid" 2>/dev/null || true          # пожать зомби (и после kill, и после естественной смерти)
    _restarts=$(( _restarts + 1 ))
    _backoff=$_restarts; [ "$_backoff" -gt 30 ] && _backoff=30   # бэкофф с потолком 30с (не долбим API/лог)
    echo "[scout-sup] скаут завершился → рестарт #$_restarts (пауза ${_backoff}с)"
    sleep "$_backoff"
  done
}

start_scout_if_enabled() {
  # FAIL-CLOSED: скаут поднимается ТОЛЬКО при явном SCOUT_ENABLED=1 (vendor-дефолт True из
  # scout/config.py:12 НЕ решает — обёртка гейтит явно). Иначе процесса скаута нет.
  if [ "$SCOUT_ENABLED" != "1" ]; then
    echo "[cartridge] скаут ВЫКЛ (SCOUT_ENABLED='${SCOUT_ENABLED:-}' != 1, fail-closed) — процесс НЕ поднят"
    return 0
  fi
  # ОТДЕЛЬНАЯ scout.db (иначе flock-коллизия с движком по <db>.lock, db.py:365 → смерть скаута через ~90с).
  SCOUT_DB="${SCOUT_DB_PATH:-$PIFAGOR_HOME/scout.db}"
  # супервизор
  SCOUT_RSS_CAP_MB="${SCOUT_RSS_CAP_MB:-300}"
  SCOUT_CHECK_SEC="${SCOUT_CHECK_SEC:-30}"
  SCOUT_MAX_SILENCE_SEC="${SCOUT_MAX_SILENCE_SEC:-180}"
  SCOUT_GRACE_SEC="${SCOUT_GRACE_SEC:-180}"
  # разведение бёрстов (ADR-0016 в.5): дефолты обёртки; per-instance крутилки прокидываются из env.
  SCOUT_RPS="${SCOUT_RPS:-1}"
  SCOUT_LIST_MAX="${SCOUT_LIST_MAX:-50}"
  SCOUT_CAL_UTC_HOUR="${SCOUT_CAL_UTC_HOUR:-5}"
  SCOUT_TFS="${SCOUT_TFS:-4h,1h}"
  # команда запуска скаута (тест-шов SCOUT_CMD; в проде — vendored scout/main.py снимка).
  SCOUT_CMD="${SCOUT_CMD:-python $PIFAGOR_HOME/scout/main.py}"
  # адаптеру (foreground, ниже) явно разрешаем читать scout.db и пушить снимки в ядро (#52) —
  # двойной гейт с существованием файла; на флоте (scout off) флаг не выставлен → пуша нет.
  export MF_SCOUT_PUSH=1
  echo "[cartridge] скаут ВКЛ (SCOUT_ENABLED=1) → супервизор; db=$SCOUT_DB rps=$SCOUT_RPS list_max=$SCOUT_LIST_MAX"
  scout_supervise &
}

main() {
  start_engine
  start_scout_if_enabled
  # Адаптер — foreground (PID 1-логика). stop_close встаёт → процесс выходит (restartPolicy=never).
  exec python -m app.main
}

# main запускается ТОЛЬКО при ПРЯМОМ вызове (CMD ["./start.sh"]); при `. start.sh` в тестах/прогонах
# исполняются лишь определения функций (движок/адаптер не поднимаются) — так доказываем (а)-(г) точечно.
case "$0" in
  *start.sh) main "$@" ;;
esac

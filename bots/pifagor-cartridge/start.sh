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

# ── супервизор движка (S8 «Динамо-близнец», ADR-0019): при смене вселенной (провайдер-адаптер бампнул ──
# ── COINS_CONFIG_PATH.gen) мягко рестартит ТОЛЬКО движок → тот перечитывает разъём. ДОЖИДАЕТСЯ выхода ──
# ── старого процесса (flock/advisory-lock БД освободятся) перед рестартом. F-restart «а» (Веха 2): ──
# ── при открытых позициях/ордерах (флаг .positions непуст) рестарт ОТКЛАДЫВАЕТСЯ до закрытия ИЛИ ──
# ── max-defer (громкий лог) — не бросаем движок мид-ордер; пин держит held в наборе (ADR-0019). ──
engine_supervise() {
  if [ -z "$BYBIT_API_KEY" ] || [ -z "$BYBIT_API_SECRET" ]; then
    echo "[engine-sup] BYBIT_* не заданы → движок НЕ поднят (config.validate требует demo-ключи)"
    return 0
  fi
  set +e                                     # единичный non-zero не роняет супервизор
  _erestarts=0
  _gfile="$COINS_CONFIG_PATH.gen"
  _pfile="$COINS_CONFIG_PATH.positions"                     # F-restart «а»: флаг открытых позиций (пишет адаптер)
  while true; do
    _egen=$(cat "$_gfile" 2>/dev/null || echo 0)
    ( cd /pifagor && exec python app/main.py ) &
    _epid=$!
    _defer=0                                                # счётчик отложенных рестартов (на жизнь движка)
    echo "[engine-sup] движок [$(engine_mode)] pid=$_epid (рестартов: $_erestarts, gen=$_egen)"
    while kill -0 "$_epid" 2>/dev/null; do
      sleep "${DYNAMIC_SUP_CHECK_SEC:-15}"
      kill -0 "$_epid" 2>/dev/null || break                 # движок сам умер → на рестарт
      [ "$(cat "$_gfile" 2>/dev/null || echo 0)" = "$_egen" ] && continue   # вселенная та же → живём
      # Вселенная сменилась. F-restart «а» (ADR-0019): НЕ рестартить движок при открытых позициях —
      # брошенная мид-ордер позиция = money-риск. Пин держит held в наборе → отсрочка безопасна.
      if [ -s "$_pfile" ]; then
        _defer=$(( _defer + 1 ))
        _maxdefer="${DYNAMIC_RESTART_MAX_DEFER:-240}"       # 240×15с ≈ 1ч до принудительного рестарта
        if [ "$_defer" -lt "$_maxdefer" ]; then
          echo "[engine-sup] ⏸ рестарт ОТЛОЖЕН: открытые позиции/ордера [$(cat "$_pfile" 2>/dev/null)] ($_defer/$_maxdefer)"
          continue                                          # держим движок, ждём закрытия слота
        fi
        echo "[engine-sup] ⚠ max-defer $_maxdefer превышен при открытых позициях → рестарт (пин несёт held, движок перечитает из БД)"
      fi
      echo "[engine-sup] вселенная сменилась (gen $_egen→$(cat "$_gfile" 2>/dev/null)) → рестарт ТОЛЬКО движка"
      kill -TERM "$_epid" 2>/dev/null || true
      break
    done
    wait "$_epid" 2>/dev/null || true                        # ДОЖДАТЬСЯ выхода → лок БД освобождён
    _erestarts=$(( _erestarts + 1 ))
    _epause="${DYNAMIC_MIN_RESTART_SEC:-20}"                 # min-интервал рестарта (анти-thrash поверх провайдера)
    echo "[engine-sup] движок завершился → рестарт #$_erestarts (пауза ${_epause}с)"
    sleep "$_epause"
  done
}

# ── супервизор скаута (ADR-0016 в.4): liveness по scout_control.heartbeat + RSS-кап через ──
# ── app.scout_health; рестарт ТОЛЬКО процесса скаута. Движок/адаптер не трогаются; ──
# ── restartPolicy=never контейнера цел (OOM контейнера убил бы движок с позициями). ──
scout_supervise() {
  set +e                                   # устойчивость: единичный non-zero не роняет супервизор
  _restarts=0
  while true; do
    _started=$(date +%s)
    # Разведка-стол: подтягиваем оверрайды дозора из ядра (файл пишет boot-fetch/dozor_apply, только
    # whitelist SCOUT_* числа/enum) — source на КАЖДОМ (ре)старте → новые пороги вступают при рестарте
    # скаута. gen — маркер смены (бампается при записи), сверяем ниже для мягкого рестарта.
    [ -f "$SCOUT_OVERRIDE_FILE" ] && . "$SCOUT_OVERRIDE_FILE"
    _gen=$(cat "$SCOUT_OVERRIDE_FILE.gen" 2>/dev/null || echo 0)
    # -u DATABASE_URL: скаут ВСЕГДА на своей SQLite (DB_PATH), даже если движок на Postgres —
    # иначе config.ops берёт DATABASE_URL и скаут делит БД движка (ADR-0016 в.2, решение #51-приёмки).
    # -u COINS_CONFIG_PATH (S8/ADR-0019): скаут на ДЕФОЛТНОЙ вселенной (bars.py), динамика Борса в бары не течёт.
    env -u DATABASE_URL -u COINS_CONFIG_PATH DB_PATH="$SCOUT_DB" SCOUT_ENABLED=1 \
        SCOUT_RPS="$SCOUT_RPS" SCOUT_LIST_MAX="$SCOUT_LIST_MAX" \
        SCOUT_CAL_UTC_HOUR="$SCOUT_CAL_UTC_HOUR" SCOUT_TFS="$SCOUT_TFS" SCOUT_TF="$SCOUT_TF" \
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
      # Разведка-стол: сменились настройки дозора (gen бампнут dozor_apply/boot-fetch) → мягкий
      # рестарт ТОЛЬКО скаута (source нового файла на след. итерации). Движок/адаптер не трогаются.
      if [ "$(cat "$SCOUT_OVERRIDE_FILE.gen" 2>/dev/null || echo 0)" != "$_gen" ]; then
        echo "[scout-sup] новые настройки дозора (gen сменился) → мягкий рестарт скаута"
        kill -TERM "$_pid" 2>/dev/null || true
        break
      fi
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
  # #55/П2: дефолты с 180 подняты — холодный Этап A (300 монет @ RPS=1 ≈356с) > 180 → рестарт-цикл.
  # max_silence ВЫШЕ SCOUT_BAN_SLEEP_SEC(600), иначе штатный 403-backoff убил бы скаут. Проверено env Галахада.
  SCOUT_MAX_SILENCE_SEC="${SCOUT_MAX_SILENCE_SEC:-1200}"
  SCOUT_GRACE_SEC="${SCOUT_GRACE_SEC:-1800}"
  # разведение бёрстов (ADR-0016 в.5): дефолты обёртки; per-instance крутилки прокидываются из env.
  SCOUT_RPS="${SCOUT_RPS:-1}"
  SCOUT_LIST_MAX="${SCOUT_LIST_MAX:-50}"
  SCOUT_CAL_UTC_HOUR="${SCOUT_CAL_UTC_HOUR:-5}"
  SCOUT_TFS="${SCOUT_TFS:-4h,1h}"
  # Разведка-стол: primary ТФ (гнал границу авто-скана; '1h' → часовой автоскан) + файл-оверрайд из
  # ядра (пишет boot-fetch/dozor_apply; супервизор source'ит на каждом рестарте). Настройкам том не нужен.
  SCOUT_TF="${SCOUT_TF:-4h}"
  SCOUT_OVERRIDE_FILE="${SCOUT_OVERRIDE_FILE:-$PIFAGOR_HOME/scout_overrides.env}"
  # команда запуска скаута (тест-шов SCOUT_CMD; в проде — vendored scout/main.py снимка).
  SCOUT_CMD="${SCOUT_CMD:-python $PIFAGOR_HOME/scout/main.py}"
  # адаптеру (foreground, ниже) явно разрешаем читать scout.db и пушить снимки в ядро (#52) —
  # двойной гейт с существованием файла; на флоте (scout off) флаг не выставлен → пуша нет.
  export MF_SCOUT_PUSH=1
  echo "[cartridge] скаут ВКЛ (SCOUT_ENABLED=1) → супервизор; db=$SCOUT_DB rps=$SCOUT_RPS list_max=$SCOUT_LIST_MAX"
  scout_supervise &
}

# ── одноразовая ре-база риск-состояния (kill-switch) после РУЧНОЙ смены баланса (#Персиваль-ks) ──
# Гейт MF_RISK_REBASELINE_ONCE=1 (Персиваль-only; убрать после применения). Правит capital_state ДО
# старта движка (иначе singleton-lock движка занимает БД). Всё в лог. Прочие боты без флага — no-op.
risk_rebaseline_if_requested() {
  if [ "$MF_RISK_REBASELINE_ONCE" = "1" ]; then
    echo "[cartridge] MF_RISK_REBASELINE_ONCE=1 → ре-база риск-состояния движка (сброс ложной защёлки kill-switch)"
    python -m app.risk_rebaseline || echo "[cartridge] ре-база: ошибка (старт НЕ валю)"
  fi
}

main() {
  # engine-БД на durable-МОНТИРУЕМОМ пути (#57, ЗАКОН ЭТАЛОНА): том Railway на /data → состояние
  # (HWM/сетапы/компаунд) переживает передеплой. Без тома — эфемерно тут же (как раньше, иной путь).
  # НЕ /pifagor/* (там вендор-код образа — том перекрыл бы его). Скаут задаёт свой DB_PATH сам (scout.db).
  export DB_PATH="${DB_PATH:-/data/pifagor.db}"
  mkdir -p "$(dirname "$DB_PATH")" 2>/dev/null || true
  echo "[cartridge] engine-БД: DB_PATH=$DB_PATH (durable при томе на $(dirname "$DB_PATH"))"
  risk_rebaseline_if_requested   # ДО движка: иначе singleton-lock займёт БД (#Персиваль-ks)
  if [ "$DYNAMIC_ENABLED" = "1" ]; then
    # S8 «Динамо-близнец»: движок берёт вселенную из печки. COINS_CONFIG_PATH на ЭФЕМЕРНОМ пути
    # (провайдер-адаптер пишет coins.json, разъём strategy.py читает); скаут/скринер стрижём (env -u).
    export COINS_CONFIG_PATH="${COINS_CONFIG_PATH:-$PIFAGOR_HOME/coins.json}"
    echo "[cartridge] динамика ВКЛ (DYNAMIC_ENABLED=1): COINS_CONFIG_PATH=$COINS_CONFIG_PATH → супервизор движка"
    engine_supervise &
  else
    start_engine                 # флот/Персиваль: путь БАЙТ-В-БАЙТ прежний (COINS_CONFIG_PATH не задан)
  fi
  start_scout_if_enabled
  # Адаптер — foreground (PID 1-логика). stop_close встаёт → процесс выходит (restartPolicy=never).
  exec python -m app.main
}

# main запускается ТОЛЬКО при ПРЯМОМ вызове (CMD ["./start.sh"]); при `. start.sh` в тестах/прогонах
# исполняются лишь определения функций (движок/адаптер не поднимаются) — так доказываем (а)-(г) точечно.
case "$0" in
  *start.sh) main "$@" ;;
esac

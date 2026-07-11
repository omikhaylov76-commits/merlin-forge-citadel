# -*- coding: utf-8 -*-
"""app.cycle — торговый цикл на закрытии 4h-бара (Веха 5 ф.5.2 под-шаг 3c).

run_4h_cycle: один проход на 4h-закрытии — предохранители (конфиг/equity/kill-switch/Пауза, всё fail-closed)
→ по монетам: гейт «один сетап на монету» → fetch_4h_series → scan_signal (per-coin курсор по времени,
no-backfill) → СВЕЖИЙ сигнал (пробой = только что закрытый бар) → cap-гейт → place_setup → state.put.

Сканер РОЖДАЕТ сетап (parity vs движок, под-шаг 3b); ВЕДЁТ его lifecycle (под-шаг 4) — здесь не ведём.
Проводка в 15m-цикл (триггер по 4h-границе) — под-шаг 3d. Реальные ордера — ТОЛЬКО при
config.ops.LIVE_TRADING_ENABLED=True (дефолт OFF: dry-run, логируем «поставил БЫ», брокера не трогаем).
Курсор in-memory (сброс на рестарте = только свежие; персист → под-шаг 5). 15m-killswitch → под-шаг 5.
"""
import json
import time
from datetime import datetime, timezone

import numpy as np

import config
from state.config import ConfigError
from state.reconcile import read_resting_orders, diff_setup_vs_exchange
from market.klines_4h import fetch_4h_series, is_4h_close, FOUR_HOUR_MS, FIFTEEN_MIN_MS
from strategy.scanner import scan_signal
from strategy import warm
from strategy.candidates import forming_candidate
from execution import lifecycle as LC
from execution.actions import setup_from_signal, close as make_close, LV, PENDING, OPEN, CLOSE, REBUILD, NONE, SKIP_FILLED, REPRICE_ENTRY
from risk_capital import killswitch, refinance
from risk_capital.concurrency import can_place_leg
from risk_capital.sizing import make_sizing_callback
from risk_capital.providers import make_risk_pct_provider

# под-шаг 5.7 п.5: порог «долгого простоя» для тревоги в _compound_realized (курсор старше → сверь working вручную)
IDLE_GAP_MS = 7 * 24 * 3600 * 1000
# dashboard_live_glavnaya под-шаг 2: окно пере-чтения журнала закрытых (journal_sync). 14д — покрывает возраст demo
# (~8д) + self-heal пропущенных best-effort-записью; идемпотентно ⇒ пере-читать безопасно.
JOURNAL_WINDOW_MS = 14 * 24 * 3600 * 1000
# каденция journal_sync (троттл в _poll_tick): не чаще ~14 мин. На деле тик ~15м ⇒ синк ≈ каждый тик (~96/день),
# каждый = 2 непересекающихся 7д-окна ⇒ ~192 account-wide REST/день. Копейки (НЕ per-coin) — регрессии REST на 16
# монетах нет; троттл = страховка от бёрстов при частом тике.
JOURNAL_INTERVAL_MS = 14 * 60 * 1000


def _to_arrays(series):
    """Список закрытых 4h-свечей → numpy (o,h,l,c,t4). t4 = open-time в СЕКУНДАХ (движок ждёт сек; get_klines — мс)."""
    o = np.array([r["open"] for r in series], float)
    h = np.array([r["high"] for r in series], float)
    l = np.array([r["low"] for r in series], float)
    c = np.array([r["close"] for r in series], float)
    t4 = np.array([r["time"] // 1000 for r in series], dtype=np.int64)
    return o, h, l, c, t4


def _configure_executor(executor, eff, ledger, working_provider):
    """Обновить долгоживущий executor из ЭФФЕКТИВНОГО конфига: sl_trigger_by + sizing (working-провайдер +
    alarm-aware risk% + потолок плеча per coin). Общий для 4h-цикла и warm-старта — sizing пере-создаётся
    каждый вызов (executor долгоживущий, self.sizing перезаписывается; поздней привязки eff нет)."""
    executor.sl_trigger_by = eff["SL_TRIGGER_BY"]
    executor.sizing = make_sizing_callback(
        working_provider,
        risk_pct_provider=make_risk_pct_provider(
            ledger, risk_pct=eff["RISK_PCT_PER_LEG"], risk_pct_alarm=eff["RISK_PCT_ALARM"]),
        max_leverage_for=lambda s: min(
            eff["MAX_LEVERAGE"], config.strategy.COINS_CONFIG.get(s, {}).get("leverage", eff["MAX_LEVERAGE"])),
    )


def _commit_place(state, executor, s, setup, logger, *, label):
    """Общий ХВОСТ постановки сетапа (переиспользуют _scan_and_place и warm_start_auto). Возврат: True —
    сетап РЕАЛЬНО поставлен (≥1 нога на бирже); False — dry-run / нет размещаемых ног / постановка не удалась.

    Инвариант 5.7: WRITE-AHEAD карта (state.put с link_id+qty) ДО ордеров → нет сироты «ордер без карты»;
    при неудаче карта снимается. LIVE-гейт внутри (OFF → лог «поставил БЫ», брокер не трогается). label —
    человекочитаемое описание для лога (напр. «jc=648 side=long» / «warm age=5 side=long»); side берётся из
    КАРТЫ (setup['side']), НЕ из sig (у warm sig нет). _log_orders_open (панель «ждущие») — ТОЛЬКО при успехе;
    событие setup_placed и итоговый info-лог — на ВЫЗЫВАЮЩЕМ, ПОД возвращённым флагом (не логировать в dry-run)."""
    if not config.ops.LIVE_TRADING_ENABLED:               # предохранитель: dry-run, без брокера
        logger.info("%s: [DRY-RUN] поставил БЫ сетап (%s) — LIVE_TRADING_ENABLED=0", s, label)
        return False
    # причину «почему 0 ног» считаем ДО presize: presize зануляет leg["qty"] у отвергнутых ног, и в режиме
    # sizing=None причина исказилась бы в no_size (ревью подшага 2). На боевом пути sizing задан и порядок не
    # важен, но так надёжно при любом режиме; лишний sizing-проход дёшев и только при постановке (редко).
    unplaceable = executor.explain_unplaceable(s, setup)
    if executor.presize(s, setup) is None:                # 5.7 п.2: sizing → нет размещаемых ног (карту не пишем)
        # fail-loud: НЕ глотаем — называем ПРИЧИНУ (в жизни чаще min_qty от обнулённого working, реже min_notional).
        logger.warning("%s: ни одной ноги не размещаемо (%s) — монета эффективно НЕ торгуется на текущем working/risk",
                       s, unplaceable)
        return False
    state.put(s, setup)                                   # WRITE-AHEAD: карта с link_id+qty ДО ордеров → нет сироты «ордер без карты»
    placed = executor.place_setup(s, setup)
    if placed is None:                                    # постановка не удалась (сеть) → снять write-ahead карту (не висеть PENDING)
        state.clear(s)
        logger.warning("%s: ни одной ноги не поставлено → карта снята", s)
        return False
    state.put(s, placed)                                  # обновить order_id (карта уже есть; идемпотентно)
    _log_orders_open(state.db, s, placed, logger=logger)  # панель «ждущие»: свежий сетап виден до 1-го тика (5.4d)
    return True


def run_4h_cycle(broker, state, cfg, ledger, executor, working_provider, symbols, cursors, *, logger):
    """Один проход торгового цикла на 4h-закрытии. cursors — in-memory dict {symbol: cursor_time(сек)|None}
    (мутируется на месте). Реальные ордера ТОЛЬКО при config.ops.LIVE_TRADING_ENABLED (иначе dry-run-лог)."""
    # ── 1. КОНФИГ (strict: перепроверка кросс-кноб DD). Любой сбой здесь → не торгуем (fail-closed) ──
    try:
        eff = cfg.effective(strict=True)
    except (ConfigError, KeyError, ValueError, TypeError, AttributeError) as e:
        logger.error("4h-цикл пропущен: конфиг невалиден (%s) → не торгуем", e)
        return

    # ── 2. ПРЕДУСЛОВИЯ: леджер засеян + Пауза ──
    snap = ledger.get()
    if not snap or snap.get("working") is None:
        logger.error("4h-цикл пропущен: леджер не засеян → не торгуем")
        return

    # ── 2.5 КАПИТАЛ-БУХГАЛТЕРИЯ — parity-нейтральна, НЕЗАВИСИМА от гейтов: компаунд реализованного PnL (5a) →
    # месячный рефинанс (5b). Свежий working из компаунда видят и рефинанс, и сайзинг ниже. kill-switch evaluate
    # ВЫНЕСЕН в 15m-контур (_maybe_15m_killswitch — КАЖДЫЙ тик, включая 4h-границу и паузу): здесь только eq
    # для fail-closed + гейт is_halted. 5.7 п.4: убран двойной инкремент stop_streak на 4h-граничном тике
    # (15m+4h читали одну equity-эпоху → дебаунс защёлкивал бы с 1-го кривого чтения). ──
    _compound_realized(broker, ledger, logger)
    refinance.run_if_due(datetime.now(timezone.utc), ledger, split=eff["REFINANCE_SPLIT"])
    eq = killswitch.safe_equity(broker.get_equity_usdt())   # только для fail-closed гейта ниже (латч/HWM ведёт 15m-контур)

    # ── 3. ГЕЙТЫ ПОСТАНОВКИ (блокируют ТОЛЬКО новые сетапы; бухгалтерия выше уже сделана) ──
    if eff["PAUSE_ENABLED"]:
        logger.warning("4h-цикл: Пауза включена (ADR 0011) → новые сетапы не ставим")
        return
    if eq is None:                                         # fail-closed: без equity новые ноги не ставим
        logger.warning("4h-цикл: equity недоступна (fail-closed) → не торгуем")
        return
    if killswitch.is_halted(ledger.store):
        logger.warning("4h-цикл: kill-switch активен (защёлка) → не торгуем")
        return

    # ── 4. ОБНОВИТЬ долгоживущий executor из ЭФФЕКТИВНОГО конфига (свежий working после компаунда) ──
    _configure_executor(executor, eff, ledger, working_provider)

    # ── 5. ПО МОНЕТАМ (ошибка по монете не валит цикл) ──
    for s in symbols:
        try:
            _scan_and_place(broker, state, executor, eff, s, cursors, logger=logger)
        except Exception as e:                              # сеть/данные по монете → пропуск монеты
            logger.warning("%s: 4h-цикл пропущен по монете (%s)", s, e)


def _scan_and_place(broker, state, executor, eff, s, cursors, *, logger):
    if state.has_active(s):                                 # ГЕЙТ «один сетап на монету» (= движок)
        return
    series = fetch_4h_series(broker, s, logger=logger)
    if series is None:                                     # нет/коротко данных → пропуск
        return
    o, h, l, c, t4 = _to_arrays(series)
    n = len(c)

    cur = cursors.get(s)
    if cur is None:                                        # ПРАЙМ: смотрим «отсюда», без сделок (no-backfill)
        cursors[s] = int(t4[-1])
        return
    start_i = int(np.searchsorted(t4, cur, side="right"))  # первый бар СТРОГО после метки
    res = scan_signal(o, h, l, c, t4, s, start_i=start_i,
                      ema_enabled=eff["EMA_FILTER_ENABLED"], shorts_enabled=eff["SHORTS_ENABLED"],
                      stop_fib=eff["STOP_FIB"])
    if res is None:                                        # нет рождения → метку НЕ двигаем (консолидация зреет)
        return
    sig, jc, _next_i = res
    if jc != n - 1:                                        # несвежий (после простоя) → ресинк на «сейчас», skip
        cursors[s] = int(t4[-1])
        logger.info("%s: несвежий сигнал jc=%d пропущен (no-backfill, ресинк)", s, jc)
        return
    cursors[s] = int(t4[jc])                               # свежий: метку двигаем за рождение
    _log_signal(state.db, s, sig, logger=logger)          # монитор: рождение сигнала (ДО cap/LIVE-гейтов — не теряем)

    if not can_place_leg(state.all().values(), eff["CONCURRENCY_CAP"]):
        logger.info("%s: cap=%d исчерпан → сетап не ставим", s, eff["CONCURRENCY_CAP"])
        return

    setup = setup_from_signal(sig)
    label = "jc=%d side=%s" % (jc, sig["side"])
    if _commit_place(state, executor, s, setup, logger, label=label):     # write-ahead+place (общий хвост); dry-run/неудача → False
        _log_event(state.db, s, "setup_placed", label, logger=logger)     # событие монитора (5.4c) — ТОЛЬКО при реальной постановке
        logger.info("%s: сетап ПОСТАВЛЕН (%s)", s, label)


# ── авто-прогрев тёплого старта (под-шаг 3b, ADR 0013) ───────────────────────
def _placed_leg_count(setup):
    """Число ПОСТАВЛЕННЫХ ног сетапа (state ∈ {PENDING, OPEN}) — для cap warm (open+pending, не только OPEN)."""
    return sum(1 for leg in setup["legs"].values() if leg.get("state") in (PENDING, OPEN))


def _warm_gate(eff, state, ledger, broker):
    """Общие safety-гейты warm-постановки (после конфига): леджер засеян / Пауза / equity fail-closed /
    kill-switch / непогашенное «Закрыть всё». -> причина-строка (блок) | None (можно). Общий для авто и кнопки.
    «Закрыть всё»: на рестарте ДО обработки flatten Пауза ещё не выставлена — warm иначе поставил бы то, что
    оператор просил ЗАКРЫТЬ (первый тик отменил бы; но лишний place/cancel + противоречие намерению)."""
    snap = ledger.get()
    if not snap or snap.get("working") is None:
        return "леджер не засеян"
    if eff["PAUSE_ENABLED"]:
        return "Пауза включена (ADR 0011)"
    if killswitch.safe_equity(broker.get_equity_usdt()) is None:   # свой REST (на старте _last_eq_raw ещё None)
        return "equity недоступна (fail-closed)"
    if killswitch.is_halted(ledger.store):                          # durable kill-switch-латч (переживает рестарт)
        return "kill-switch активен"
    latest_ca = state.db.config_log_latest("CLOSE_ALL")
    if latest_ca is not None:
        ack = ledger.store.get_close_all_ack()
        if ack is None or ack < latest_ca["id"]:
            return "непогашенное «Закрыть всё»"
    return None


def _warm_fetch_classify(broker, eff, s, *, logger):
    """Свежая 4h-серия монеты → classify с эффективными крутилками. -> (desc|None, t4|None)."""
    series = fetch_4h_series(broker, s, logger=logger)
    if series is None:
        return None, None
    o, h, l, c, t4 = _to_arrays(series)
    desc = warm.classify(o, h, l, c, t4, s,
                         ema_enabled=eff["EMA_FILTER_ENABLED"], shorts_enabled=eff["SHORTS_ENABLED"],
                         stop_fib=eff["STOP_FIB"], max_age_bars=eff["WARM_MAX_AGE_BARS"])
    return desc, t4


def _warm_cap_ok(state, eff):
    """Влезает ли ещё ОДИН полный warm-сетап (3 ноги) в cap по ВСЕМ поставленным ногам (open+pending)?
    can_place_leg считает лишь OPEN, а warm-PENDING его НЕ насыщают → warm поставил бы на всех монетах разом
    сверх cap (аудит C1). state.all() пере-читывается каждый вызов → счётчик растёт по мере постановки."""
    placed = sum(_placed_leg_count(su) for su in state.all().values())
    return placed + len(LV) <= eff["CONCURRENCY_CAP"]


def _warm_place(state, executor, s, desc, t4, cursors, *, logger):
    """Общий хвост warm-постановки: build_setup → _commit_place (write-ahead+LIVE-гейт) → курсор+событие.
    -> 1|0 (реально поставлено). Событие setup_placed (тот же тип, что цикл — виден монитору)."""
    setup = warm.build_setup(desc)
    label = "warm %s age=%d side=%s" % (desc["kind"], desc["age_bars"], desc["side"])
    if _commit_place(state, executor, s, setup, logger, label=label):
        cursors[s] = int(t4[-1])                          # детерминизм курсора: прайм «отсюда» (не оставлять None)
        _log_event(state.db, s, "setup_placed", label, logger=logger)
        logger.info("%s: WARM-сетап ПОСТАВЛЕН (%s)", s, label)
        return 1
    return 0


def warm_start_auto(broker, state, cfg, ledger, executor, working_provider, symbols, cursors, *, logger):
    """Авто-подхват живых сетапов на старте (Веха 5.8 под-шаг 3b, ADR 0013): при WARM_ON_START прогреть
    ТОЛЬКО auto_eligible (нетронутый PENDING) кандидатов. Гейты — WARM_ON_START первым + общий `_warm_gate`.
    Идемпотентно (has_active→skip; рестарт — reconcile → has_active). Сеть per-coin fail-soft — не валит старт."""
    try:
        eff = cfg.effective(strict=True)
    except (ConfigError, KeyError, ValueError, TypeError, AttributeError) as e:
        logger.error("warm-старт пропущен: конфиг невалиден (%s)", e)
        return
    if not eff["WARM_ON_START"]:                          # ПЕРВЫМ (дефолт False → чистый no-op, без сети)
        return
    reason = _warm_gate(eff, state, ledger, broker)
    if reason is not None:
        logger.warning("warm-старт: %s → прогрев блокирован", reason)
        return
    _configure_executor(executor, eff, ledger, working_provider)   # иначе executor.sizing=None → пустая постановка
    n = 0
    for s in symbols:                                     # ошибка/сеть по монете НЕ валит старт
        try:
            n += _warm_one(broker, state, executor, eff, s, cursors, logger=logger)
        except Exception as e:
            logger.warning("%s: warm-старт пропущен по монете (%s)", s, e)
    if n:
        logger.info("warm-старт: подхвачено %d сетап(ов)", n)


def _warm_one(broker, state, executor, eff, s, cursors, *, logger):
    """АВТО-кандидат: ТОЛЬКО auto_eligible (нетронутый PENDING, ADR 0013) → cap → постановка. -> 1|0."""
    if state.has_active(s):                               # гейт «один сетап на монету» (идемпотентность)
        return 0
    desc, t4 = _warm_fetch_classify(broker, eff, s, logger=logger)
    if desc is None or not desc["auto_eligible"]:
        return 0
    if not _warm_cap_ok(state, eff):
        logger.info("%s: cap=%d — warm-сетап не влезает → пропуск", s, eff["CONCURRENCY_CAP"])
        return 0
    return _warm_place(state, executor, s, desc, t4, cursors, logger=logger)


# ── консьюмер кнопки «Прогреть выбранные» (durable-намерение WARM_APPLY, под-шаг 4b) ──
def _parse_warm_approved(detail):
    """Список одобренных монет из detail WARM_APPLY. Контракт producer (дашборд): CSV «BTC,ETH» ИЛИ JSON-массив
    строк. Начинается с '[' → JSON-массив (битый/не-список → []); иначе CSV. Пусто → []."""
    if not detail:
        return []
    s = str(detail).strip()
    if s[:1] in ("[", "{"):                               # JSON (по контракту — массив строк; не-список → [])
        try:
            val = json.loads(s)
        except (ValueError, TypeError):
            return []
        return [str(x).strip() for x in val if str(x).strip()] if isinstance(val, list) else []
    return [p.strip() for p in s.split(",") if p.strip()]  # CSV


def _warm_one_button(broker, state, executor, eff, s, cursors, *, logger):
    """КНОПОЧНЫЙ кандидат: любой PENDING (человек вёттил, вкл. пере-якоренный — НЕ только auto_eligible) →
    cap → постановка. OPEN → skip (вход по рынку — бэклог, нет executor-пути; решение владельца 2026-07-02). -> 1|0."""
    if state.has_active(s):
        return 0
    desc, t4 = _warm_fetch_classify(broker, eff, s, logger=logger)
    if desc is None:
        logger.info("%s: WARM_APPLY — уже не кандидат → skip", s)
        return 0
    if desc["kind"] != warm.PENDING:                      # OPEN → рыночный вход в бэклоге
        logger.info("%s: WARM_APPLY — OPEN-кандидат (вход по рынку в бэклоге) → skip", s)
        return 0
    if not _warm_cap_ok(state, eff):
        logger.info("%s: cap=%d — WARM_APPLY-сетап не влезает → пропуск", s, eff["CONCURRENCY_CAP"])
        return 0
    return _warm_place(state, executor, s, desc, t4, cursors, logger=logger)


def maybe_warm(broker, state, cfg, ledger, executor, working_provider, symbols, cursors, *, logger):
    """Консьюмер кнопки «Прогреть выбранные» (Веха 5.8 п.4b). При НОВОМ durable-намерении WARM_APPLY (config_log
    новее warm-ack) греет ОДОБРЕННЫЕ монеты (PENDING; OPEN — бэклог). Зовётся каждый 15m-тик. Идемпотентно (ack-гейт).

    SINGLE-SHOT (НЕ ретраит): намерение исполняется ОДИН раз и гасится (ack сдвигается) при ЛЮБОМ исходе —
    и safety-гейт-блок (Пауза/kill/equity/«Закрыть всё»/битый конфиг), и частичный недобор (сеть моргнула /
    монета уже не кандидат / cap). Не прогретые монеты оператор ПЕРЕЖИМАЕТ кнопкой (has_active НЕ задваивает уже
    прогретые). Это подходит кнопке ПОД НАДЗОРОМ (в отличие от CLOSE_ALL, где ретрай нужен безнадзорной
    безопасности — там сбой close БРОСАЕТ; здесь fetch/equity fail-soft возвращают None, «ретрай» был бы мнимым).
    Денежные инварианты: двойной постановки нет (has_active + write-ahead _commit_place); «выстрел позже» закрыт
    (намерение гасится в тот же тик, стойкое состояние не оживает)."""
    store = ledger.store
    latest = state.db.config_log_latest("WARM_APPLY")
    if latest is None:
        return
    ack = store.get_warm_ack()
    if ack is not None and ack >= latest["id"]:
        return                                            # намерение уже исполнено (идемпотентность)
    try:
        eff = cfg.effective(strict=True)
    except (ConfigError, KeyError, ValueError, TypeError, AttributeError) as e:
        store.set_warm_ack(latest["id"])                  # битый конфиг → дроп намерения (оператор нажмёт заново)
        logger.warning("WARM_APPLY отклонён: конфиг невалиден (%s) → сброшено", e)
        return
    reason = _warm_gate(eff, state, ledger, broker)
    if reason is not None:                                # safety-гейт → ДРОП намерения (не висеть/не выстрелить позже)
        store.set_warm_ack(latest["id"])
        logger.warning("WARM_APPLY отклонён: %s → сброшено (нажмите заново)", reason)
        _log_event(state.db, "ALL", "warm_apply", "отклонён: %s" % reason, logger=logger)
        return
    approved = _parse_warm_approved(latest.get("new"))
    _configure_executor(executor, eff, ledger, working_provider)
    n = 0
    for s in approved:
        if s not in symbols:                              # монета вне конфига → игнор
            continue
        try:
            n += _warm_one_button(broker, state, executor, eff, s, cursors, logger=logger)
        except Exception as e:                            # сбой по монете (сеть/данные) → монета не прогрета (single-shot)
            logger.warning("%s: WARM_APPLY по монете не прошёл (не прогрета, нажмите заново): %s", s, e)
    store.set_warm_ack(latest["id"])                      # ИСПОЛНЕНО (single-shot): непрогретые монеты — оператор пережмёт
    _log_event(state.db, "ALL", "warm_apply", "прогрето %d из %d одобренных" % (n, len(approved)), logger=logger)
    logger.info("WARM_APPLY исполнен → прогрето %d из %d (ack=%d)", n, len(approved), latest["id"])


def write_warm_candidates(broker, state, cfg, symbols, *, logger):
    """Снимок ТЕКУЩИХ warm-кандидатов в БД (`warm_candidates`) — для превью дашборда (Веха 5.8 п.4a, кнопка 5).
    Обновляется на 4h-границе (кандидаты меняются на закрытии 4h-бара). НЕ гейтится WARM_ON_START/LIVE/Паузой —
    ТОЛЬКО чтение (classify + запись снимка, без ордеров), чтобы оператор всегда видел актуальные кандидаты.
    По монете БЕЗ активного сетапа: classify → put(дескриптор, вкл. PENDING И OPEN)|clear; с активным сетапом →
    clear (не кандидат — уже ведётся). Сеть per-coin fail-soft — битая монета НЕ валит снимок/цикл."""
    try:
        eff = cfg.effective(strict=True)
    except (ConfigError, KeyError, ValueError, TypeError, AttributeError) as e:
        logger.warning("снимок warm-кандидатов пропущен: конфиг невалиден (%s)", e)
        return
    for s in symbols:
        try:
            if state.has_active(s):
                state.db.warm_candidates_clear(s)             # монета ведётся → не кандидат
                continue
            series = fetch_4h_series(broker, s, logger=logger)
            if series is None:
                state.db.warm_candidates_clear(s)
                continue
            o, h, l, c, t4 = _to_arrays(series)
            desc = warm.classify(o, h, l, c, t4, s,
                                 ema_enabled=eff["EMA_FILTER_ENABLED"], shorts_enabled=eff["SHORTS_ENABLED"],
                                 stop_fib=eff["STOP_FIB"], max_age_bars=eff["WARM_MAX_AGE_BARS"])
            if desc is None:
                state.db.warm_candidates_clear(s)
            else:
                state.db.warm_candidates_put(s, desc)
        except Exception as e:                                # сеть/данные по монете → пропуск (снимок best-effort)
            logger.warning("%s: снимок warm-кандидата пропущен (%s)", s, e)


def _signal_born_at_last(o, h, l, c, t4, s, eff):
    """True, если детектор РОДИЛ сигнал на ПОСЛЕДНЕМ 4h-баре (jc==n-1) — как «свежий» в run_4h_cycle, но
    cursor-НЕЗАВИСИМО (снимок переживает рестарт/курсоры). Перебирает рождения слева направо через scan_signal
    (start двигается за каждый пробой → терминируется). Гейты EMA/shorts — как в живом цикле (eff-крутилки)."""
    n = len(c)
    start = 1
    while True:
        res = scan_signal(o, h, l, c, t4, s, start_i=start,
                          ema_enabled=eff["EMA_FILTER_ENABLED"], shorts_enabled=eff["SHORTS_ENABLED"],
                          stop_fib=eff["STOP_FIB"])
        if res is None:
            return False
        _sig, jc, next_i = res
        if jc == n - 1:
            return True
        start = next_i


def write_scan_snapshot(broker, state, cfg, symbols, *, now_ms, logger):
    """Снимок ПОСЛЕДНЕГО 4h-скана в БД (`scan_snapshot`) — карточка «Здоровье и работа бота» (bot_health 2b/3).
    Обновляется на 4h-границе. ТОЛЬКО чтение (зонд + детектор, без ордеров), тем же путём, что write_warm_candidates:
    по монете fetch_4h_series → forming_candidate (греётся?) + _signal_born_at_last (родился ли сигнал на послед.
    баре). Сеть per-coin fail-soft. Движок/зонд НЕ трогаем. Дублирует fetch 4h-серий (once/4h — перф-хвост)."""
    try:
        eff = cfg.effective(strict=True)
    except (ConfigError, KeyError, ValueError, TypeError, AttributeError) as e:
        logger.warning("снимок скана пропущен: конфиг невалиден (%s)", e)
        return
    coins_scanned = signals_found = 0
    candidates = []
    for s in symbols:
        try:
            series = fetch_4h_series(broker, s, logger=logger)
            if series is None:                                # нет/коротко данных → не считаем проверенной
                continue
            o, h, l, c, t4 = _to_arrays(series)
            coins_scanned += 1
            mb1 = (config.strategy.COINS_CONFIG.get(s) or {}).get("mb1")
            if mb1 is not None:
                cand = forming_candidate(o, h, l, c, mb1=mb1)
                if cand is not None:                          # numpy→float для JSON; проценты округлены под показ
                    candidates.append({
                        "symbol": s,
                        "consolidation_bars": int(cand["consolidation_bars"]),
                        "breakout_dist_pct": round(float(cand["breakout_dist_pct"]), 2),
                        "cancel_dist_pct": round(float(cand["cancel_dist_pct"]), 2),
                        "breakout_level": float(cand["breakout_level"]),
                    })
            if _signal_born_at_last(o, h, l, c, t4, s, eff):
                signals_found += 1
        except Exception as e:                                # сеть/данные по монете → пропуск (снимок best-effort)
            logger.warning("%s: снимок скана пропущен (%s)", s, e)
    try:
        state.db.scan_snapshot_put(coins_scanned=coins_scanned, signals_found=signals_found,
                                   candidates=candidates, now_ms=now_ms)
    except Exception as e:
        logger.warning("снимок скана не записан: %s", e)


# ── 15m-ведение опросом (под-шаги 4a poll-diff + 4b on_bar_close) ─────────────
def run_15m_tick(broker, state, executor, symbol, net, cursors, candles, closed_window, *, now_ms, logger,
                 reanchor_after_scalp=False, runner_tp_hold=False, leg2_ext=None, cond05=None, tol05=0.0,
                 trail_r=0.0, position=None):
    """Один 15m-тик ведения по монете: (4a) свести карточку с фактом биржи (poll-diff fill/exit) → on_fill;
    (4b) прогнать on_bar_close по КАЖДОЙ новой закрытой 15m-свече (pre-commit reanchor / beyond_B / timeout).
    Реальные ордера ТОЛЬКО при config.ops.LIVE_TRADING_ENABLED. На завершении (completion/timeout) — финализация:
    state.clear + сдвиг per-coin курсора за 4h-период (обязательство 3b). База poll-диффа = САМА карточка
    (рестарт-безопасно). candles — новые закрытые 15m этого тика (ASC); closed_window — окно 15m (4h-агрегат)."""
    setup = state.get(symbol)
    if setup is None:
        return
    _log_orders_open(state.db, symbol, setup, logger=logger)  # панель «ждущие»: рефреш снимка карточки (5.4d)
    # ── 4a: снимок НАШИХ стоящих ордеров ОДИН раз ДО любого execute — иначе исчезновение линка не отличить
    # от нашего же cancel/rebuild позже в тике. net — снимок позиции этого тика (из _poll_tick, один на тик).
    live = read_resting_orders(broker, symbol, executor.prefix)
    entries, exits = diff_setup_vs_exchange(
        setup, live["ent"], set(live["pool"]), float(net),
        link_of=lambda lv, role: executor._link(symbol, lv, role, setup.get("gen")))

    # граница 15m ОБНАРУЖЕНИЯ залива/выхода опросом (не wall-clock now_ms — без джиттера планировщика/downtime):
    # знаменатель офлайн-замера края WS (5.2 п6), лаг = detect_bar_ms − ws_exec.exec_time_ms ∈ [0, 15m].
    detect_bar_ms = (int(now_ms) // FIFTEEN_MIN_MS) * FIFTEEN_MIN_MS
    for lv in entries:                                     # заливы (мелкая→глубокая; commit-латч/каскад — в on_fill)
        leg = setup["legs"].get(lv) or {}
        action = state.mark_filled(symbol, leg.get("link_id"), kind="entry",
                                   runner_tp_hold=runner_tp_hold, leg2_ext=leg2_ext,
                                   cond05=cond05, tol05=tol05, trail_r=trail_r)
        if action is not None:                             # реальный переход (идемпотентно) → лог залива монитору
            _log_fill(state.db, symbol, setup.get("side"), lv, leg, detect_bar_ms=detect_bar_ms, logger=logger)
        _exec_action(executor, state, symbol, action, logger)

    for lv, role, price, exit_link in exits:               # выходы (price — с уровня карточки, знак profit_taken)
        action = state.mark_filled(symbol, kind="exit", lv=lv, price=price,
                                   runner_tp_hold=runner_tp_hold, leg2_ext=leg2_ext,
                                   cond05=cond05, tol05=tol05, trail_r=trail_r)
        if action is None or action.kind == CLOSE:
            continue                                       # CLOSE — единая финализация (_finalize_if_complete)
        leg = setup["legs"].get(lv) or {}
        _log_event(state.db, symbol, "leg_exit", "lv=%s %s @ %s" % (lv, role, price),
                   ts_ms=detect_bar_ms, logger=logger,     # + структурный ключ выхода для Стадии B (ws_stage_b_preconditions)
                   exit_link=exit_link, lv=lv, role=role, qty=leg.get("qty"))
        _exec_action(executor, state, symbol, action, logger)

    if _finalize_if_complete(state, executor, symbol, cursors, now_ms, logger):
        return                                             # сетап завершён poll-diff'ом (или ретрай упавшего close)

    # ── 4b: ведение по закрытым 15m-свечам (reanchor/beyond_B/timeout), хронологически ──
    for candle in candles:
        if state.get(symbol) is None:                      # завершён на предыдущей свече этого тика
            return
        if _drive_bar_close(state, executor, symbol, candle, closed_window, cursors, now_ms, logger,
                            reanchor_after_scalp=reanchor_after_scalp, runner_tp_hold=runner_tp_hold, leg2_ext=leg2_ext,
                            cond05=cond05, tol05=tol05, trail_r=trail_r):
            return                                         # timeout/completion на этой свече → финализирован

    # R8 путь Y: армировать нативный трейлер соло-бегунка (beyond_B/соло проставлены заливами+свечами этого тика)
    _maybe_arm_trailer(executor, state, symbol, trail_r, leg2_ext, position, logger)

    # инвариант Σopen≈net: остаток без линка-выхода (не флэт) → лог D3 (пер-ножное разложение в backlog)
    cur = state.get(symbol)
    if cur is not None:
        oq = sum((cur["legs"][lv].get("qty") or 0.0) for lv in cur["legs"] if cur["legs"][lv].get("state") == OPEN)
        if tol_below(float(net), oq):
            logger.warning("%s: нетто %.10g < открытых ног %.10g без линка-выхода — пер-ножное разложение → "
                           "backlog D3 (биржа=арбитр на флэте)", symbol, float(net), oq)


def _finalize_if_complete(state, executor, symbol, cursors, now_ms, logger):
    """ЕДИНАЯ candle-НЕЗАВИСИМАЯ точка завершения (ретрай-безопасна, идемпотентна). Финализирует, если:
      • `lifecycle._is_complete` (канонический предикат движка — не дублируем, иначе дрейф parity); ЛИБО
      • **таймаут-72 наступил** (committed ∧ wait_postcommit≥TIMEOUT_BARS ∧ есть открытые) — on_bar_close на
        timeout НЕ флипает leg.state, поэтому `_is_complete` его НЕ ловит; без этой ветки упавший timeout-close
        завис бы навсегда (`fetch_new_closed` не пере-эмитит 4h-свечу). Выводится из карты КАЖДЫЙ тик → ретрай
        упавшего close без свечи. reduce-only страхует повторный close. -> True, если финализирован."""
    cur = state.get(symbol)
    if cur is None:
        return False
    complete = LC._is_complete(cur)
    timed_out = (cur.get("committed")
                 and cur.get("wait_postcommit", 0) >= config.execution.TIMEOUT_BARS
                 and any(cur["legs"][lv].get("state") == OPEN for lv in LV))
    if not complete and not timed_out:
        return False
    still_open = [lv for lv in LV if cur["legs"][lv].get("state") == OPEN]
    reason = "complete" if complete else "timeout"
    _exec_action(executor, state, symbol, make_close(still_open, reason), logger)
    _finalize_closed_setup(state, symbol, cursors, now_ms, logger)
    _log_event(state.db, symbol, "setup_closed", reason, logger=logger)         # событие монитора (5.4c)
    return True


def _drive_bar_close(state, executor, symbol, candle, closed_window, cursors, now_ms, logger,
                     reanchor_after_scalp=False, runner_tp_hold=False, leg2_ext=None, cond05=None, tol05=0.0,
                     trail_r=0.0):
    """on_bar_close для ОДНОЙ закрытой 15m-свечи (+ 4h-агрегатный вызов, если свеча закрывает 4h-период).
    Зеркалит оракул tests/test_lifecycle_parity:85-125: per-15m (is_4h_close=False, геометрия бара) → REBUILD
    обрывает остаток бара; на 4h-границе — отдельный вызов (is_4h_close=True, 4h-агрегат) для timeout-72.
    Завершение (completion/timeout) — через `_finalize_if_complete` (ЕДИНАЯ точка, без двойного close).
    -> True, если сетап финализирован на этой свече."""
    setup = state.get(symbol)
    if setup is None:
        return True
    # (1) per-15m: pre-commit reanchor / beyond_B / retarget (геометрия 15m-бара)
    action = LC.on_bar_close(symbol, setup, {"high": candle["high"], "low": candle["low"], "is_4h_close": False},
                             reanchor_after_scalp=reanchor_after_scalp, runner_tp_hold=runner_tp_hold, leg2_ext=leg2_ext,
                             cond05=cond05, tol05=tol05, trail_r=trail_r)
    state.put(symbol, setup)                               # персист (beyond_B/targets мутированы in-place)
    _exec_action(executor, state, symbol, action, logger)
    if action.kind == REBUILD:                             # пере-якорь → новая сетка, ПРОПУСТИТЬ остаток бара (oracle:95-96)
        return False
    if _finalize_if_complete(state, executor, symbol, cursors, now_ms, logger):
        return True                                       # completion мог залатчиться на этом per-15m баре
    # (2) 4h-граница: отдельный вызов с 4h-агрегатом — timeout-72 (is_4h_close=True; committed → post-commit)
    if not is_4h_close(candle["time"]):
        return False
    setup = state.get(symbol)
    if setup is None:
        return True
    h4, l4 = _agg_4h(closed_window, candle)
    action = LC.on_bar_close(symbol, setup, {"high": h4, "low": l4, "is_4h_close": True},
                             reanchor_after_scalp=reanchor_after_scalp, runner_tp_hold=runner_tp_hold, leg2_ext=leg2_ext,
                             cond05=cond05, tol05=tol05, trail_r=trail_r)
    state.put(symbol, setup)                               # персист wait_postcommit++ ДО close → ретрай-точка, если close упадёт
    if action.kind != CLOSE:                              # retarget (beyond_B мог двинуть БУ-стоп); CLOSE(timeout) → ниже
        _exec_action(executor, state, symbol, action, logger)
    return _finalize_if_complete(state, executor, symbol, cursors, now_ms, logger)


# ── delta-курсор компаунд реализованного PnL (под-шаг 5a) ────────────────────
def _load_ids(blob):
    """JSON-множество orderId курсора → set (битый/пустой → пустой set)."""
    if not blob:
        return set()
    try:
        return set(json.loads(blob))
    except Exception:
        return set()


def _accept(r, last_ms, prev_ids):
    """Правило приёма строки closed-pnl на полле: строго новее курсора, ИЛИ на РАВНОМ ms но НЕ виденный
    orderId. Единственный корректный дедуп, когда вторичный ключ (orderId) неупорядочиваем/не уникален."""
    cm = r["created_ms"]
    return cm > last_ms or (cm == last_ms and str(r.get("order_id")) not in prev_ids)


def _compound_realized(broker, ledger, logger, now_ms=None):
    """Компаунд НОВЫХ закрытых сделок биржи в working по delta-курсору (5a). Идемпотентно (курсор персист
    → рестарт/ре-полл не задваивает); `{err}`/нет новых → working и курсор НЕ трогаем (fail-safe). Курсор
    НЕ засеян (None) → skip (boot.ensure_cursor_seeded штампует now_ms; защита от проглота истории now-7d).
    Бухгалтерия факта биржи — под `LIVE_TRADING_ENABLED` НЕ ходит (чтение, не постановка).
    5.7 п.5: пустое окно + курсор старше IDLE_GAP_MS → тревога «долгий простой» (working мог разойтись с
    биржей вне closed-pnl — фандинг/ручные операции; авто-пересчёта НЕТ, только ручная сверка). now_ms — для теста."""
    row = ledger.store.get()
    if row is None:
        return
    start = row.get("last_closed_ms")
    if start is None:                                       # не засеян → ждём boot-штамп; компаунд пропускаем
        logger.warning("компаунд: delta-курсор не засеян (None) → пропуск (boot.ensure_cursor_seeded штампует now_ms)")
        return
    rows = broker.get_closed_pnl_rows(start)
    if isinstance(rows, dict) and "err" in rows:           # сбой/усечение → НЕ компаундить, курсор не двигать
        logger.warning("компаунд: closed-pnl недоступен (%s) → пропуск цикла (курсор не сдвинут)", rows["err"])
        return
    prev_ids = _load_ids(row.get("last_closed_ids"))
    new = [r for r in rows if _accept(r, start, prev_ids)]
    if not new:
        # 5.7 п.5: пустое окно + курсор старше порога = «долгий простой». working/курсор НЕ трогаем (уже
        # безопасно), но громко тревожим — сверка working на операторе (авто-пересчёт рискован, 🟠D). Латч
        # mark_idle_gap_alerted: одна тревога на эпизод (курсор в простое не двигается → повтор молчит).
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        if start < now - IDLE_GAP_MS and ledger.mark_idle_gap_alerted(start):
            gap_days = (now - start) / 86_400_000
            logger.warning("компаунд: ДОЛГИЙ ПРОСТОЙ ~%.1fд (курсор старше %dд, новых сделок нет) — working мог "
                           "разойтись с биржей (фандинг/ручные операции); сверь working ВРУЧНУЮ (авто-пересчёта нет)",
                           gap_days, IDLE_GAP_MS // 86_400_000)
            _log_event(ledger.store.db, "ALL", "idle_gap", "простой ~%.0fд — сверь working" % gap_days, logger=logger)
        return
    _log_closed_trades(ledger.store.db, new, logger=logger)   # trade_history_pnl: журнал закрытых ДО учёта (изолирован, best-effort)
    delta = sum(r["closed_pnl"] for r in new)
    new_ms = max(r["created_ms"] for r in new)
    new_ids = {r["order_id"] for r in new if r["created_ms"] == new_ms}
    _, floored = ledger.apply_pnl_with_cursor(delta, new_ms, new_ids)
    logger.info("компаунд: %+.4f из %d закрытых сделок → working=%.2f (курсор→%d)",
                delta, len(new), ledger.get()["working"], new_ms)
    if floored:
        logger.warning("компаунд: working УШЁЛ В 0 (убыток > working) — сайзинг разместит 0 ног до пополнения; "
                       "проверь kill-switch (он мерит биржевую equity, не working)")


def _log_closed_trades(db, new_rows, *, logger):
    """Журнал ЗАКРЫТЫХ сделок (trade_history_pnl) — до-сохраняет РЕАЛЬНЫЕ Bybit closed-pnl строки, которые
    компаунд СЕЙЧАС учёл в working (тот же набор `new`, то же мультимножество). ИЗОЛИРОВАН (как observability-
    писатели 5.4c): сбой записи журнала НЕ ломает компаунд/бухгалтерию/торговлю — journal best-effort, деньги
    сакральны. Идемпотентно (closed_trade_put по dedup_key: ре-полл после краха не задваивает). side — СЫРАЯ
    сторона закрывающего ордера из closed-pnl (Sell для лонга); позиционную сторону для показа выводит дашборд.
    avg_entry/avg_exit/qty могут быть None (частичный дамп Bybit) — closed_trade_put это принимает."""
    try:
        n = 0
        for r in new_rows:
            n += db.closed_trade_put(
                created_ms=r.get("created_ms"), symbol=r.get("symbol"), side=r.get("side"),
                qty=r.get("qty"), avg_entry=r.get("avg_entry"), avg_exit=r.get("avg_exit"),
                closed_pnl=r.get("closed_pnl"), order_id=r.get("order_id"))
        if n:
            logger.info("журнал закрытых: +%d сделок (trade_history_pnl)", n)
    except Exception as ex:
        logger.warning("журнал закрытых сделок пропущен (компаунд НЕ задет): %s", ex)


def journal_sync(broker, db, logger, now_ms=None):
    """НЕЗАВИСИМЫЙ писатель журнала закрытых сделок (dashboard_live_glavnaya под-шаг 2): каждый вызов ЗАНОВО читает
    Bybit closed-pnl за окно JOURNAL_WINDOW_MS и upsert'ит в `closed_trades` (идемпотентно — closed_trade_put дедупит
    по стабильному ключу created_ms+order_id+closed_pnl). Чинит И ЗАДЕРЖКУ (зовётся на 15m-тике, не ждёт 4h-компаунд),
    И ПОЛНОТУ («не все сделки»: вытаскивает пропущенное best-effort-записью компаунда и до-бутовые). ⚠ НЕ ТРОГАЕТ
    money-леджер компаунда: last_closed_ms / working / apply_pnl_with_cursor здесь НЕ участвуют (журнал = дисплей-
    таблица, компаунд = леджер — граница священна). ИЗОЛИРОВАН: сбой (broker {err} / db-исключение) НЕ рейзит в тик
    (как observability-писатели 5.4c). journal = closed-pnl ТОЛЬКО: фандинг/комиссии в него НЕ попадают by design.
    now_ms — для теста."""
    try:
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        rows = broker.get_closed_pnl_rows(now - JOURNAL_WINDOW_MS)
        if isinstance(rows, dict) and "err" in rows:          # сбой/усечение выборки → журнал НЕ трогаем (изолир.)
            logger.warning("журнал-синк: closed-pnl недоступен (%s) → пропуск (журнал не тронут)", rows["err"])
            return
        n = 0
        for r in rows:
            try:                                              # ПО-СТРОЧНО: битая строка (created_ms=None/не-dict) пропускает СЕБЯ, не пачку
                n += db.closed_trade_put(
                    created_ms=r.get("created_ms"), symbol=r.get("symbol"), side=r.get("side"),
                    qty=r.get("qty"), avg_entry=r.get("avg_entry"), avg_exit=r.get("avg_exit"),
                    closed_pnl=r.get("closed_pnl"), order_id=r.get("order_id"))
            except Exception as ex:
                logger.warning("журнал-синк: строка пропущена (order_id=%s): %s",
                               r.get("order_id") if isinstance(r, dict) else "?", ex)
        if n:
            logger.info("журнал-синк: +%d новых закрытых (trade_history_pnl, окно %dд)",
                        n, JOURNAL_WINDOW_MS // 86_400_000)
    except Exception as ex:                                   # деньги/тик сакральны: журнал best-effort, сбой НЕ валит проход
        logger.warning("журнал-синк пропущен (тик/компаунд НЕ задет): %s", ex)


def _agg_4h(closed_window, candle):
    """4h-агрегат (high, low) периода, закрываемого `candle` = max/min 15m-баров окна в [period_open, period_end).
    period_end = candle.time + 15m (= 4h-граница). Окно не покрыло период (старт/гэп >50ч) → fallback на геометрию
    закрывающего бара (beyond_B уже залатчен per-15m, timeout от high/low не зависит → функц. безопасно)."""
    end_ms = int(candle["time"]) + FIFTEEN_MIN_MS
    start_ms = end_ms - FOUR_HOUR_MS
    period = [b for b in closed_window if start_ms <= b["time"] < end_ms]
    if not period:
        return candle["high"], candle["low"]
    return max(b["high"] for b in period), min(b["low"] for b in period)


def tol_below(net, open_qty, tol=1e-9):
    """net строго НИЖЕ открытых ног, но НЕ полный флэт (net>0) — необъяснённый остаток (backlog D3)."""
    return net > tol and net < open_qty - tol


def _exec_reprice(executor, state, symbol, action, logger):
    """REPRICE_ENTRY (двойной заход, 2b): WRITE-AHEAD карта (entry=thr,qty) ДО amend (инвариант 5.7, как
    _commit_place — кросс-крах не даёт незатрибученный залив) → executor.reprice_apply (amend + пере-читать
    ордер + откат на плоскую при кросс-снятии). LIVE-гейт; сам гейт/дедуп/qty — в reprice_plan (None → ордер
    оставлен как есть, ретрай след. тик)."""
    if not config.ops.LIVE_TRADING_ENABLED:
        logger.info("%s: [DRY-RUN] REPRICE_ENTRY — брокер не трогаем (LIVE_TRADING_ENABLED=0)", symbol)
        return
    setup = state.get(symbol)
    if setup is None:
        return
    lv = action.payload["lv"]
    plan = executor.reprice_plan(symbol, setup, lv, action.payload["price"])
    if plan is None:
        return
    leg = setup["legs"][lv]
    leg["entry"] = plan["thr"]
    leg["qty"] = plan["qty"]
    state.put(symbol, setup)                               # WRITE-AHEAD: карта = thr/qty ДО amend (5.7)
    result = executor.reprice_apply(symbol, setup, lv, plan)
    state.put(symbol, result if isinstance(result, dict) else setup)


def _exec_action(executor, state, symbol, action, logger):
    """Исполнить Action lifecycle на бирже ПОД предохранителем LIVE_TRADING_ENABLED. OFF → лог «сделал БЫ»,
    брокера НЕ трогаем (state уже мутирован on_fill под локом). Мутации executor (migrated/targets/closed)
    персистим (единственный писатель — воркер; гонок с дашбордом нет). Raise execute → пробрасываем (тик
    пропустится по монете в _poll_tick, финализация НЕ случится → ретрай след. тик)."""
    if action is None or action.kind in (NONE, SKIP_FILLED):
        return
    if action.kind == REPRICE_ENTRY:                       # двойной заход: свой write-ahead путь (не generic execute)
        _exec_reprice(executor, state, symbol, action, logger)
        return
    if not config.ops.LIVE_TRADING_ENABLED:
        logger.info("%s: [DRY-RUN] %s — брокер не трогаем (LIVE_TRADING_ENABLED=0)", symbol, action.kind)
        return
    cur = state.get(symbol)
    if cur is None:
        return
    result = executor.execute(symbol, cur, action)
    if isinstance(result, dict):                           # setup вернулся мутированным → персист (миграция/цели/closed)
        state.put(symbol, result)


def _maybe_arm_trailer(executor, state, symbol, trail_r, leg2_ext, position, logger):
    """R8 путь Y (C3): под LIVE-гейтом армировать нативный трейлер Bybit соло-бегунка (executor.maybe_arm_trailer).
    trail_r<=0 / dry-run → no-op (брокера не трогаем). Мутированный setup персистим (латч trail_armed переживёт
    рестарт; единственный писатель — воркёр). Сбой НЕ валит тик (маловероятно; свой лог внутри executor)."""
    if trail_r <= 0.0 or not config.ops.LIVE_TRADING_ENABLED:
        return
    setup = state.get(symbol)
    if setup is None:
        return
    result = executor.maybe_arm_trailer(symbol, setup, trail_r, leg2_ext, position)
    if isinstance(result, dict):
        state.put(symbol, result)


def _finalize_closed_setup(state, symbol, cursors, now_ms, logger):
    """Завершение сетапа: очистить карту + сдвинуть per-coin курсор за 4h-период закрытия (обязательство 3b:
    следующий скан стартует строго ПОСЛЕ — без перекрытий). Единый для complete (4a) и timeout (4b). Курсор
    в СЕКУНДАХ (как t4 в run_4h_cycle), выводится из времени тика (на 15m-драйве 4h-индекса t4[k] нет)."""
    state.clear(symbol)
    _clear_orders_open(state.db, symbol, logger=logger)   # панель «ждущие»: снять при финализации (5.4d) — единый чокпоинт
    four_h_open_ms = (int(now_ms) // FOUR_HOUR_MS) * FOUR_HOUR_MS
    cursors[symbol] = four_h_open_ms // 1000
    logger.info("%s: сетап завершён → карта очищена, курсор сдвинут на %d (сек)", symbol, cursors[symbol])


# ── энфорсмент «Закрыть всё» (под-шаг 5.3c) ──────────────────────────────────
def maybe_flatten_all(db, state, executor, cfg, ledger, cursors, *, now_ms, logger):
    """Энфорсмент «Закрыть всё» (тревожная кнопка дашборда). При НОВОМ durable-намерении (свежая config_log-
    строка CLOSE_ALL новее ack-курсора, 5.3b): АВТО-ПАУЗА (решение владельца) + рыночное reduce-only закрытие
    ВСЕХ активных сетапов + финализация (карта/курсор). Идемпотентно (ack-гейт + reduce-only), рестарт-безопасно
    (намерение durable, ack durable). Брокерские вызовы — централизованно под `LIVE_TRADING_ENABLED` (через
    `_exec_action`, как completion/timeout-close). Зовётся каждый 15m-тик из app.main._poll_tick (ДО ведения).

    Порядок: ПАУЗА ставится сразу (идемпотентно), ack — ПОСЛЕДНИМ и ТОЛЬКО при полном успехе (любой close упал →
    ack не сдвинут → ретрай след. тик; ПАУЗА уже держит новые сетапы). Закрытый сетап финализируется (`state.clear`),
    поэтому тот же тик `run_15m_tick` по этой монете → no-op."""
    store = ledger.store
    latest = db.config_log_latest("CLOSE_ALL")
    if latest is None:
        return
    ack = store.get_close_all_ack()
    if ack is not None and ack >= latest["id"]:
        return                                              # намерение уже исполнено (идемпотентность)

    cfg.set("PAUSE_ENABLED", True, source="action")         # АВТО-ПАУЗА (old==new → no-op, без journal-спама)
    all_ok, n = True, 0
    for symbol in list(state.all().keys()):                 # снимок ключей: финализация мутирует state по ходу
        setup = state.get(symbol)
        if setup is None or setup.get("closed"):
            continue
        try:
            still_open = [lv for lv in LV if (setup["legs"].get(lv) or {}).get("state") == OPEN]
            _exec_action(executor, state, symbol, make_close(still_open, "close_all"), logger)  # LIVE-гейт внутри
            _finalize_closed_setup(state, symbol, cursors, now_ms, logger)
            n += 1
        except Exception as e:                              # close одной монеты упал — не валим остальные; ack не сдвинем
            all_ok = False
            logger.warning("%s: CLOSE_ALL flatten не прошёл — ретрай след. тик: %s", symbol, e)
    if all_ok:
        store.set_close_all_ack(latest["id"])               # намерение исполнено → курсор за него (идемпотентно)
        _log_event(db, "ALL", "close_all", "закрыто %d" % n, logger=logger)   # событие монитора (5.4c)
        logger.warning("CLOSE_ALL исполнен → ПАУЗА + закрыто %d сетапов (ack=%d)", n, latest["id"])
    else:
        logger.warning("CLOSE_ALL частично исполнен → ack НЕ сдвинут (ретрай след. тик); ПАУЗА держит новые сетапы")


# ── observability-писатели монитора (под-шаг 5.4c) ───────────────────────────
# Пишут в логовые таблицы (signals/fills/events). КАЖДЫЙ изолирован собственным try/except — сбой записи НЕ
# маскирует trade-skip и НЕ валит торговый путь (внешний per-coin try его бы проглотил как «тик пропущен»).
# db берём из state.db (StateStore владеет соединением). observability — НЕЗАВИСИМО от LIVE_TRADING_ENABLED.
def _log_signal(db, symbol, sig, *, logger):
    """Строка ленты сигналов на РОЖДЕНИИ (вкл. cap-фильтрованные и dry-run). min_bar_pct/shadow_* — NULL
    (нет live-продьюсера теневого касания → тайл fill-rate off до shadow-движка/5.6)."""
    try:
        e, t = sig.get("entries", {}), sig.get("targets", {})
        db.signals_put(symbol=symbol, side=sig.get("side"), bar_time=sig.get("bar_time"),
                       a=sig.get("A"), b=sig.get("B"), stop=sig.get("stop"),
                       entry_0382=e.get(0.382), entry_05=e.get(0.5), entry_0618=e.get(0.618),
                       tgt_0382=t.get(0.382), tgt_05=t.get(0.5), tgt_0618=t.get(0.618))
    except Exception as ex:
        logger.warning("signals_put(%s) пропущен: %s", symbol, ex)


def _log_fill(db, symbol, side, lv, leg, *, detect_bar_ms=None, logger):
    """Строка истории заливов — ТОЛЬКО входы (инвариант V7: счёт выходов раздул бы fill-rate ~×2; выходы →
    событие leg_exit). cost/risk-колонки NULL (опросный путь без execution-record). detect_bar_ms/order_id
    (5.2 п6): граница 15m обнаружения залива опросом + orderId ноги — знаменатель офлайн-сверки края с WS."""
    try:
        leg = leg or {}
        db.fills_put(symbol=symbol, side=side, entry_level=str(lv), exec_type="entry",
                     order_link_id=leg.get("link_id"), requested_price=leg.get("entry"),
                     requested_qty=leg.get("qty"), exec_qty=leg.get("qty"),
                     detect_bar_ms=detect_bar_ms, order_id=leg.get("order_id"))
    except Exception as ex:
        logger.warning("fills_put(%s/%s) пропущен: %s", symbol, lv, ex)


def _log_event(db, symbol, event, detail=None, *, ts_ms=None, logger,
               exit_link=None, order_id=None, lv=None, role=None, qty=None):
    """Строка журнала событий (setup_placed/setup_closed/leg_exit/close_all/kill_switch_stop). detail → TEXT|None.
    ts_ms (5.2 п6): для leg_exit — граница 15m обнаружения выхода опросом. exit_link/order_id/lv/role/qty
    (ws_stage_b_preconditions): СТРУКТУРНЫЙ ключ выхода для офлайн-сверки края Стадии B (leg_exit; прочие NULL)."""
    try:
        db.events_put(symbol=symbol, event=event, detail=None if detail is None else str(detail), ts_ms=ts_ms,
                      exit_link=exit_link, order_id=order_id, lv=lv, role=role, qty=qty)
    except Exception as ex:
        logger.warning("events_put(%s/%s) пропущен: %s", symbol, event, ex)


# ── панель «ждущие ордера» (orders_open, под-шаг 5.4d) ───────────────────────
# Снимок resting-ордеров активной карточки + снятие строки при уходе сетапа (иначе фантом на мониторе).
# Источник — САМА карточка (по построению только входные -ent ноги → reduce-only/выходы не попадают, инвариант
# анти-раздув V7). Свои inner try/except — сбой записи НЕ маскирует trade-skip и НЕ валит торговый тик.
def _log_orders_open(db, symbol, setup, *, logger):
    """Снимок ЖИВОЙ входной ЛАДДЕР-ноги карточки в orders_open (панель «ждущие»): в снимок идут `OPEN` (залитые,
    `filled=True`) И resting `PENDING` (живой `link_id` -ent лимита на бирже); `CLOSED` и отменённые (`PENDING` без
    `link_id` — cancel_all_legs снял link) исключены. Так панель показывает fill-прогресс медальоном N/total
    (0/3→1/3→2/3). Трансляция V8.1 leg→legacy {level,entry,tgt,qty,filled,order_id}, `filled`=`state==OPEN` (по
    построению только входные ноги — инвариант анти-раздув). Строку держим, пока есть ≥1 resting-нога; НЕТ resting →
    СНИМАЕМ (само-чистка: все залиты → сетап вошёл целиком → уходит в «позиции»; после kill-switch-cancel/отмены —
    пусто; даже если writer перепишется на том же тике). Снимок на ВЕРХУ 15m-тика → залив/пере-якорь этого тика виден
    со следующего (задержка ≤1 тик; фантома не создаёт). Свой try/except — сбой записи НЕ маскирует trade-skip и НЕ
    валит торговый тик."""
    try:
        setup = setup or {}
        legs = setup.get("legs") or {}
        ladder = [
            {"level": lv, "entry": leg.get("entry"), "tgt": leg.get("target"),
             "qty": leg.get("qty"), "filled": leg.get("state") == OPEN, "order_id": leg.get("order_id")}
            for lv, leg in sorted(legs.items())
            if leg.get("state") == OPEN
            or (leg.get("state") == PENDING and leg.get("link_id") is not None)
        ]
        has_resting = any(leg.get("state") == PENDING and leg.get("link_id") is not None
                          for leg in legs.values())
        if ladder and has_resting:
            db.orders_open_put(symbol, {"side": setup.get("side"), "stop": setup.get("stop0"), "legs": ladder})
        else:
            db.orders_open_clear(symbol)
    except Exception as ex:
        logger.warning("orders_open_put(%s) пропущен: %s", symbol, ex)


def _clear_orders_open(db, symbol, *, logger):
    """Снять строку панели «ждущие» при уходе сетапа из активного состояния (идемпотентно: DELETE отсутствующей
    = no-op). Зовётся на финализации (этот файл) и в kill-switch/reconcile/старт-sweep (app.main/state.reconcile)."""
    try:
        db.orders_open_clear(symbol)
    except Exception as ex:
        logger.warning("orders_open_clear(%s) пропущен: %s", symbol, ex)

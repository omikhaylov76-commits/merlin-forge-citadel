#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scout.main — сервис «Сканер-разведчик» (Веха 7). Под-шаг 1: Этап A (вселенная + состоятельность).

KEYLESS: только публичные эндпоинты Bybit (scout.public_api); из секретов — лишь DATABASE_URL (общая
Postgres) через config.ops. Боевой воркер/движок/execution НЕ трогает.

Запуск (под-шаг 1):
  python3 scout/main.py --once --stage=A   # разовый Этап A: воронка в stdout + запись в scout_universe/scout_meta

Полный сервис (wake-loop + кнопка «Сканировать сейчас» + расписание) — под-шаг 4.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # запуск как `python3 scout/main.py` (как dashboard.py)

import scout.config as scfg  # noqa: E402
from scout import bars as barlib  # noqa: E402
from scout import klines_cache as kcache  # noqa: E402
from scout import universe as uni  # noqa: E402
from scout.public_api import ExchangeError, PublicMarket, RateLimitBan  # noqa: E402
from storage.db import DB  # noqa: E402


def _now_ms():
    return int(time.time() * 1000)


def run_stage_a(db, *, market=None, now_ms=None, log=print):
    """Этап A: собрать вселенную, посчитать состоятельность, записать в БД, вернуть воронку.
    RateLimitBan (403/бан IP) — пробрасываем наверх (circuit-breaker: прогон прерывается, ждать ≥10 мин)."""
    now_ms = _now_ms() if now_ms is None else now_ms
    market = PublicMarket() if market is None else market
    tf = scfg.SCOUT_TF
    interval = uni.tf_to_interval(tf)
    t0 = time.time()

    # Этап A читает через ROLLING кэш (2b): докач в БД → серия для калибровки (заодно питает скан/график)
    def fetch_series(sym):
        return kcache.top_up(db, market, sym, tf, scfg.SCOUT_CAL_BARS,
                             retention=scfg.SCOUT_CAL_BARS, now_ms=now_ms)

    rows = uni.build_universe(market, interval=interval, now_ms=now_ms, log=log, fetch_series=fetch_series)

    # структурные исключения (klines НЕ тянули) отделяем от оценённых — иначе «klines N» врёт
    structural = {"beyond_universe_cap", "stablecoin"}
    fetched = [r for r in rows if not (structural & set(r["rejects"]))]   # реально стянули klines
    passed = [r for r in fetched if not r["rejects"]]
    reasons = {}
    for r in fetched:
        for rj in r["rejects"]:
            reasons[rj] = reasons.get(rj, 0) + 1
    n_stable = sum(1 for r in rows if "stablecoin" in r["rejects"])
    n_beyond = sum(1 for r in rows if "beyond_universe_cap" in r["rejects"])

    # курированный список: годные → топ-N по скору + пол → бары (config|volnorm-v1)
    listed = barlib.curate_list(rows)
    n_config = sum(1 for x in listed if x["bar_source"] == "config")

    # per-ТФ бары (под-шаг 7): primary (tf) бары уже в скалярных полях; для доп. ТФ (1h) докачиваем СВОЮ
    # серию по монетам списка → калибруем по её волатильности → кладём в bars_by_tf (payload). config-монеты
    # на не-4h → volnorm (боевые бары 4h-специфичны). Каденция: 1h освежается ВМЕСТЕ с 4h (§7a).
    for x in listed:
        x["bars_by_tf"] = {tf: {"mb1": x["mb1"], "mb2": x["mb2"], "bar_source": x["bar_source"]}}
    extra_tfs = [t for t in scfg.scanned_tfs() if t != tf]
    n_extra = {t: 0 for t in extra_tfs}
    for xtf in extra_tfs:
        for x in listed:
            try:
                s = kcache.top_up(db, market, x["symbol"], xtf, scfg.SCOUT_CAL_BARS,
                                  retention=scfg.SCOUT_CAL_BARS, now_ms=now_ms)
                b = barlib.bars_from_series(s, x["symbol"], xtf)
            except RateLimitBan:
                raise
            except Exception as e:               # сбой одной монеты — не роняем Этап A (у неё нет баров этого ТФ)
                log(f"  {xtf}-бары {x['symbol']} FAIL: {e}")
                b = None
            if b is not None:
                x["bars_by_tf"][xtf] = b
                n_extra[xtf] += 1

    funnel = {
        "universe_total": len(rows),
        "stablecoins": n_stable,
        "beyond_cap": n_beyond,
        "klines_fetched": len(fetched),
        "passed": len(passed),
        "list_size": len(listed),
        "list_config_bars": n_config,
        "list_generic_bars": len(listed) - n_config,
        "min_score": scfg.SCOUT_MIN_SCORE, "list_max": scfg.SCOUT_LIST_MAX,
        "rejects_by_reason": reasons,
        "tf": scfg.SCOUT_TF, "interval": interval,
        "scanned_tfs": scfg.scanned_tfs(), "extra_tf_bars": n_extra,
        "top_passed": sorted(
            ({"symbol": r["symbol"], "score": r["score"]} for r in passed),
            key=lambda x: x["score"], reverse=True)[:15],
    }
    duration_s = round(time.time() - t0, 1)

    db.scout_universe_put_many(
        [{"symbol": r["symbol"], "score": r["score"], "payload": r} for r in rows], now_ms)
    db.scout_list_put_snapshot(listed, now_ms)
    db.scout_meta_put(stage="A", funnel=funnel, now_ms=now_ms, duration_s=duration_s)

    log(f"\nЭтап A готов за {duration_s}с: вселенная {funnel['universe_total']} "
        f"(−{n_stable} стейбл, −{n_beyond} вне cap) → klines {funnel['klines_fetched']} → ГОДНЫ {funnel['passed']}")
    if reasons:
        log("  отсевы: " + ", ".join(f"{k}={v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])))
    log(f"  СПИСОК: {len(listed)} монет (пол {scfg.SCOUT_MIN_SCORE}, кап {scfg.SCOUT_LIST_MAX}); "
        f"боевых баров {n_config}, generic {len(listed) - n_config}")
    if extra_tfs:
        log("  доп-ТФ бары: " + ", ".join(f"{t}={n_extra[t]}/{len(listed)}" for t in extra_tfs))
    if listed:
        log("  топ списка: " + ", ".join(
            f"{x['symbol']}[{x['mb1']}/{x['mb2']} {x['bar_source'][:3]}]" for x in listed[:8]))
    return funnel


def run_stage_b(db, *, market=None, now_ms=None, log=print):
    """Этап B: скан сетапов по scout_list для КАЖДОГО ТФ (под-шаг 7: 4h + 1h) — докач кэша → три статуса →
    запись находок (snapshot per-ТФ). Возврат — все находки (каждая со своим tf). Оба ТФ за один проход."""
    from scout import scan as scanlib
    now_ms = _now_ms() if now_ms is None else now_ms
    market = PublicMarket() if market is None else market
    t0 = time.time()
    findings = []
    for tf in scfg.scanned_tfs():
        tf_find = scanlib.scan_list(db, market, tf=tf, now_ms=now_ms, log=log)
        findings.extend(tf_find)
        by = {}
        for f in tf_find:
            by[f["status"]] = by.get(f["status"], 0) + 1
        log(f"  [{tf}] находок {len(tf_find)} — " +
            (", ".join(f"{k}={v}" for k, v in sorted(by.items())) or "нет"))
    log(f"\nЭтап B готов за {round(time.time() - t0, 1)}с: всего находок {len(findings)} по ТФ {scfg.scanned_tfs()}")
    for f in sorted(findings, key=lambda x: x.get("score", 0), reverse=True)[:10]:
        st = {"ready": "✅готов", "tracking": "📈тянется", "forming": "🔥греется"}.get(f["status"], f["status"])
        log(f"  {str(f.get('tf')):3} {f['symbol']:12} {st}  score={f.get('score')}")
    return findings


# ─── сервис: wake-loop (под-шаг 4) ───
_TF_MS = {"4h": 14_400_000, "1h": 3_600_000, "15m": 900_000, "5m": 300_000}


def _cur_boundary(tf, now_ms):
    step = _TF_MS.get(tf, 14_400_000)
    return (now_ms // step) * step


def decide(ctrl, now_ms, *, tf="4h", auto=True, cal_hour=5, list_present=False):
    """Решение одного тика wake-loop → ('A'|'B'|None, reason). ЧИСТАЯ функция (тестируемо).
    Приоритет: bootstrap списка → кнопка → утренняя рекалибровка → авто-граница → простой."""
    if not list_present or not ctrl.get("last_a_ms"):
        return ("A", "bootstrap")                       # нет списка → сперва Этап A
    if ctrl.get("scan_now_ms", 0) > ctrl.get("scan_now_ack_ms", 0):
        return ("B", "button")                          # кнопка «Сканировать сейчас» (durable-намерение)
    hour = (now_ms // 3_600_000) % 24
    if hour == cal_hour and (now_ms - ctrl.get("last_a_ms", 0)) > 20 * 3_600_000:
        return ("A", "morning")                         # утренняя рекалибровка списка (раз в сутки)
    if auto and _cur_boundary(tf, now_ms) > ctrl.get("last_b_boundary_ms", 0):
        return ("B", "boundary")                        # закрылась новая граница ТФ
    return (None, "idle")


def run_service(db, *, market=None, poll_sec=None, max_ticks=None, now_fn=None, sleep_fn=None, log=print):
    """Главный цикл сервиса-скаута: каждые ~poll_sec решает (кнопка/граница/утро) и гоняет Этап A/B, пишет
    heartbeat/метки в scout_control. RateLimitBan (403) → пауза SCOUT_BAN_SLEEP_SEC (circuit-breaker).
    max_ticks — тест-хук (ограничить число тиков, без сна); в проде None (бесконечно)."""
    market = PublicMarket() if market is None else market
    poll = scfg.SCOUT_POLL_SEC if poll_sec is None else poll_sec
    now_fn = now_fn or _now_ms
    sleep_fn = sleep_fn or time.sleep
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        ticks += 1
        now_ms = now_fn()
        try:
            ctrl = db.scout_control_get()
            try:
                list_present = bool(db.scout_list_all())
            except Exception:
                list_present = False
            action, reason = decide(ctrl, now_ms, tf=scfg.SCOUT_TF, auto=scfg.SCOUT_AUTO,
                                    cal_hour=scfg.SCOUT_CAL_UTC_HOUR, list_present=list_present)
            if action == "A":
                log("[скаут] Этап A (%s)" % reason)
                run_stage_a(db, market=market, now_ms=now_ms, log=log)
                db.scout_control_mark(last_a_ms=now_ms)
            elif action == "B":
                log("[скаут] Этап B (%s)" % reason)
                run_stage_b(db, market=market, now_ms=now_ms, log=log)
                if reason == "button":
                    db.scout_control_mark(scan_now_ack_ms=ctrl.get("scan_now_ms", 0))
                else:
                    db.scout_control_mark(last_b_boundary_ms=_cur_boundary(scfg.SCOUT_TF, now_ms))
            db.scout_control_mark(heartbeat_ms=now_ms)
        except RateLimitBan as e:
            log("[скаут] 403 бан IP — пауза %sс: %s" % (scfg.SCOUT_BAN_SLEEP_SEC, e))
            if max_ticks is None:
                sleep_fn(scfg.SCOUT_BAN_SLEEP_SEC)
            continue
        except Exception as e:                          # сбой тика — не роняем сервис
            log("[скаут] тик FAIL: %s" % e)
        if max_ticks is None:
            sleep_fn(poll)
    return ticks


def _acquire_lock_with_wait(db, *, key=918274, wait_sec=None, sleep_fn=time.sleep, log=print):
    """Взять advisory-lock скаута, ОЖИДАЯ освобождения при overlap-передеплое Railway (старый скаут ещё держит
    лок; Railway снимет его, увидев новый контейнер «живым»). True=взял; False=не дождались за wait_sec (реальная
    коллизия). Процесс при ожидании ЖИВ (не крэшит) — это и позволяет Railway остановить старый и снять лок
    (зеркало воркёрского `_acquire_singleton_with_wait`, 5.5c). key≠918273 (воркёрский)."""
    wait_sec = scfg.SCOUT_LOCK_WAIT_SEC if wait_sec is None else wait_sec
    waited = 0
    while True:
        if db.acquire_singleton(key=key):
            if waited:
                log("[скаут] лок %d освободился и взят (ждал %dс)" % (key, waited))
            return True
        if waited >= wait_sec:
            return False
        log("[скаут] лок %d занят (передеплой?) — жду освобождения (%d/%dс)..." % (key, waited, wait_sec))
        sleep_fn(5)
        waited += 5


def main(argv=None):
    ap = argparse.ArgumentParser(description="Скаут (Веха 7) — сервис / Этап A/B")
    ap.add_argument("--once", action="store_true", help="разовый прогон и выход (без сервиса)")
    ap.add_argument("--stage", choices=["A", "B"], default="A",
                    help="A=вселенная+список (под-шаги 1/2), B=скан сетапов (под-шаг 3)")
    args = ap.parse_args(argv)

    db = DB(owner=True)                     # ensure_schema (создаёт scout_* идемпотентно)
    if args.once:                           # разовый прогон (смоук/отладка)
        try:
            if args.stage == "A":
                run_stage_a(db)
            else:
                run_stage_b(db)
        except RateLimitBan as e:
            print(f"СТОП: публичный лимит биржи (403, бан IP ~10 мин) — {e}. Повторить позже.")
            return 3
        except ExchangeError as e:
            print(f"СТОП: биржа недоступна — {e}. Повторить позже.")
            return 3
        finally:
            db.close()
        return 0

    # СЕРВИС: свой лок ≠ воркерского 918273 (мульти-контейнер PG advisory / SQLite-файл). Overlap-передеплой:
    # ЖДЁМ освобождения (не крэшим), иначе крэш-луп при живом старом контейнере — дедлок (5.5c).
    if not _acquire_lock_with_wait(db, key=918274):
        print("[скаут] лок 918274 не освободился за %sс — выходим (реальная коллизия)." % scfg.SCOUT_LOCK_WAIT_SEC)
        db.close()
        return 4
    print("[скаут] wake-loop запущен: poll=%sс tf=%s auto=%s cal_hour=%s" % (
        scfg.SCOUT_POLL_SEC, scfg.SCOUT_TF, scfg.SCOUT_AUTO, scfg.SCOUT_CAL_UTC_HOUR))
    try:
        run_service(db)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

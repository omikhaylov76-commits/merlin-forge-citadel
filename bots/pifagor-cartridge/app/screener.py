"""screener — С7-2а: подбор монет по ПАРАМЕТРАМ (не фикс-список) для разового прогона.

Возраст и оборот 24h — это уже штатные отсевы Этапа A вендора (`universe.build_universe`:
`age_days` из launchTime → `young_listing`; `turnover24h` → `low_turnover`). НОВОЕ здесь —
ИМПУЛЬС: всплеск объёма последнего бара против обычного. Цель Оператора — «монеты, в которых
есть импульс».

Чистые функции (impulse_ratio / has_impulse / select_candidates) — юнит-тест без сети и без vendor.
Живой оркестратор (build_universe → импульс → scan_list на оба ТФ → отчёт) тянет Bybit и связан с БД
Этапа A — он за гейтом (риск 403-бана на общем IP скаута + развилка изоляции БД), пишется отдельно.
Vendor НЕ правим — только импорт функций образца.
"""
from __future__ import annotations

# Сколько баров ТФ укладывается в сутки — для перевода «N дней» в размер окна среднего объёма.
_BARS_PER_DAY = {"4h": 6, "1h": 24, "15m": 96, "5m": 288}


def bars_for_days(days: float, tf: str) -> int:
    """Число баров ТФ за `days` суток (окно среднего объёма). Неизвестный ТФ считаем как 4h."""
    return max(1, int(round(days * _BARS_PER_DAY.get(tf, 6))))


def volumes_of(klines) -> list:
    """Объёмы из klines (vendor parse_kline_rows кладёт ключ 'volume' в каждый бар)."""
    return [k.get("volume") for k in (klines or [])]


def impulse_ratio(volumes, *, lookback_bars):
    """Отношение объёма ПОСЛЕДНЕГО бара к среднему объёму предыдущих `lookback_bars` баров.

    `volumes` — по возрастанию времени (последний = самый свежий бар). Возвращает None, если данных
    мало, все предыдущие объёмы пусты, или их среднее ≤ 0 (нельзя нормировать)."""
    if not volumes or len(volumes) < 2:
        return None
    recent = volumes[-1]
    if recent is None:
        return None
    start = max(0, len(volumes) - 1 - lookback_bars) if lookback_bars else 0
    prior = [v for v in volumes[start:-1] if v is not None]
    if not prior:
        return None
    avg = sum(prior) / len(prior)
    if avg <= 0:
        return None
    return recent / avg


def has_impulse(volumes, *, k=1.5, lookback_bars):
    """Импульс есть, если объём последнего бара ≥ k× среднего объёма предыдущих `lookback_bars`."""
    r = impulse_ratio(volumes, lookback_bars=lookback_bars)
    return r is not None and r >= k


def select_candidates(rows, *, k=1.5, days=14, tf="4h", klines_of=None):
    """Из строк `build_universe` (per-symbol {symbol, rejects, metrics, …}) отобрать кандидатов.

    Кандидат = прошёл Этап A (rejects пуст) И имеет импульс ≥ k. `klines_of(symbol)` отдаёт klines
    для объёма (в живом прогоне — из кэша, что тянул build_universe). Возвращает честный разбор по
    КАЖДОЙ монете (для отчёта «кто взят / кто отсеян и почему»):
    {symbol, stage_a_ok, rejects, impulse_ratio, impulse_ok, selected}."""
    lb = bars_for_days(days, tf)
    out = []
    for row in rows:
        sym = row.get("symbol")
        rej = row.get("rejects") or []
        stage_a_ok = not rej
        # импульс считаем ТОЛЬКО для прошедших Этап A — незачем тянуть/мерить отсеянные
        kl = klines_of(sym) if (stage_a_ok and klines_of) else None
        ratio = impulse_ratio(volumes_of(kl), lookback_bars=lb) if stage_a_ok else None
        imp_ok = ratio is not None and ratio >= k
        out.append({
            "symbol": sym,
            "stage_a_ok": stage_a_ok,
            "rejects": rej,
            "impulse_ratio": round(ratio, 3) if ratio is not None else None,
            "impulse_ok": imp_ok,
            "selected": stage_a_ok and imp_ok,
        })
    return out


# ── ЖИВОЙ прогон (тянет Bybit; за гейтом Куратора) ───────────────────────────
def run_screener(*, k=1.5, days=14, universe_max=150, rps=1, min_age_days=180,
                 min_turnover_usd=5_000_000, db_path=None, log=print):
    """Разовый прогон по параметрам: Этап A вендора (возраст/оборот) → импульс из кэша 4h →
    Этап B скан (оба ТФ) → структурированный отчёт. Изолированная SQLite (db_path), троттл rps.

    Тянет публичный Bybit. Vendor импортируется лениво — чистые функции сети/vendor не касаются."""
    import json as _json
    import os
    import tempfile

    # scout.config читает env на импорте → задаём ДО импорта vendor; DATABASE_URL убираем
    os.environ["SCOUT_UNIVERSE_MAX"] = str(universe_max)
    os.environ["SCOUT_RPS"] = str(rps)
    os.environ["SCOUT_MIN_AGE_DAYS"] = str(min_age_days)
    os.environ["SCOUT_MIN_TURNOVER_USD"] = str(min_turnover_usd)
    os.environ.pop("DATABASE_URL", None)

    from app.reader import _ensure_vendor_on_path
    _ensure_vendor_on_path()
    import scout.config as scfg
    from scout import main as smain
    from scout.public_api import PublicMarket
    from storage.db import DB

    if db_path is None:
        db_path = os.path.join(tempfile.gettempdir(), "mfc_screener_run.db")
    db = DB(owner=True, db_path=db_path)
    market = PublicMarket(rps=rps)
    try:
        funnel = smain.run_stage_a(db, market=market, log=log)
        findings = smain.run_stage_b(db, market=market, log=log)

        lb = bars_for_days(days, "4h")
        setups_by_symbol = {}
        for f in findings:
            setups_by_symbol.setdefault(f["symbol"], []).append(
                {"tf": f.get("tf"), "status": f.get("status"), "score": f.get("score")})

        struct = {"beyond_universe_cap", "stablecoin"}  # klines не тянули → не в таблицу
        rows = []
        for r in db.scout_universe_all():
            payload = r["payload"]
            if isinstance(payload, str):
                payload = _json.loads(payload)
            rejects = payload.get("rejects") or []
            if struct & set(rejects):
                continue
            sym = r["symbol"]
            score = round(float(r.get("score") or 0.0), 1)
            if rejects:  # отсеян Этапом A — в таблицу с причиной, импульс не мерим
                rows.append({"symbol": sym, "score": score, "impulse_ratio": None,
                             "selected": False, "reject_reason": rejects[0], "setups": []})
                continue
            win = db.scout_klines_read_window(sym, "4h", lb + 1)
            ratio = impulse_ratio(volumes_of(win), lookback_bars=lb)
            imp_ok = ratio is not None and ratio >= k
            rows.append({
                "symbol": sym, "score": score,
                "impulse_ratio": round(ratio, 3) if ratio is not None else None,
                "selected": imp_ok,  # прошёл Этап A (rejects пуст) + импульс
                "reject_reason": None if imp_ok else "low_impulse",
                "setups": setups_by_symbol.get(sym, []),
            })
    finally:
        db.close()

    # взятые — вверх по импульсу; затем прочие
    rows.sort(key=lambda x: (x["selected"], x["impulse_ratio"] or 0.0), reverse=True)
    selected = [x for x in rows if x["selected"]]
    setups_sel = [s for x in selected for s in x["setups"]]
    return {
        "params": {"k": k, "days": days, "universe_max": universe_max, "rps": rps,
                   "min_age_days": scfg.SCOUT_MIN_AGE_DAYS,
                   "min_turnover_usd": scfg.SCOUT_MIN_TURNOVER_USD, "tfs": scfg.scanned_tfs()},
        "funnel": funnel,
        "passed_stage_a": sum(1 for x in rows if x["reject_reason"] in (None, "low_impulse")),
        "selected_count": len(selected),
        "setups_selected_count": len(setups_sel),
        "findings": rows,
        "selected": selected,
    }


def print_report(rep, log=print):
    """Человекочитаемый отчёт скринера в stdout (для Оператора)."""
    p, f = rep["params"], rep["funnel"]
    log("\n===== ОТЧЁТ СКРИНЕРА (импульс) =====")
    log(f"параметры: возраст>{p['min_age_days']}д · оборот24h>=${p['min_turnover_usd']:,} · "
        f"импульс>=x{p['k']} (окно {p['days']}д) · ТФ {p['tfs']} · "
        f"вселенная top-{p['universe_max']}")
    log(f"воронка: вселенная {f.get('universe_total')} -> klines {f.get('klines_fetched')} -> "
        f"Этап A прошли {f.get('passed')}")
    rej = f.get("rejects_by_reason") or {}
    if rej:
        parts = ", ".join(f"{a}={b}" for a, b in sorted(rej.items(), key=lambda x: -x[1]))
        log("  отсев Этапа A: " + parts)
    log(f"импульс>=x{p['k']}: ВЗЯТО {rep['selected_count']} из {rep['passed_stage_a']} "
        f"прошедших Этап A; сетапов у взятых: {rep['setups_selected_count']}")
    log("\nВЗЯТЫЕ (по убыванию импульса):")
    for x in rep["selected"][:30]:
        su = ", ".join(f"{s['tf']}:{s['status']}({s['score']})" for s in x["setups"]) or "—"
        log(f"  {x['symbol']:12} x{x['impulse_ratio']:<5} скор {x['score']:<5} сетапы: {su}")
    if not rep["selected"]:
        log("  (никто не прошёл импульс-порог)")


def push_results(core_url, token, run_id, status, *, summary=None, findings=None):
    """Пуш статуса/результата прогона в ядро (POST /v1/screener/runs/{run_id}/results)."""
    import json
    import urllib.request

    body = {"status": status}
    if summary is not None:
        body["summary"] = summary
    if findings is not None:
        body["findings"] = findings
    req = urllib.request.Request(
        f"{core_url.rstrip('/')}/v1/screener/runs/{run_id}/results",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def _summary_of(rep):
    return {k: rep[k] for k in ("params", "funnel", "passed_stage_a", "selected_count",
                                "setups_selected_count")}


def main(argv=None):
    import argparse
    import os

    ap = argparse.ArgumentParser(description="Скринер монет по параметрам (импульс)")
    ap.add_argument("--k", type=float, default=1.5, help="порог импульса (x среднего)")
    ap.add_argument("--days", type=int, default=14, help="окно среднего объёма, дней")
    ap.add_argument("--universe-max", type=int, default=150, help="сколько топ-по-обороту тянуть")
    ap.add_argument("--rps", type=int, default=1, help="троттл запросов к Bybit")
    ap.add_argument("--min-age-days", type=int, default=180, help="мин. возраст монеты, дней")
    ap.add_argument("--min-turnover", type=int, default=5_000_000, help="мин. оборот 24ч, USD")
    ap.add_argument("--db-path", default=None, help="изолированная SQLite (по умолчанию tmp)")
    ap.add_argument("--json-out", default=None, help="сохранить отчёт JSON")
    ap.add_argument("--push", action="store_true", help="пушить результат в ядро (нужен --run-id)")
    ap.add_argument("--run-id", default=None, help="run_id прогона (для --push)")
    args = ap.parse_args(argv)

    core_url = os.environ.get("MF_CORE_URL", "http://127.0.0.1:8000")
    token = os.environ.get("MF_INSTANCE_TOKEN", "")

    def _run():
        return run_screener(k=args.k, days=args.days, universe_max=args.universe_max,
                            rps=args.rps, min_age_days=args.min_age_days,
                            min_turnover_usd=args.min_turnover, db_path=args.db_path)

    if args.push:
        if not args.run_id:
            ap.error("--push требует --run-id")
        try:
            push_results(core_url, token, args.run_id, "running")
            rep = _run()
            push_results(core_url, token, args.run_id, "done",
                         summary=_summary_of(rep), findings=rep["findings"])
            print(f"пуш done: run_id={args.run_id} findings={len(rep['findings'])}")
        except Exception as exc:  # прогон/пуш упал → фиксируем error в ядре, чтобы консоль не висла
            try:
                push_results(core_url, token, args.run_id, "error",
                             summary={"error": str(exc)[:300]})
            except Exception:
                pass
            print(f"скринер FAIL: {exc}")
            return 1
        return 0

    rep = _run()
    print_report(rep)
    if args.json_out:
        import json

        with open(args.json_out, "w") as fp:
            json.dump(rep, fp, ensure_ascii=False, indent=2)
        print(f"\nJSON отчёт: {args.json_out}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

# -*- coding: utf-8 -*-
"""dashboard.viewmodel — сборка вью-моделей кокпита (Веха 4).

build_monitor(...) — вкладка «Главная» (ф.3): капитал/состояние/тайлы/позиции/история/сигналы/паритет.
build_settings(...) — вкладка «Настройки» (ф.4): крутилки (с UI-метаданными KNOB_UI), per-coin (read-only),
журнал изменений, пауза, режим, блок состояния (баннер) + признаки доступа (control). Оба берут общий
расчёт капитала/просадки/состояния из _derive_capital_status (единый путь деривации, без дубля).

Граница безопасности: дашборд — пассивный кокпит, БЕЗ broker/pybit (физически не торгует). NB: через
state/__init__->reconcile транзитивно тянется execution + strategy.engine + pandas/numpy (вес, не «лёгкий
решатель»; биржи/ключей нет — граница цела; leaf-вынос — хвост Вехи 5). Состояния ног сверяем с литералами-
зеркалом "open"/"pending" (анти-дрейф — tests/test_dashboard_viewmodel.py). Запись — эндпоинты
dashboard.dashboard (под control-сессией + CSRF), не здесь.
"""
import json
import time

import config  # config — БЕЗ broker/execution-зависимостей (config.execution — это knobs-модуль, не пакет execution)
from config import knobs
from logging_.trade_logger import get_logger

_log = get_logger("pifagor.dashboard.viewmodel")

# Зеркало execution.actions (НЕ импортируем execution — дашборд без broker/lifecycle-зависимостей).
# Анти-дрейф: tests/test_dashboard_viewmodel.py сверяет _OPEN/_PENDING с execution.actions.
_OPEN = "open"
_PENDING = "pending"

# UI-метаданные крутилок (группа/подпись/единица/шаг/предохранитель/advisory/help) — ОТДЕЛЬНО от чистого
# config.knobs (валидация). group="_emergency" -> крутилка не в сетке, отрисовывается как кнопка (Пауза).
# Предохранитель 🔒 (fused) — на опасных (риск/kill/тревога). advisory ⚠ — ТОЛЬКО value-крутилки вне честной
# выборки (STOP_FIB/SL_TRIGGER_BY); тумблеры Shorts/EMA — голые (ADR 0009: без плашки).
KNOB_UI = {
    "RISK_PCT_PER_LEG":   {"group": "Риск", "label": "Риск на ногу", "unit": "%", "step": 0.1, "fused": True,
                           "help": "Риск на одну ногу, % от рабочего капитала. Меньше = консервативнее."},
    "RISK_PCT_ALARM":     {"group": "Риск", "label": "Риск при тревоге", "unit": "%", "step": 0.05,
                           "help": "Риск на ногу в режиме тревоги (−40%). Обычно ~половина обычного."},
    "CONCURRENCY_CAP":    {"group": "Риск", "label": "Лимит одновременных ног", "unit": "", "step": 1,
                           "help": "Максимум одновременно залитых ног (cap). Сверх — новые пропускаются."},
    "MAX_LEVERAGE":       {"group": "Риск", "label": "Максимальное плечо", "unit": "x", "step": 1,
                           "help": "Потолок плеча при сайзинге."},
    "KILLSWITCH_DD":      {"group": "Стоп-защита", "label": "Kill-switch (стоп)", "unit": "доля", "step": 0.01,
                           "fused": True,
                           "help": "Просадка от пика, на которой торговля останавливается. Дефолт 0.50 (−50%)."},
    "ALARM_DD":           {"group": "Стоп-защита", "label": "Тревога", "unit": "доля", "step": 0.01, "fused": True,
                           "help": "Просадка, на которой риск уполовинивается. Должна быть < kill-switch. Дефолт 0.40."},
    "STOP_FIB":           {"group": "Стоп-защита", "label": "Стоп (фибо)", "unit": "", "step": 0.05, "advisory": True,
                           "help": "Уровень стопа. Проверено только 1.0; иное — вне честной выборки (ADR 0004)."},
    "SL_TRIGGER_BY":      {"group": "Стоп-защита", "label": "Триггер стопа", "advisory": True,
                           "help": "Цена срабатывания стопа. LastPrice — паритет с бэктестом (ADR 0007)."},
    "WORKING_START":      {"group": "Капитал", "label": "Рабочий старт", "unit": "$", "step": 100,
                           "help": "Стартовый рабочий капитал (база сайзинга). Применяется на засеве."},
    "CUSHION_START":      {"group": "Капитал", "label": "Подушка старт", "unit": "$", "step": 100,
                           "help": "Стартовая подушка (амортизирует просадку)."},
    "REFINANCE_SPLIT":    {"group": "Капитал", "label": "Рефинанс в подушку", "unit": "доля", "step": 0.05,
                           "help": "Доля месячной прибыли в подушку. 0.5 — держит долю; >0.5 растит подушку."},
    "SHORTS_ENABLED":     {"group": "Режимы", "label": "Шорты",
                           "help": "Разрешить шорт-сетапы. Вне проверенной выборки (ADR 0009)."},
    "EMA_FILTER_ENABLED": {"group": "Режимы", "label": "Фильтр EMA200",
                           "help": "Включить тренд-фильтр EMA200. Вне проверенной выборки (ADR 0009)."},
    "REANCHOR_AFTER_SCALP": {"group": "Режимы", "label": "Режим v3 (пере-якорь после скальпа)",
                             "help": "v2 (выкл) — эталон: после скальпа ближней ноги 0.382 якорь замерзает. "
                                     "v3 (вкл) — на новый хай перерисовать сетку и перезарядить ногу (research R6). "
                                     "Demo-first, реал позже малым."},
    "WARM_ON_START":      {"group": "Режимы", "label": "Тёплый старт (авто)",
                           "help": "Подхватывать живые сетапы при запуске воркера. Авто ставит ТОЛЬКО нетронутые "
                                   "PENDING (ADR 0013); панель подтверждения — отдельно."},
    "WARM_MAX_AGE_BARS":  {"group": "Режимы", "label": "Окно тёплого старта", "unit": "бар", "step": 1,
                           "help": "Насколько назад (закрытые 4h-бары) искать живой пробой для подхвата. Дефолт 72."},
    "RUNNER_TP_HOLD":     {"group": "Режимы", "label": "Живой бегунок (держать TP ноги 0.5)",
                           "help": "Выкл (эталон) — как сейчас: тейки ног 0.382 и 0.5 на одной цене 0.236, бьют разом. "
                                   "Вкл — ноге-бегунку 0.5 не ставим тейк 0.236, пока открыта 0.382; каскадом уходит на "
                                   "2.0R (ADR 0015). Demo-first."},
    "LEG2_EXT":           {"group": "Режимы", "label": "Цель бегунка (ext)", "unit": "×R", "step": 0.01, "advisory": True,
                           "help": "Куда целит нога-бегунок 0.5: ext(LEG2_EXT). Дефолт 1.0 (=2.0R, чемпион). "
                                   "Иное — вне честной выборки (ре-бэктест перед реалом, как STOP_FIB)."},
    "DOUBLE_DIP_ENABLED": {"group": "Режимы", "label": "Двойной заход (перезаход ноги 0.5)", "advisory": True,
                           "help": "Выкл (эталон) — нога 0.5 входит строго на своём уровне. Вкл — после скальпа "
                                   "ближней ноги 0.382 нога 0.5 перезаходит с допуском (поле ниже) — ловит «почти "
                                   "дотянулись» (задача 5.9, ADR 0016). Вне честной выборки (walk-forward слабый), "
                                   "demo-first, реал позже малым."},
    "DOUBLE_DIP_TOL":     {"group": "Режимы", "label": "% допуска двойного захода", "unit": "доля", "step": 0.01,
                           "advisory": True,
                           "help": "Ширина допуска: доля высоты импульса |B−A|. Дефолт 0.04 (≈4%). 0 = допуск выключен "
                                   "(режим инертен). Иное — вне честной выборки. Действует только при включённом «Двойном заходе»."},
    "TRAIL_ENABLED":      {"group": "Режимы", "label": "Трейл бегунка (нативный стоп Bybit)", "advisory": True,
                           "help": "Выкл (эталон) — бегунок 0.5 целит в фикс ext(цель бегунка). Вкл — соло-бегунок за "
                                   "вершиной ведётся биржевым трейлинг-стопом (ширина — поле ниже) ПОВЕРХ вшитого стопа; "
                                   "фикс-цель снимается (R8, путь Y, ADR 00XX). Тик биржи ≠ 15m-бэктест → вне честной "
                                   "выборки, demo-first; активация — отдельное go/no-go после форварда."},
    "TRAIL_R":            {"group": "Режимы", "label": "Ширина трейла (R)", "unit": "×R", "step": 0.05, "advisory": True,
                           "help": "Дистанция трейлинг-стопа = TRAIL_R·(B−A). Дефолт 0.4 (центр проверенного плато "
                                   "0.35–0.55). Действует только при включённом «Трейле бегунка»."},
    "PAUSE_ENABLED":      {"group": "_emergency", "label": "Пауза"},
}

# Порядок секций крутилок в UI (стабильный контракт для settings.js; иначе порядок зависел бы от dict KNOB_SPECS).
GROUP_ORDER = ("Риск", "Стоп-защита", "Капитал", "Режимы")


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _i(x, default=None):
    """Безопасный int: одна битая строка снимка (ts_ms) не должна ронять всю вью-модель (500)."""
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _parse_json(text, default=None):
    if not text:
        return default if default is not None else []
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return default if default is not None else []


class DisplayConfig:
    """Обёртка ConfigStore ТОЛЬКО для ПОКАЗА (фича unified_config_source): дефолт крутилки берётся из
    ОПУБЛИКОВАННОГО воркером env-снимка (единый источник = воркер), а не из env дашборда — иначе показ врёт
    про env-заданные крутилки (воркер и дашборд — разные контейнеры с разным env). override (config_state —
    ОБЩИЙ) и журнал делегируются реальному store как есть. Путь ЗАПИСИ (`set`) НЕ оборачивается — эндпоинты
    зовут реальный ConfigStore напрямую (управление сохраняется 1:1). УЗКАЯ: реализует лишь raw/default/get/log
    (весь текущий show-path). Если новый путь показа начнёт звать overrides()/all()/effective() — расширить обёртку."""

    def __init__(self, config_store, worker_defaults):
        self._cs = config_store
        self._wd = worker_defaults or {}

    def raw(self, key):
        return self._cs.raw(key)                          # override из ОБЩЕЙ config_state — не трогаем

    def default(self, key):
        if key in self._wd:
            return self._wd[key]                          # воркерский env-дефолт = единый источник показа
        if self._wd:                                      # снимок ЕСТЬ, но ключа нет → version-skew (дашборд новее воркера)
            _log.debug("worker_config: ключа %s нет в снимке воркера (version-skew?) → фолбэк на свой env", key)
        return knobs.default(key)                         # фолбэк: свой env (снимка нет / skew) = текущее поведение

    def get(self, key):
        ov = self.raw(key)
        return ov if ov is not None else self.default(key)

    def log(self, *a, **k):
        return self._cs.log(*a, **k)                      # журнал изменений = общий config_state, делегируем


def _display_config(db, config_store):
    """(DisplayConfig, updated_ms|None): обернуть config_store снимком воркера для ПОКАЗА. `worker_config_get`
    fail-soft (нет снимка/битый → None) ⇒ обёртка падает на свой env = текущее поведение."""
    snap = db.worker_config_get()
    return (DisplayConfig(config_store, snap["defaults"] if snap else None),
            snap["updated_ms"] if snap else None)


def _knob_view(key, config_store):
    """Один пункт крутилки для UI: эффективное значение, дефолт, override?, диапазон/enum + UI-метаданные."""
    spec = knobs.KNOB_SPECS[key]
    ui = KNOB_UI.get(key, {})
    eff = config_store.get(key)
    default = config_store.default(key)                    # воркерский дефолт (unified_config_source) → advisory ниже тоже следует воркеру
    out = {
        "key": key, "type": spec["t"], "value": eff, "default": default,
        "is_override": config_store.raw(key) is not None,
        "group": ui.get("group", "Прочее"), "label": ui.get("label", key),
        "unit": ui.get("unit", ""), "fused": bool(ui.get("fused")), "help": ui.get("help", ""),
        # advisory ⚠ показываем только когда значение отличается от проверенного дефолта
        "advisory": bool(ui.get("advisory")) and (eff != default),
    }
    if spec["t"] == "num":
        out.update(lo=spec.get("lo"), hi=spec.get("hi"),
                   lo_inc=spec.get("lo_inc", True), hi_inc=spec.get("hi_inc", True),
                   int=(spec["py"] is int), step=ui.get("step", 1 if spec["py"] is int else 0.01))
    elif spec["t"] == "enum":
        out["values"] = list(spec["values"])
    return out


def _journal_row(r):
    """Строка журнала для UI. ДЕЙСТВИЕ (Пауза/Закрыть-всё) отличаем по source="action" ИЛИ param∉KNOB_SPECS
    (НЕ по old is None: у первой установки крутилки old тоже None) — рисуется как «действие», не «было→стало»."""
    param = r.get("param")
    is_action = (r.get("source") == "action") or (param not in knobs.KNOB_SPECS)
    return {
        "id": r.get("id"), "ts": r.get("ts"), "param": param,
        "old": r.get("old"), "new": r.get("new"),
        "source": r.get("source"), "applied_from_bar": r.get("applied_from_bar"),
        "kind": "action" if is_action else "knob",
        "label": param if is_action else KNOB_UI.get(param, {}).get("label", param),
    }


def _derive_capital_status(db, capital_store, config_store, *, now_ms, stale_sec):
    """Общий расчёт капитала/просадки/состояния/баннера (переиспользуют монитор и настройки — единый путь).
    Возвращает сырые снимки (cap/acc/hb) + производные (working…dd_pct…state/zone/stale/banner)."""
    cap = capital_store.get()                       # None если леджер не засеян
    acc = db.account_get()                          # снимок счёта (Веха 5 пишет) или None
    hb = db.heartbeat_get()                         # последний heartbeat или None
    kill_dd = _f(config_store.get("KILLSWITCH_DD"), 0.50)
    alarm_dd = _f(config_store.get("ALARM_DD"), 0.40)

    working = _f(cap.get("working")) if cap else 0.0
    cushion = _f(cap.get("cushion")) if cap else 0.0
    ratio = _f(cap.get("ratio")) if cap else 0.0
    peak = _f(cap.get("peak_equity")) if cap else 0.0
    ks_active = bool(cap.get("killswitch_active")) if cap else False
    al_active = bool(cap.get("alarm_active")) if cap else False
    live = acc is not None                          # есть ли снимок live-equity с биржи (writer Вехи 5)
    if live:
        equity = _f(acc.get("total_equity"))
        if peak <= 0:
            peak = equity
        dd_pct = max(0.0, (peak - equity) / peak) if peak > 0 else 0.0
        dd_usd = max(0.0, peak - equity)
    else:
        equity = working + cushion                  # ОЦЕНКА по леджеру для тайла equity; НЕ источник просадки
        dd_pct = 0.0                                # ADR 0010 §1: просадку/тревогу меряем по LIVE-equity, НЕ по working-леджеру
        dd_usd = 0.0
    # state: защёлки авторитетны и без свежего снимка; вычисляемый STOP/ALARM — ТОЛЬКО от live-equity (ADR 0010 §1).
    # Леджер засеян, но live-equity нет и защёлки нет -> просадку оценить нельзя -> NO_DATA (не ложный red от working).
    if cap is None:
        state = "NO_DATA"
    elif ks_active:
        state = "STOP"
    elif al_active:
        state = "ALARM"
    elif not live:
        state = "NO_DATA"
    elif dd_pct >= kill_dd:
        state = "STOP"
    elif dd_pct >= alarm_dd:
        state = "ALARM"
    else:
        state = "NORMAL"
    zone = "red" if state == "STOP" else ("amber" if state == "ALARM" else "green")

    hb_ts_ms = _i(hb.get("ts_ms")) if hb else None      # safe-int: битая строка снимка не роняет вью-модель
    hb_age_s = (now_ms - hb_ts_ms) / 1000.0 if hb_ts_ms is not None else None
    ws_alive = (hb.get("ws_alive") == "yes") if hb else False
    # «бот жив» = СВЕЖИЙ heartbeat. ws_alive (WS-фид) — ОТДЕЛЬНЫЙ индикатор, НЕ форсит «обрыв»: в опрос-режиме
    # (Веха 5 до WS) WS нет, но бот жив и тикает — иначе монитор показывал бы «disconnect» всю фазу.
    stale = (hb is None) or (hb_age_s is not None and hb_age_s > stale_sec)
    banner = "disconnect" if stale else state.lower()

    # Пороги срабатывания в ДЕНЬГАХ (для оператора у кнопки «Снять стоп» — фича 5.3a): equity ниже kill_at_usd ⇒
    # сброс защёлки не поможет, движок снова защёлкнет. peak есть всегда (из capital_state); below_kill достоверен
    # ТОЛЬКО при live-equity (её писатель — Веха 5.4; без неё dd_pct=0, сравнение бессмысленно) -> гейтим по `live`.
    kill_at_usd = (1.0 - kill_dd) * peak if peak > 0 else 0.0
    alarm_at_usd = (1.0 - alarm_dd) * peak if peak > 0 else 0.0
    below_kill = bool(live and peak > 0 and equity < kill_at_usd)

    return {
        "cap": cap, "acc": acc, "hb": hb,
        "working": working, "cushion": cushion, "ratio": ratio, "peak": peak, "equity": equity,
        "dd_pct": dd_pct, "dd_usd": dd_usd, "kill_dd": kill_dd, "alarm_dd": alarm_dd,
        "kill_at_usd": kill_at_usd, "alarm_at_usd": alarm_at_usd, "below_kill": below_kill,
        "ks_active": ks_active, "al_active": al_active, "state": state, "zone": zone,
        "equity_live": live,
        "hb_age_s": hb_age_s, "ws_alive": ws_alive, "stale": stale, "banner": banner,
    }


def build_monitor(db, *, capital_store, config_store, state_store, now_ms=None, use_demo=None, stale_sec=None,
                  range_days=None, prices=None):
    """Вью-модель монитора. now_ms/use_demo/stale_sec инъектируемы (тесты/контроллер); по умолчанию —
    реальные (use_demo<-config.ops.USE_DEMO; stale_sec<-2×HEARTBEAT_SEC, чтобы здоровый бот с каденцией
    heartbeat не давал ложный «обрыв»). range_days — окно кривой капитала (7/30); None = вся история («Всё»)."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if use_demo is None:
        use_demo = config.ops.USE_DEMO
    if stale_sec is None:
        stale_sec = 2 * config.ops.HEARTBEAT_SEC            # 2× каденции записи heartbeat (как legacy ~10мин)

    config_store, _ = _display_config(db, config_store)   # показ = ПРАВДА воркера, не env дашборда (unified_config_source)
    d = _derive_capital_status(db, capital_store, config_store, now_ms=now_ms, stale_sec=stale_sec)
    acc, hb = d["acc"], d["hb"]
    setups = state_store.all()                      # {symbol: setup} (может быть пусто)
    cap_n = int(_f(config_store.get("CONCURRENCY_CAP"), 8))

    # ── тайлы (из setup_state) ──
    open_legs = pending_legs = 0
    for s in setups.values():
        for leg in (s.get("legs") or {}).values():
            st = leg.get("state") if isinstance(leg, dict) else None    # устойчивость к битой строке БД
            if st == _OPEN:
                open_legs += 1
            elif st == _PENDING:
                pending_legs += 1

    # ── fill-rate (касаний/залито за всё время) ──
    fr = db.fillrate_counts()
    fr_pct = (fr["filled"] / fr["touches"]) if fr["touches"] else None

    # окно кривой капитала: 7/30д → фильтр ts_ms>=since (без капа точек); «Всё» (None) → вся история, кап 5000 точек
    # (≈7 мес при каденции ~1ч — с запасом покрывает demo-горизонт; защита от гигантского payload, аудит cos-1).
    if range_days:
        eq_since, eq_limit = now_ms - int(range_days) * 86_400_000, None
    else:
        eq_since, eq_limit = None, 5000
    curve = [{"ts_ms": _i(r.get("ts_ms")), "equity": _f(r.get("total_equity"))}
             for r in db.equity_history_recent(limit=eq_limit, since_ms=eq_since) if _i(r.get("ts_ms")) is not None]
    # размах истории (дни от самой ранней точки до сейчас) — фронт гасит пилюли периода длиннее наработанного
    # (30д недоступна, пока бот крутится <30 дней; 30д≡Всё разъедутся сами позже). fail-soft: нет истории → 0.
    _first_ts = None
    try:
        _first_ts = db.equity_first_ts_ms()
    except Exception:
        _first_ts = None
    equity_span_days = ((now_ms - _first_ts) / 86_400_000.0) if _first_ts else 0.0

    # позиции/ждущие: парсим JSON на сервере и гарантируем типы контракта (list)
    pos = _parse_json(acc.get("positions")) if acc else []
    positions = pos if isinstance(pos, list) else []
    pending = [dict(r, payload=_parse_json(r.get("payload"), {})) for r in db.orders_open_all()]

    # биржевые фигуры плашки «Баланс счёта» — LIVE mark-to-market по СВЕЖИМ ценам (prices, ~15с), а НЕ по снимку
    # воркёра (~15мин): нереализ. P&L / «в позициях» / equity двигаются ВМЕСТЕ С КОТИРОВКАМИ (owner). Это ОЦЕНКА
    # между 15-мин снимками воркёра (last-цена ≈ mark; без фандинга/комиссий с последнего снимка) — сверяется с
    # биржевым снимком каждые 15 мин. Fail-soft ПО ПОЗИЦИИ: нет свежей цены символа → та позиция берёт значения
    # снимка. ⚠ dd/kill-switch/гейдж НЕ трогаем — они на БИРЖЕВОМ снимке (d[...]) = безопасность. realised — журнал.
    prices = prices or {}
    _snap_unrealised = sum(_f(p.get("unrealisedPnl")) for p in positions)   # Σ нереализ. по СНИМКУ (для вывода wallet)
    unrealised_pnl = 0.0
    in_positions_usd = 0.0
    for p in positions:
        _px = prices.get(str(p.get("symbol")))
        _sz, _avg = _f(p.get("size")), _f(p.get("avgPrice"))
        if _px is not None and _avg:                        # свежая цена есть → mark-to-market по last
            _short = str(p.get("side", "")).lower().startswith("s")
            _upl = _sz * (_avg - _px if _short else _px - _avg)
            _val = _sz * _px
        else:                                               # fail-soft: та позиция — из снимка воркёра
            _upl = _f(p.get("unrealisedPnl"))
            _val = _sz * _f(p.get("markPrice"))
        p["live_pnl"] = _upl                                # per-position ЖИВОЙ P&L → «Открытые позиции» обновляются ~15с
        unrealised_pnl += _upl
        in_positions_usd += _val
    open_count = len(positions)
    realised_pnl = db.closed_trades_pnl_total()
    # equity LIVE = осевший баланс (биржевой снимок − Σ нереализ. снимка) + Σ ЖИВОГО нереализ. По-честному «equity =
    # свободный баланс + текущий нереализ.». Нет биржевого снимка (equity=0) → отдаём как есть (UI пометит оценкой).
    _eq_snap = _f(d.get("equity"))
    equity_display = (_eq_snap - _snap_unrealised + unrealised_pnl) if _eq_snap else _eq_snap

    # bot_health под-шаг 4: лёгкое подмножество для чипов строки «Главной» — связь с биржей (из heartbeat) +
    # число греющихся кандидатов (из snapshot). Один доп. запрос на /api/data-тик; boot_count НЕ трогаем (тяжело).
    _exch_ms = _i((d.get("hb") or {}).get("last_exchange_ok_ms"))
    _exch_age = (now_ms - _exch_ms) / 1000.0 if _exch_ms is not None else None
    _exch_ok = _exch_age is not None and _exch_age <= 3 * config.ops.HEARTBEAT_SEC
    _snap = db.scan_snapshot_get()
    _warming = len(_snap.get("candidates") or []) if _snap else 0

    # ── коин-борд «Монеты · котировки» (dashboard_live_glavnaya): включённые монеты + живая цена + флаг позиции.
    # Цена — из инъектируемого prices (keyless публичный Bybit; fail-soft None → «—», одометр рисует «—»);
    # позиция — символ есть в снимке позиций с ненулевым размером (медная каёмка чипа на «Главной»).
    prices = prices or {}
    pos_syms = {str(p.get("symbol")) for p in positions if _f(p.get("size"))}
    coins = [{"symbol": s, "price": prices.get(s), "has_position": s in pos_syms}
             for s in sorted(sym for sym, cc in config.strategy.COINS_CONFIG.items() if cc.get("enabled"))]

    return {
        "status": {
            "ws_alive": d["ws_alive"], "stale": d["stale"], "heartbeat_age_s": d["hb_age_s"],
            "active_setups": int(hb["active_setups"]) if (hb and hb.get("active_setups") is not None) else len(setups),
            "demo": bool(use_demo) if use_demo is not None else None,
            "banner": d["banner"],
            "exchange_ok": _exch_ok, "exchange_seen": _exch_ms is not None, "exchange_age_s": _exch_age,
            "warming": _warming,
        },
        "capital": {
            "working": d["working"], "cushion": d["cushion"], "ratio": d["ratio"], "equity": equity_display,
            "equity_live": d["equity_live"],   # False -> equity = ОЦЕНКА по леджеру (нет снимка биржи), UI помечает
            "peak_equity": d["peak"], "dd_pct": d["dd_pct"], "dd_usd": d["dd_usd"],
            "killswitch_dd": d["kill_dd"], "alarm_dd": d["alarm_dd"],
            "kill_at_usd": d["kill_at_usd"], "alarm_at_usd": d["alarm_at_usd"], "below_kill": d["below_kill"],
            "state": d["state"], "killswitch_active": d["ks_active"], "alarm_active": d["al_active"],
            # биржевые фигуры плашки (capital_card_redesign): нереализ. P&L (Σ открытых), реализ. (журнал),
            # экспозиция $ + число открытых (медальон). «Свободно» не отдаём — нет чистого availableBalance в снимке.
            "unrealised_pnl": unrealised_pnl, "in_positions_usd": in_positions_usd,
            "open_count": open_count, "realised_pnl": realised_pnl,
            # gauge.stale -> серый гейдж при обрыве (docs/11), отдельно от dd-зоны
            "gauge": {"dd_pct": d["dd_pct"], "alarm_at": d["alarm_dd"], "kill_at": d["kill_dd"],
                      "zone": d["zone"], "stale": d["stale"]},
        },
        "tiles": {"warmed": len(setups), "open": open_legs, "pending": pending_legs,
                  "exposure": f"{open_legs}/{cap_n}", "cap": cap_n},
        "positions": positions,
        "coins": coins,
        "pending": pending,
        # «История» = ЗАКРЫТЫЕ сделки с честным per-trade P&L (trade_history_pnl): воркер до-сохраняет реальный
        # Bybit closed-pnl (fills = ВХОДЫ, остаются для WS-края/fill-rate, но на «Главной» показываем финиш).
        "trades": db.closed_trades_recent(200),   # запас показа истории (сумма-плашка — closed_trades_pnl_total, полная)
        "signals": db.signals_recent(50),
        "events": db.events_recent(50),
        "fillrate": {"filled": fr["filled"], "touches": fr["touches"], "pct": fr_pct},
        # паритет live↔движок (✓/⚠) пишет parity-гейт/движок — Веха 5; форма стабильна (dict, как fillrate)
        "parity": {"status": "nodata", "mismatches": 0},
        "equity_curve": curve,
        "equity_curve_range": (int(range_days) if range_days else "all"),   # активная пилюля периода
        "equity_span_days": round(equity_span_days, 2),                     # размах истории → доступность пилюль
    }


def _warm_candidate_view(row):
    """Плоский вид warm-кандидата для фронта (5.8 п.5a; payload снимка = дескриптор warm.classify). entries
    после JSON-раунда — со СТРОКОВЫМИ ключами ('0.382'); отдаём готовые поля (числа фронт округляет сам)."""
    p = _parse_json(row.get("payload"), {}) or {}
    e = p.get("entries") or {}
    _e = lambda k: e.get(str(k), e.get(k))
    return {
        "symbol": row.get("symbol"), "kind": p.get("kind"),
        "auto_eligible": bool(p.get("auto_eligible")), "reanchored": bool(p.get("reanchored")),
        "side": p.get("side"), "age_bars": p.get("age_bars"),
        "entry_0382": _e(0.382), "entry_05": _e(0.5), "entry_0618": _e(0.618),
        "stop": p.get("stop"), "est_risk_pct": p.get("est_risk_pct"),
        "price_now": p.get("price_now"), "note": p.get("note"),
    }


_FOUR_H_MS = 4 * 3600 * 1000


def _health_scan(db, d, config_store, now_ms):
    """Блок «Здоровье и работа бота» для карточки (bot_health под-шаг 3). Собирает из ГОТОВЫХ снимков
    (heartbeat/worker_boot/scan_snapshot — под-шаги 1-2) + расчёта капитала `d`. Всё fail-soft (нет данных → None/«—»).
    Светофор: 🔴 kill-switch/обрыв heartbeat; 🟡 тревога/пауза/биржа молчит/heartbeat стареет; 🟢 иначе."""
    hb = d.get("hb") or {}
    start_ms = _i(hb.get("process_start_ms"))
    exch_ms = _i(hb.get("last_exchange_ok_ms"))
    hb_age_s = d.get("hb_age_s")
    pause = bool(config_store.get("PAUSE_ENABLED"))
    ks, al, stale = d.get("ks_active"), d.get("al_active"), d.get("stale")
    exch_age_s = (now_ms - exch_ms) / 1000.0 if exch_ms is not None else None
    exch_stale = 3 * config.ops.HEARTBEAT_SEC                         # биржа «молчит», если ответ старше ~3× каденции
    exch_ok = exch_age_s is not None and exch_age_s <= exch_stale
    if ks or stale:
        light = "red"
    elif (al or pause or (exch_ms is not None and not exch_ok)
          or (exch_ms is None and start_ms is not None and (now_ms - start_ms) > 600_000)   # жив >10мин, а с биржей 0 связи (кривые ключи/сеть) — не зелёный
          or (hb_age_s is not None and hb_age_s > config.ops.HEARTBEAT_SEC)):
        light = "amber"
    else:
        light = "green"
    snap = db.scan_snapshot_get()
    scan = None
    if snap:
        next_4h = ((now_ms // _FOUR_H_MS) + 1) * _FOUR_H_MS
        scan = {"ts_ms": _i(snap.get("ts_ms")), "coins_scanned": snap.get("coins_scanned"),
                "signals_found": snap.get("signals_found"), "candidates": snap.get("candidates") or [],
                "next_scan_s": max(0.0, (next_4h - now_ms) / 1000.0)}
    return {
        "light": light,
        "process_start_ms": start_ms,
        "uptime_s": (now_ms - start_ms) / 1000.0 if start_ms is not None else None,
        "exchange_seen": exch_ms is not None, "exchange_ok": exch_ok, "exchange_age_s": exch_age_s,
        "heartbeat_age_s": hb_age_s, "heartbeat_sec": config.ops.HEARTBEAT_SEC,
        "restarts_24h": int(db.boot_count_since(now_ms - 24 * 3600 * 1000)),
        "pause": pause, "alarm": bool(al), "killswitch": bool(ks), "state": d.get("state"),
        "ws": {"alive": d.get("ws_alive"), "drops": _i(hb.get("drops")),
               "reconnect": _i(hb.get("reconnect_count")), "msgs": _i(hb.get("msgs_received"))},
        "scan": scan,
    }


def build_settings(db, *, capital_store, config_store, use_demo=None, control=None, now_ms=None, stale_sec=None,
                   prices=None):
    """Вью-модель вкладки «Настройки» (ф.4). knobs — крутилки с UI-метаданными (PAUSE_ENABLED вынесен в
    `pause`, не в сетку); per_coin — read-only показ COINS_CONFIG (enabled); journal — последние изменения
    (action-строки помечены kind); status — баннер/просадка (общий расчёт с монитором); control —
    {configured, unlocked} (задан ли пароль управления и разблокирована ли control-сессия). БЕЗ csrf в теле."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if use_demo is None:
        use_demo = config.ops.USE_DEMO
    if stale_sec is None:
        stale_sec = 2 * config.ops.HEARTBEAT_SEC

    config_store, worker_cfg_ms = _display_config(db, config_store)   # показ = ПРАВДА воркера (unified_config_source)
    d = _derive_capital_status(db, capital_store, config_store, now_ms=now_ms, stale_sec=stale_sec)
    knobs_view = [_knob_view(k, config_store) for k in knobs.KNOBS
                  if KNOB_UI.get(k, {}).get("group") != "_emergency"]
    prices = prices or {}                               # {symbol: текущая цена} (cos-2; нет → «—» на фронте)
    per_coin = sorted(
        [{"symbol": s, "enabled": bool(c.get("enabled")), "mb1": c.get("mb1"), "mb2": c.get("mb2"),
          "leverage": c.get("leverage"), "weight": c.get("weight"), "price": prices.get(s)}
         for s, c in config.strategy.COINS_CONFIG.items() if c.get("enabled")],
        key=lambda x: x["symbol"])                      # cos-2: стабильный порядок по алфавиту (серверный контракт)

    return {
        "knobs": knobs_view,
        "groups": list(GROUP_ORDER),                    # порядок секций для settings.js (стабильный контракт)
        "per_coin": per_coin,
        "capital_mode": config.capital.CAPITAL_MODE,
        "journal": [_journal_row(r) for r in config_store.log(limit=50)],
        "pause": bool(config_store.get("PAUSE_ENABLED")),
        "demo": bool(use_demo),
        # свежесть env-снимка воркера (None если не публиковал) — для подписи «конфиг воркера от <t>»; мёртвый
        # воркер + стале-снимок распознаётся по heartbeat-age (status.stale), чтобы старьё не выдавать за свежее.
        "worker_config_updated_ms": worker_cfg_ms,
        "status": {
            "banner": d["banner"], "state": d["state"], "stale": d["stale"],
            "dd_pct": d["dd_pct"], "zone": d["zone"],
            "killswitch_active": d["ks_active"], "alarm_active": d["al_active"],
            "killswitch_dd": d["kill_dd"], "alarm_dd": d["alarm_dd"],
            # пороги срабатывания в $ + below_kill для кнопки «Снять стоп» (5.3a); below_kill достоверен лишь при live-equity
            "peak_equity": d["peak"], "equity_live": d["equity_live"],
            "kill_at_usd": d["kill_at_usd"], "alarm_at_usd": d["alarm_at_usd"], "below_kill": d["below_kill"],
        },
        "control": control if control is not None else {"configured": False, "unlocked": False},
        # тёплый старт (5.8 п.5): снимок кандидатов для превью-панели. Тумблер WARM_ON_START — в knobs (Режимы).
        "warm": {"candidates": [_warm_candidate_view(r) for r in db.warm_candidates_all()]},
        # bot_health под-шаг 3: карточка «Здоровье и работа бота» (жив/связь/рестарты/WS + скан + греющиеся)
        "health": _health_scan(db, d, config_store, now_ms),
    }


# ── Разведчик (Веха 7, под-шаг 5): вью-модель страницы /scout (read-only, fail-soft) ──
_SCOUT_STATUS = {
    "ready": {"label": "готов · в зоне входа", "chip": "ready", "rank": 0},
    "tracking": {"label": "тянется · ждём откат", "chip": "tracking", "rank": 1},
    "forming": {"label": "греется", "chip": "forming", "rank": 2},
}


def _scout_finding_view(f, bars_by_symbol):
    """Одна находка → строка UI. f — payload находки (+ status/symbol/score/tf сверху). Бары — из САМОЙ
    находки (per-ТФ, под-шаг 7a), фолбэк на scout_list-скаляр (4h, старые строки)."""
    st = f.get("status")
    meta = _SCOUT_STATUS.get(st, {"label": st, "chip": "muted", "rank": 9})
    fb = bars_by_symbol.get(f.get("symbol"), {})
    mb1 = f.get("mb1") if f.get("mb1") is not None else fb.get("mb1")
    mb2 = f.get("mb2") if f.get("mb2") is not None else fb.get("mb2")
    row = {
        "symbol": f.get("symbol"),
        "tf": f.get("tf") or "4h",
        "status": st, "status_label": meta["label"], "chip": meta["chip"], "rank": meta["rank"],
        "score": _f(f.get("score")),
        "mb1": _f(mb1), "mb2": _f(mb2), "bar_source": f.get("bar_source") or fb.get("bar_source"),
        "note": f.get("note"),
    }
    if st == "forming":
        row.update({
            "consolidation_bars": f.get("consolidation_bars"),
            "breakout_dist_pct": _f(f.get("breakout_dist_pct")),
            "cancel_dist_pct": _f(f.get("cancel_dist_pct")),
        })
    else:                                               # ready / tracking (есть уровни входа/стопа)
        row.update({
            "dist_to_entry_pct": _f(f.get("dist_to_entry_pct")),
            "dist_to_stop_pct": _f(f.get("dist_to_stop_pct")),
            "bars_since_anchor": f.get("bars_since_anchor"),
            "entries": f.get("entries"), "stop": f.get("stop"),
        })
    return row


def _bookmark_freshness(snap, cur):
    """Свежесть закладки: снимок точных уровней (snap) vs ТЕКУЩАЯ находка (cur, None если ушла).
    gone — сетап ушёл; moved — якорь B сместился >0.5%; status — статус изменился; fresh — актуальна."""
    if cur is None:
        return {"state": "gone", "label": "сетап ушёл"}
    b0, b1 = _f(snap.get("B")), _f(cur.get("B"))
    if b0 and b1 and b0 > 0 and abs(b1 - b0) / b0 > 0.005:
        return {"state": "moved", "label": "якорь сместился %+.1f%%" % ((b1 - b0) / b0 * 100.0)}
    if snap.get("status") != cur.get("status"):
        return {"state": "status", "label": "статус изменился"}
    return {"state": "fresh", "label": "актуальна"}


def build_scout(db, *, now_ms=None):
    """Вью-модель страницы «Разведчик» (Веха 7). FAIL-SOFT: нет данных/таблиц скаута → пустая структура
    (страница покажет «скан ещё не запускался»). Дашборд ТОЛЬКО читает scout_* (пишет сервис-скаут)."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    try:
        findings_raw = db.scout_findings_all()
    except Exception:
        findings_raw = []
    try:
        listed = db.scout_list_all()
    except Exception:
        listed = []
    try:
        meta = db.scout_meta_get()
    except Exception:
        meta = None
    meta = meta if isinstance(meta, dict) else {}

    bars_by_symbol = {r.get("symbol"): {"mb1": _f(r.get("mb1")), "mb2": _f(r.get("mb2")),
                                        "bar_source": r.get("bar_source")} for r in listed}
    findings, raw_by = [], {}
    for r in findings_raw:
        p = _parse_json(r.get("payload"), {}) or {}
        p["status"], p["symbol"], p["score"], p["tf"] = r.get("status"), r.get("symbol"), r.get("score"), r.get("tf")
        raw_by[(r.get("symbol"), r.get("tf") or "4h")] = p         # ключ (symbol, tf) — 4h/1h сосуществуют (под-шаг 7)
        findings.append(_scout_finding_view(p, bars_by_symbol))
    findings.sort(key=lambda x: (x["rank"], -(x["score"] or 0)))    # рекомендация: нетронутые + высокий скор сверху

    # закладки владельца (под-шаг 6): пометить находки + свежесть (снимок vs текущее ТОГО ЖЕ ТФ, под-шаг 7)
    try:
        sels = db.scout_selections_all()
    except Exception:
        sels = []
    view_by = {(f["symbol"], f["tf"]): f for f in findings}
    bookmarks = []
    for s in sels:
        sym = s.get("symbol")
        snap = _parse_json(s.get("payload"), {}) or {}
        stf = snap.get("tf") or "4h"
        fr = _bookmark_freshness(snap, raw_by.get((sym, stf)))
        v = view_by.get((sym, stf))
        if v is not None:
            v["bookmarked"] = True
            v["freshness"] = fr
        bookmarks.append({"symbol": sym, "tf": stf, "ts_ms": s.get("ts_ms"), "present": (sym, stf) in raw_by,
                          "freshness": fr, "snap_status": snap.get("status")})
    for f in findings:
        f.setdefault("bookmarked", False)

    # счётчики статусов ПО ТФ (под-шаг 7: переключатель фильтрует клиентски по выбранному ТФ)
    counts_by_tf = {}
    for f in findings:
        c = counts_by_tf.setdefault(f["tf"], {"ready": 0, "tracking": 0, "forming": 0})
        if f["status"] in c:
            c[f["status"]] += 1
    tfs_available = sorted(counts_by_tf.keys(), key=lambda t: (t != "4h", t)) or ["4h"]   # 4h первым
    funnel = meta.get("funnel", {}) if isinstance(meta.get("funnel"), dict) else {}
    return {
        "has_data": bool(findings) or bool(listed),
        "updated_ms": meta.get("ts_ms"),
        "tf": "4h",                                          # дефолтный показ (валидированный трек)
        "tfs_available": tfs_available,
        "funnel": {
            "universe_total": funnel.get("universe_total"),
            "stablecoins": funnel.get("stablecoins"),
            "klines_fetched": funnel.get("klines_fetched"),
            "passed": funnel.get("passed"),
            "list_size": funnel.get("list_size") if funnel.get("list_size") is not None else len(listed),
        },
        "counts_by_tf": counts_by_tf,
        "findings": findings,
        "bookmarks": bookmarks,
        "bookmarks_count": len(bookmarks),
        "disclaimer": ("«Разведчик» показывает СТРУКТУРУ паттерна и КАЧЕСТВО монеты — это НЕ предсказание "
                       "прибыли. Generic-бары (не боевые) не проверены held-out. Вход — решение владельца."),
        "oos_note": ("1h — предпросмотр ДРУГОГО режима: честный OOS-бэктест НЕ пройден. Быстрее, но край на сделку "
                     "меньше, а трение (комиссия/слиппедж/funding) кусает сильнее. Только структура — НЕ совет входить."),
    }


def build_scout_chart(db, symbol, *, tf=None, n=90):
    """Данные окна графика монеты (Веха 7, под-шаг 5b): свечи из кэша scout_klines + уровни находки
    (для оверлея сетки/стопа/пробоя). FAIL-SOFT: нет данных → candles=[], finding=None."""
    ftf = tf or "4h"
    try:
        finding = db.scout_finding_get(symbol, tf=ftf)     # tf-aware (под-шаг 7): уровни ИМЕННО этого ТФ
    except Exception:
        finding = None
    try:
        candles = db.scout_klines_read_window(symbol, ftf, n)
    except Exception:
        candles = []
    return {"symbol": symbol, "tf": ftf, "candles": candles, "finding": finding}

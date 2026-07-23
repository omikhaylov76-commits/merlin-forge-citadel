"""F-lookahead v3 (подпись Куратора): вселенная ОТ ДВИЖКА — placeable-отбор по warm.classify из
scout_list, вместо скаут-курации. Против НАСТОЯЩЕГО вендора (урок vendor-integration-tests):
реальная storage.db (scout_list + scout_klines) + живой `warm.classify` на синт-сериях (калиброваны
зондом по detect_v81 (те же, что test_engine_truth). Плюс регресс-гвоздь: DYNAMIC_SOURCE=scout
(дефолт) == прежний путь байт-в-байт.
"""
import types

from storage.db import DB

from app.dynamic_universe import DynamicUniverse
from app.scout_reader import ScoutReader
from tests.test_engine_truth import H4, NOW, _rows

# Серии откалиброваны зондом под mb1=2.0/mb2=3.5 — те пороги, что провайдер пишет в coins.json
# (движок REPLACE). S8 per-coin бары: pool несёт эти mb в scout_list → placeable_scan классифицирует
# ими (не форс _DEFAULT_COIN), coins.json получает per-coin бары. Проверка per-coin — тесты ниже.
_IMP = [(100.0, 105.0, 99.8, 104.8)]                       # импульс-1: 5% чистый (>mb1 2%)
_CONS = [(104.8, 105.0, 103.5, 104.0)]                     # консолидация без отмены
_BRK = [(104.0, 109.6, 103.9, 109.4)]                      # пробой 5.5% (>mb2 3.5%)
_HOVER = [(109.4, 109.6, 108.0, 108.8), (108.8, 109.5, 108.0, 109.0)]    # висим над входами
_NEWHI = [(109.4, 114.0, 109.2, 113.6), (113.6, 114.0, 112.5, 113.0)]    # REBUILD → пере-якорь
_DIP = [(108.0, 108.3, 105.0, 105.5), (105.5, 106.0, 105.0, 105.8)]      # залив входа 0.382
_CRASH = [(109.4, 109.6, 99.0, 99.5), (99.5, 100.0, 99.0, 99.8)]         # до стопа → закрыт


def _flat(n):
    return [(100.0, 100.3, 99.7, 100.0) for _ in range(n)]


_AUTO = _flat(60) + _IMP + _CONS + _BRK + _HOVER           # PENDING auto_eligible → самоход ставит
_REAN = _flat(60) + _IMP + _CONS + _BRK + _NEWHI           # PENDING reanchored → «нужна кнопка»
_OPEN = _flat(60) + _IMP + _CONS + _BRK + _DIP             # OPEN (нога залита) → не placeable
_DEAD = _flat(60) + _IMP + _CONS + _BRK + _CRASH           # None (реплей закрыл) → не placeable

# монеты пула (scout_list) с сериями и скором КАЧЕСТВА
POOL = {
    "AUTOUSDT": (_AUTO, 90),
    "AUTO2USDT": (_AUTO, 60),        # ещё один auto (приоритет/сорт по скору качества)
    "BTNUSDT": (_REAN, 88),          # reanchored → после auto
    "OPENUSDT": (_OPEN, 95),         # OPEN → НЕ placeable, топ-скор не спасает
    "DEADUSDT": (_DEAD, 99),         # None → НЕ placeable, топ-скор не спасает
}


def _reader(tmp_path):
    path = str(tmp_path / "scout.db")
    db = DB(db_path=path, owner=True, database_url="")
    db.scout_control_mark(last_b_boundary_ms=NOW)             # ненулевой курсор скана
    # курированный ПУЛ (scout_list) + свежие свечи каждой монеты (Этап B их докачивает в проде).
    # S8: mb 2.0/3.5 — калибровка серий; per-coin classify берёт ИХ (не форс дефолт).
    db.scout_list_put_snapshot(
        [{"symbol": s, "score": sc, "mb1": 2.0, "mb2": 3.5, "bar_source": "volnorm-v1"}
         for s, (_, sc) in POOL.items()], NOW)
    for s, (quads, _) in POOL.items():
        db.scout_klines_put_many(s, "4h", _rows(quads))
    r = ScoutReader(scout_db_path=path, worker_reader=object(),
                    detector_version="test", producer="test")
    return r, db


def _provider(tmp_path, reader, **crit):
    cfg = types.SimpleNamespace(
        dynamic_source="engine", dynamic_coins_path=str(tmp_path / "coins.json"),
        dynamic_stack_max=crit.get("stack_max", 10), dynamic_enter_scans=1, dynamic_exit_scans=2,
        dynamic_min_write_s=0.0, dynamic_criteria_path="",
        dynamic_min_score=crit.get("min_score", 0), dynamic_fresh_bars=0,
        dynamic_bars_refresh_s=crit.get("bars_refresh_s", 2_592_000.0))   # S8: ритм refresh баров
    return DynamicUniverse(cfg, reader)


# ── Слой 1: placeable_scan против живого вендора ──────────────────────────────

def test_placeable_scan_picks_only_pending(tmp_path):
    """warm.classify по пулу: PENDING (auto|reanchored) → placeable; OPEN/None → мимо."""
    r, _ = _reader(tmp_path)
    scan_ms, placeable = r.placeable_scan()
    assert scan_ms == NOW
    assert set(placeable) == {"AUTOUSDT", "AUTO2USDT", "BTNUSDT"}   # OPEN/DEAD отсеяны
    assert placeable["AUTOUSDT"]["auto_eligible"] and not placeable["AUTOUSDT"]["reanchored"]
    assert placeable["BTNUSDT"]["reanchored"] and not placeable["BTNUSDT"]["auto_eligible"]
    assert "OPENUSDT" not in placeable    # OPEN (в позиции) — не свежая постановка
    assert "DEADUSDT" not in placeable    # None (реплей закрыл) — не placeable
    r.close()


def test_placeable_scan_uses_per_coin_mb_over_static(tmp_path):
    """S8 per-coin бары (ЗАМЕНЯЕТ форс-хак _DEFAULT_COIN): монета с ЧУЖИМ mb в COINS_CONFIG (стейл
    статик-вендора вроде AAVE 2.5/4.0) классифицируется mb ИЗ scout_list (2.0/3.5) — вердикт
    == постановка движка (coins.json REPLACE пишет ТУ ЖЕ mb). Иначе universe разошёлся бы."""
    import config as vcfg
    r, _ = _reader(tmp_path)
    # пред-ставим AUTOUSDT ЖЁСТКИЙ mb, при котором его 5.5%-пробой НЕ прошёл бы (mb2=9)
    vcfg.strategy.COINS_CONFIG["AUTOUSDT"] = {"enabled": True, "mb1": 8.0, "mb2": 9.0,
                                              "leverage": 5, "weight": 1.0}
    _, placeable = r.placeable_scan()
    assert "AUTOUSDT" in placeable                              # per-coin mb перебил жёсткий стейл
    assert vcfg.strategy.COINS_CONFIG["AUTOUSDT"]["mb2"] == 3.5   # scan_list mb, не стейл 9.0
    assert placeable["AUTOUSDT"]["mb1"] == 2.0                  # бары монеты — в дескрипторе
    assert placeable["AUTOUSDT"]["mb2"] == 3.5
    r.close()


def test_default_source_scout_uses_findings_not_placeable(tmp_path):
    """РЕГРЕСС-ГВОЗДЬ (условие подписи): дефолт (без dynamic_source) = scout-путь — провайдер зовёт
    findings_for_universe, НЕ placeable_scan. Флот и Борс-в-scout-режиме байт-в-байт."""
    calls = {"findings": 0, "placeable": 0}

    class _Spy:
        def findings_for_universe(self):
            calls["findings"] += 1
            return (0, [])

        def placeable_scan(self):
            calls["placeable"] += 1
            return (0, {})

    cfg = types.SimpleNamespace(       # БЕЗ dynamic_source — как старые конструкторы
        dynamic_coins_path=str(tmp_path / "coins.json"), dynamic_stack_max=3,
        dynamic_enter_scans=1, dynamic_exit_scans=2, dynamic_min_write_s=0.0,
        dynamic_criteria_path="", dynamic_min_score=0, dynamic_fresh_bars=0)
    dv = DynamicUniverse(cfg, _Spy())
    assert dv._source == "scout"       # дефолт
    dv.tick(1.0)
    assert calls == {"findings": 1, "placeable": 0}   # scout-путь: только findings


def test_engine_gates_expensive_scan_on_cursor(tmp_path):
    """EFFICIENCY: engine-режим гейтит ДЕШЁВЫМ last_scan_ms ДО дорогого placeable_scan.
    Тот же scan_ms второй раз → placeable_scan НЕ гоняется (не жжём CPU/лог каждый тик)."""
    calls = {"cursor": 0, "placeable": 0}

    class _Spy:
        def last_scan_ms(self):
            calls["cursor"] += 1
            return 500

        def placeable_scan(self):
            calls["placeable"] += 1
            return (500, {})

    cfg = types.SimpleNamespace(
        dynamic_source="engine", dynamic_coins_path=str(tmp_path / "coins.json"),
        dynamic_stack_max=3, dynamic_enter_scans=1, dynamic_exit_scans=2, dynamic_min_write_s=0.0,
        dynamic_criteria_path="", dynamic_min_score=0, dynamic_fresh_bars=0)
    dv = DynamicUniverse(cfg, _Spy())
    dv.tick(1.0)                                # новый scan_ms=500 → дорогой скан 1 раз
    dv.tick(2.0)                                # тот же 500 → гейт по курсору, placeable НЕ зовём
    assert calls == {"cursor": 2, "placeable": 1}


def test_scan_list_rows_reads_quality_pool(tmp_path):
    """scan_list_rows читает курированный scout_list вендора (symbol+score), не сырую вселенную."""
    r, _ = _reader(tmp_path)
    rows = {x["symbol"]: x["score"] for x in r.scan_list_rows()}
    assert rows == {"AUTOUSDT": 90, "AUTO2USDT": 60, "BTNUSDT": 88, "OPENUSDT": 95, "DEADUSDT": 99}
    r.close()


# ── Слой 2: провайдер в engine-режиме ────────────────────────────────────────

def test_engine_source_stack_is_placeable_only(tmp_path):
    """Стек engine-режима = ТОЛЬКО placeable (3), НЕ топ-скор OPEN/None (misalignment снят)."""
    r, _ = _reader(tmp_path)
    dv = _provider(tmp_path, r)
    dv.tick(2.0)
    assert {i["symbol"] for i in dv.view()["items"]} == {"AUTOUSDT", "AUTO2USDT", "BTNUSDT"}
    r.close()


def test_engine_source_auto_prioritised_over_reanchored(tmp_path):
    """Кап < числа placeable: auto-годные ПЕРВЫМИ (самоход возьмёт), reanchored — после."""
    r, _ = _reader(tmp_path)
    dv = _provider(tmp_path, r, stack_max=2)     # кап 2 из 3 placeable
    dv.tick(2.0)
    got = {i["symbol"] for i in dv.view()["items"]}
    assert got == {"AUTOUSDT", "AUTO2USDT"}       # два auto вошли, reanchored BTN не влез (кап)
    assert "BTNUSDT" not in got
    r.close()


def test_engine_source_writes_coins_json(tmp_path):
    """coins.json пишется per-coin блоком: mb1/mb2 ИЗ scout_list (S8), lev/weight — дефолт."""
    import json
    r, _ = _reader(tmp_path)
    dv = _provider(tmp_path, r)
    dv.tick(2.0)
    coins = json.load(open(tmp_path / "coins.json"))
    assert set(coins) == {"AUTOUSDT", "AUTO2USDT", "BTNUSDT"}
    assert coins["AUTOUSDT"] == {"enabled": True, "mb1": 2.0, "mb2": 3.5,
                                 "leverage": 5, "weight": 1.0}    # mb per-coin из пула, не флэт
    r.close()


def test_engine_source_min_score_quality_filter(tmp_path):
    """min_score канала в engine-режиме → доп-порог к скору КАЧЕСТВА scan_list (условие подписи)."""
    r, _ = _reader(tmp_path)
    dv = _provider(tmp_path, r, min_score=70)     # AUTO2 (60) отсекается по качеству
    dv.tick(2.0)
    assert {i["symbol"] for i in dv.view()["items"]} == {"AUTOUSDT", "BTNUSDT"}
    r.close()


def test_engine_source_pin_holds_open_position(tmp_path):
    """Предохранитель Вехи 2: held (открытая позиция) ЗАПИНЕН даже если не placeable (OPEN/None) —
    при переключении источника позиция не осиротеет (линза Куратора)."""
    r, _ = _reader(tmp_path)
    dv = _provider(tmp_path, r)
    dv.tick(2.0, frozenset({"DEADUSDT"}))         # позиция на DEAD (None-вердикт), но held
    v = {i["symbol"]: i for i in dv.view()["items"]}
    assert "DEADUSDT" in v and v["DEADUSDT"]["pinned"] is True   # пин держит, не placeable не важно
    r.close()


def test_engine_source_empty_pool_keeps_stack(tmp_path):
    """Пул пуст (scout_list не прочёлся) → placeable пуст → ПОЛ-НА-ПУСТОТУ держит набор."""
    r, _ = _reader(tmp_path)
    dv = _provider(tmp_path, r)
    dv.tick(2.0)
    assert dv.view()["count"] == 3
    r.scout_db.scout_list_put_snapshot([], NOW + H4)          # пул опустел
    r.scout_db.scout_control_mark(last_b_boundary_ms=NOW + H4)  # новый скан
    dv.tick(3.0)
    # placeable пуст → кандидатов нет; существующие уходят по exit-гистерезису, НЕ разом
    assert dv.view()["count"] == 3                            # missed=1 < exit=2 → держим
    r.close()


# ── S8 per-coin бары: проводка volnorm-mb из scout_list в coins.json (подпись Куратора) ──────

def _mb_auto_15(s):
    """AUTO → (1.5,2.5); прочие → (2.0,3.5). Меняем mb ТОЛЬКО у AUTO (sticky/refresh-тесты)."""
    return (1.5, 2.5, "config") if s == "AUTOUSDT" else (2.0, 3.5, "config")


def _put_pool(db, at_ms, mb_of):
    """Пере-положить весь POOL с per-coin mb (mb_of: sym→(mb1,mb2,src)) + двинуть курсор скана."""
    rows = []
    for s, (_, sc) in POOL.items():
        mb1, mb2, src = mb_of(s)
        rows.append({"symbol": s, "score": sc, "mb1": mb1, "mb2": mb2, "bar_source": src})
    db.scout_list_put_snapshot(rows, at_ms)
    db.scout_control_mark(last_b_boundary_ms=at_ms)


def test_scan_list_rows_carries_bars(tmp_path):
    """Слой 1: scan_list_rows несёт mb1/mb2/bar_source (вендор считает в Этапе A) — не дропает."""
    r, _ = _reader(tmp_path)
    row = {x["symbol"]: x for x in r.scan_list_rows()}["AUTOUSDT"]
    assert row["mb1"] == 2.0 and row["mb2"] == 3.5 and row["bar_source"] == "volnorm-v1"
    r.close()


def test_engine_writes_per_coin_bars_differentiated(tmp_path):
    """S8 ЯДРО ПРОВОДКИ: РАЗНЫЕ монеты → РАЗНЫЕ бары в coins.json (per-coin, не флэт 2.0/3.5)."""
    import json
    r, db = _reader(tmp_path)
    # два placeable с РАЗНОЙ mb (обе достаточно узкие — _AUTO 5%/5.5% пробой остаётся placeable)
    db.scout_list_put_snapshot([
        {"symbol": "AUTOUSDT", "score": 90, "mb1": 2.0, "mb2": 3.5, "bar_source": "volnorm-v1"},
        {"symbol": "AUTO2USDT", "score": 88, "mb1": 1.5, "mb2": 2.5, "bar_source": "config"},
    ], NOW)
    dv = _provider(tmp_path, r)
    dv.tick(2.0)
    coins = json.load(open(tmp_path / "coins.json"))
    assert coins["AUTOUSDT"]["mb1"] == 2.0 and coins["AUTOUSDT"]["mb2"] == 3.5
    assert coins["AUTO2USDT"]["mb1"] == 1.5 and coins["AUTO2USDT"]["mb2"] == 2.5   # свои бары
    r.close()


def test_engine_held_coin_freezes_bars_even_on_refresh(tmp_path):
    """Уточнение #2: held-монета держит бары, с которыми ВОШЛА, даже когда ритм refresh настал
    (bars_refresh_s=0) и mb пула сменилась — пороги под живой позицией не дёргаем."""
    import json
    r, db = _reader(tmp_path)
    dv = _provider(tmp_path, r, bars_refresh_s=0.0)   # refresh всегда «настал»
    dv.tick(2.0, frozenset())                          # AUTO входит с 2.0/3.5
    _put_pool(db, NOW + H4, _mb_auto_15)
    dv.tick(3.0, frozenset({"AUTOUSDT"}))              # AUTO теперь held → бары ЗАМОРОЖЕНЫ
    coins = json.load(open(tmp_path / "coins.json"))
    assert coins["AUTOUSDT"]["mb1"] == 2.0 and coins["AUTOUSDT"]["mb2"] == 3.5   # не пере-захвачены
    r.close()


def test_engine_non_held_recaptures_bars_on_refresh(tmp_path):
    """Ритм refresh (bars_refresh_s=0 = настал): НЕ-held стек-монета ПЕРЕ-захватывает свежую mb
    пула (Оператор: периодич. пересчёт баров). Sticky только в окне; окно истекло → новые бары."""
    import json
    r, db = _reader(tmp_path)
    dv = _provider(tmp_path, r, bars_refresh_s=0.0)
    dv.tick(2.0, frozenset())                          # AUTO входит 2.0/3.5
    _put_pool(db, NOW + H4, _mb_auto_15)
    dv.tick(3.0, frozenset())                          # НЕ held + refresh настал → пере-захват
    coins = json.load(open(tmp_path / "coins.json"))
    assert coins["AUTOUSDT"]["mb1"] == 1.5 and coins["AUTOUSDT"]["mb2"] == 2.5   # свежие бары
    r.close()


def test_engine_non_held_bars_sticky_within_window(tmp_path):
    """Sticky: в окне refresh (дефолт ~30д) не-held стек-монета держит бары ВХОДА, даже если mb пула
    сменилась — не дёргать пороги движка каждый скан (decouple от Этапа A, условие Оператора)."""
    import json
    r, db = _reader(tmp_path)
    dv = _provider(tmp_path, r)                        # дефолтный ~30д refresh (окно не истечёт)
    dv.tick(2.0, frozenset())                          # AUTO входит 2.0/3.5
    _put_pool(db, NOW + H4, _mb_auto_15)
    dv.tick(3.0, frozenset())                          # окно не истекло → sticky
    coins = json.load(open(tmp_path / "coins.json"))
    assert coins["AUTOUSDT"]["mb1"] == 2.0 and coins["AUTOUSDT"]["mb2"] == 3.5   # держит бары входа
    r.close()


def test_maybe_write_noop_when_content_unchanged(tmp_path):
    """Уточнение #1 (инверсия): новый скан с ТЕМ ЖЕ составом+барами → НЕ переписываем (сигнатура по
    содержимому не изменилась) → gen не бампаем зря (движок не рестартит на пустом месте)."""
    r, db = _reader(tmp_path)
    dv = _provider(tmp_path, r)
    dv.tick(2.0)                                       # первая запись
    assert dv._last_write_mono == 2.0
    _put_pool(db, NOW + H4, lambda s: (2.0, 3.5, "volnorm-v1"))   # новый скан, ИДЕНТИЧНЫЙ пул+mb
    dv.tick(3.0)
    assert dv._last_write_mono == 2.0                  # сигнатура та же → повторно НЕ писали
    r.close()


def test_engine_write_fallback_default_when_no_mb(tmp_path):
    """Уточнение #2 (фолбэк): held БЕЗ scan_list-mb (пришпилена вне пула) → coins.json дефолт-
    бары (mb неоткуда взять). Валидный блок — позиция не осиротеет."""
    import json
    r, _ = _reader(tmp_path)
    dv = _provider(tmp_path, r)
    dv.tick(2.0, frozenset({"GHOSTUSDT"}))             # held вне пула → пин без mb
    coins = json.load(open(tmp_path / "coins.json"))
    assert coins["GHOSTUSDT"] == {"enabled": True, "mb1": 2.0, "mb2": 3.5,
                                  "leverage": 5, "weight": 1.0}
    r.close()


def test_scout_source_writes_flat_default_bars(tmp_path):
    """РЕГРЕСС-ГВОЗДЬ: scout-режим (findings, не placeable) пишет флэт _DEFAULT_COIN байт-в-байт —
    per-coin бары ТОЛЬКО engine-путь. Флот/Персиваль/Галахад не задеты (стек findings без mb)."""
    import json

    class _Spy:
        def findings_for_universe(self):
            return (500, [{"symbol": "SCOUTUSDT", "tf": "4h", "state": "ready", "score": 80,
                           "bars_since_anchor": 1}])

    cfg = types.SimpleNamespace(          # scout-режим (без dynamic_source)
        dynamic_coins_path=str(tmp_path / "coins.json"), dynamic_stack_max=5,
        dynamic_enter_scans=1, dynamic_exit_scans=2, dynamic_min_write_s=0.0,
        dynamic_criteria_path="", dynamic_min_score=0, dynamic_fresh_bars=0)
    dv = DynamicUniverse(cfg, _Spy())
    dv.tick(1.0)
    coins = json.load(open(tmp_path / "coins.json"))
    assert coins == {"SCOUTUSDT": {"enabled": True, "mb1": 2.0, "mb2": 3.5,
                                   "leverage": 5, "weight": 1.0}}   # флэт, per-coin не просочился


def test_view_exposes_per_coin_bars(tmp_path):
    """view() (engine_state.stack) несёт mb1/mb2/bar_source монеты → Оператор видит РЕАЛЬНЫЕ
    бары движка (визуальная сверка Куратора: не плоские 2.0/3.5)."""
    r, _ = _reader(tmp_path)
    dv = _provider(tmp_path, r)
    dv.tick(2.0)
    item = {i["symbol"]: i for i in dv.view()["items"]}["AUTOUSDT"]
    assert item["mb1"] == 2.0 and item["mb2"] == 3.5 and item["bar_source"] == "volnorm-v1"
    r.close()


def test_coin_block_falls_back_on_bad_mb():
    """Fail-soft (само-ревью): мусорная/непозитивная mb (порча scout_list) → дефолт-бары, НЕ битый
    coins.json — иначе config.validate отвергнет ВСЮ вселенную (движок на _DEFAULT_COINS_CONFIG)."""
    from app.dynamic_universe import coin_block
    assert coin_block(2.0, 3.5) == {"enabled": True, "mb1": 2.0, "mb2": 3.5,
                                    "leverage": 5, "weight": 1.0}   # валидные → сквозь
    assert coin_block(None, 3.5)["mb1"] == 2.0          # неполна → дефолт
    assert coin_block(0.0, 3.5)["mb1"] == 2.0           # ≤0 → дефолт (0 уронил бы validate)
    assert coin_block(-1.0, 3.5)["mb2"] == 3.5          # отрицательная → дефолт
    assert coin_block("junk", 3.5)["mb1"] == 2.0        # не число → дефолт

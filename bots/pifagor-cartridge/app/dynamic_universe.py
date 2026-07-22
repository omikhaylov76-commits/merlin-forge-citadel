"""DynamicUniverse — провайдер динамической вселенной (S8 «Динамо-близнец», ADR-0019).

Живёт в адаптере картриджа (один процесс со scout_reader). Читает свежие сетапы печки, держит СТЕК
рабочих монет ≤N (предохранитель), и при стабильной смене набора пишет coins.json атомарно + бампает
.gen → супервизор start.sh мягко рестартит ТОЛЬКО движок → тот подхватывает вселенную через разъём
COINS_CONFIG_PATH (ADR-0019).

Анти-thrash (рестарт-луп): (1) только на НОВЫЙ scan_ts; (2) гистерезис входа/выхода;
(3) min-интервал записи; (4) ПОЛ НА ПУСТОТУ — пустой набор не пишем, gen не бампаем.
Слот свободен по стадии/отсутствию (dry-run). Веха 2: слот занят позицией — гейт (ADR-0019).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile

from app.dynamic_overrides import read_criteria  # живое чтение файла-критериев (ADR-0020 D1)

log = logging.getLogger("mfc.pifagor-cartridge")

# Дефолтный per-coin блок scout-монет (ADR-0019 F6): parity-приближение, НЕ боевая настройка;
# пересмотр перед Вехой 2. Проходит config.validate (mb1/mb2>0, lev 1..5, weight>0).
_DEFAULT_COIN = {"enabled": True, "mb1": 2.0, "mb2": 3.5, "leverage": 5, "weight": 1.0}
# Решение Оператора (живая сверка Вехи 2): БЕЗ "forming" — сетап ещё зарождается, не факт что
# родится (не кандидат в торговую вселенную); committed — производная UI, не стадия печки.
_ACTIVE_STAGES = ("tracking", "ready")
# Решение Оператора: движок торгует ТОЛЬКО 4h (config.strategy.SIGNAL_TF="4h" — vendor, ОДНОЗНАЧНО
# захардкожен здесь, не импортируем vendor в 0-vendor модуль); 1h-находки скаута для ЭТОГО движка
# некорректны как торговый сигнал → в динамическую вселенную не пускаем (были бы monета-пустышка:
# слот занят, 4h-входа у движка на ней никогда не будет).
_SIGNAL_TF = "4h"
_STACK_MAX_CAP = 100   # потолок предохранителя (зеркало ядра le=100; env-путь мимо валидации)
_EMPTY_SETUP = {"stage": None, "score": None, "tf": None}   # пришпилен без сетапа печки


def _score_key(v):
    """Ключ сортировки по скору (None — в хвост)."""
    s = v.get("score")
    return (s is not None, s or 0)


class DynamicUniverse:
    """Мост печка→рабочие монеты бота. Гейт — у вызывающего (dynamic_enabled + scout_reader)."""

    def __init__(self, cfg, scout_reader) -> None:
        self._scout = scout_reader
        # F-lookahead v3: источник вселенной. "engine" → отбор по warm.classify из scout_list;
        # иначе "scout" (дефолт, байт-в-байт прежний путь). getattr — старые cfg без поля = scout.
        self._source = str(getattr(cfg, "dynamic_source", "scout") or "scout").lower()
        self._coins_path = cfg.dynamic_coins_path
        # Критерии канала (ADR-0020 D1): читаются ЖИВЬЁМ из файла каждый скан; cfg = ген-дефолт
        # (файла нет / re-fetch не доехал). Живой кап → view() честен при сжатии (EDIT 2).
        self._criteria_path = cfg.dynamic_criteria_path
        self._cfg_n = max(1, int(cfg.dynamic_stack_max))
        self._cfg_min_score = int(cfg.dynamic_min_score)
        self._cfg_fresh_bars = int(cfg.dynamic_fresh_bars)
        self._n = self._cfg_n
        self._min_score = self._cfg_min_score
        self._fresh_bars = self._cfg_fresh_bars
        self._enter = max(1, int(cfg.dynamic_enter_scans))   # гистерезис (геном, не канал)
        self._exit = max(1, int(cfg.dynamic_exit_scans))     # гистерезис (геном, не канал)
        self._min_write_s = float(cfg.dynamic_min_write_s)
        self._stack: dict[str, dict] = {}       # {symbol: {stage,score,tf,missed}}
        self._held: frozenset[str] = frozenset()   # символы с живой позицией/ордером (пин, Веха 2)
        self._pending: dict[str, int] = {}      # кандидат → сканов подряд виден (гистерезис входа)
        self._last_scan_ms = 0
        self._written: frozenset[str] = frozenset()
        self._last_write_mono = float("-inf")

    def _load_criteria(self) -> None:
        """ADR-0020 D1: критерии из файла (re-fetch пишет), fallback = ген-дефолты cfg. Читаются на
        КАЖДОМ скане → правка в консоли доезжает до Борса без рестарта. `stack_max` → живой кап
        (EDIT 2: сжатие 10→5 не выгоняет — естественное убытие; view() честен: 7·кап5)."""
        c = read_criteria(self._criteria_path) if self._criteria_path else {}
        # предохранитель держим и на env-пути (config.py без потолка) → кламп ЗДЕСЬ (страж в коде)
        self._n = max(1, min(_STACK_MAX_CAP, int(c.get("stack_max", self._cfg_n))))
        self._min_score = int(c.get("min_score", self._cfg_min_score))
        self._fresh_bars = int(c.get("fresh_bars", self._cfg_fresh_bars))

    def tick(self, now_mono: float, held: frozenset[str] = frozenset()) -> None:
        """Один заход. held = символы с живой позицией/ордером (пин Вехи 2, ADR-0019 «б»).

        Флаг-файл позиций пишем КАЖДЫЙ тик (позиции меняются между сканами) — супервизор start.sh
        читает его перед мягким рестартом движка (F-restart «а»). Рекомпьют/запись набора — только
        на НОВЫЙ скан (анти-thrash). Сбой печки → набор не трогаем, но флаг уже свежий."""
        self._held = frozenset(s.strip().upper() for s in held if s)   # нормализация == ключи стека
        self._write_positions_flag()            # F-restart «а»: адаптер пишет флаг открытых позиций
        try:
            # F-lookahead v3: engine-источник гоняет warm.classify по ~155 монетам — ДОРОГО. Гейтим
            # ДЕШЁВЫМ курсором ДО скана → 155-classify только на НОВЫЙ скан. Scout-путь (findings
            # дёшев) — как был, байт-в-байт.
            if self._source == "engine":
                scan_ms = self._scout.last_scan_ms()
                if scan_ms == 0 or scan_ms == self._last_scan_ms:
                    return                      # скан не новый → дорогой placeable-скан НЕ гоняем
                _, cand = self._scout.placeable_scan()
            else:
                scan_ms, cand = self._scout.findings_for_universe()
                if scan_ms == 0 or scan_ms == self._last_scan_ms:
                    return                      # скаут не готов / скан не новый → тишина
        except Exception:  # noqa: BLE001 — печка недоступна → не роняем цикл, набор держим
            log.exception("dynamic: чтение источника (%s) упало — пропуск", self._source)
            return
        self._last_scan_ms = scan_ms
        if self._source == "engine":
            self._recompute_engine(cand)        # F-lookahead v3: отбор по warm.classify (placeable)
        else:
            self._recompute(cand)               # прежний путь: по скаут-стадии/скору
        self._maybe_write(now_mono)

    def _apply_fresh(self, fresh: dict, cand_key) -> None:
        """ПРЕДОХРАНИТЕЛИ Вехи 2 (пин held / exit-гистерезис / вход enter+кап / пол-на-пустоту через
        _maybe_write) — ЕДИНЫ для обоих источников, НЕ переписаны (условие Куратора): извлечены
        из прежнего _recompute без смены поведения (регресс-гвоздь DYNAMIC_SOURCE=scout доказывает).
        fresh — {symbol:{stage,score,tf,…}} кандидатов ЭТОГО скана; cand_key — ключ сортировки входа
        (источник задаёт: скаут по скору, движок auto-первыми)."""
        for sym in list(self._stack):           # обновление/выход существующих
            if sym in fresh:
                self._stack[sym].update(fresh[sym])
                self._stack[sym]["missed"] = 0
            elif sym in self._held:             # ПИН (ADR-0019 «б»): позиция/ордер жив → держим
                self._stack[sym]["missed"] = 0   # слот занят (сетап ушёл)
            else:
                self._stack[sym]["missed"] += 1
                if self._stack[sym]["missed"] >= self._exit:
                    del self._stack[sym]        # слот свободен (сетап ушёл/протух)
        for sym in self._held:                  # ПИН: held без слота печки → до-шпилить,
            if sym not in self._stack:          # чтобы нести в coins.json и карточке
                base = fresh.get(sym) or _EMPTY_SETUP
                self._stack[sym] = {**base, "missed": 0}
        cands = sorted((s for s in fresh if s not in self._stack), key=cand_key, reverse=True)
        for sym in cands:                       # вход: гистерезис enter_scans + кап N
            self._pending[sym] = self._pending.get(sym, 0) + 1
            if self._pending[sym] >= self._enter and len(self._stack) < self._n:
                self._stack[sym] = {**fresh[sym], "missed": 0}
                self._pending.pop(sym, None)
        self._pending = {s: c for s, c in self._pending.items()
                         if s in fresh and s not in self._stack}

    def _recompute(self, findings: list[dict]) -> None:
        self._load_criteria()                   # ADR-0020 D1: критерии ЖИВЬЁМ (кап/скор/свежесть)
        fresh = {}
        for f in findings:
            if (f.get("tf") or "4h") != _SIGNAL_TF:
                continue                        # движок торгует ТОЛЬКО 4h — иной ТФ не кандидат
            if str(f.get("state") or "") not in _ACTIVE_STAGES:
                continue                        # неактивная/незрелая стадия — не кандидат
            score = f.get("score")
            if self._min_score > 0 and (score is None or score < self._min_score):
                continue                        # доп-порог скора ПОВЕРХ дозорного (0 = выкл)
            if self._fresh_bars > 0:            # свежесть: слишком старый сетап — мимо (0 = выкл)
                bsa = f.get("bars_since_anchor")
                # bsa=None → якоря нет (forming) → свежесть не определена → пропускаем (не режем)
                if bsa is not None and bsa > self._fresh_bars:
                    continue
            sym = str(f.get("symbol") or "").strip().upper()   # нормализация регистра
            if sym:
                fresh[sym] = {"stage": f["state"], "score": score,
                              "tf": f.get("tf") or "4h"}
        self._apply_fresh(fresh, lambda s: _score_key(fresh[s]))

    def _recompute_engine(self, placeable: dict) -> None:
        """F-lookahead v3: кандидаты = движко-PLACEABLE (`warm.classify` PENDING) из пула качества
        scout_list — НЕ скаут-стадия/скор. auto_eligible ПЕРВЫМИ (самоход поставит сам), reanchored
        после (кнопка «Поставить»). Сито качества УЖЕ применено при сборе scout_list (Этап A) — не
        дублируем; `min_score` канала → доп-порог к скору КАЧЕСТВА монеты (семантика в README).
        fresh_bars в engine-режиме НЕ применяем — движок сам режет окном TIMEOUT_BARS=72 (placeable
        уже в нём). Предохранители — общий `_apply_fresh`."""
        self._load_criteria()                   # ADR-0020 D1: живой кап/мин-скор качества
        fresh = {}
        for sym, p in placeable.items():
            score = p.get("score")
            if self._min_score > 0 and (score is None or score < self._min_score):
                continue                        # доп-порог качества поверх сита scout_list (0=выкл)
            fresh[sym] = {"stage": "ready" if p.get("auto_eligible") else "tracking",
                          "score": score, "tf": _SIGNAL_TF, "auto": bool(p.get("auto_eligible"))}
        # вход: auto-годные ПЕРВЫМИ (самоход возьмёт без кнопки), затем по скору качества
        self._apply_fresh(
            fresh,
            lambda s: (fresh[s]["auto"], fresh[s]["score"] is not None, fresh[s]["score"] or 0))

    def _maybe_write(self, now_mono: float) -> None:
        symbols = frozenset(self._stack) | self._held   # ПИН: held ВСЕГДА в наборе (даже вне стека)
        if not symbols:
            return                              # ПОЛ НА ПУСТОТУ: стек и held пусты → не пишем
        if symbols == self._written:
            return                              # набор не менялся
        if now_mono - self._last_write_mono < self._min_write_s:
            return                              # min-интервал записи (анти-thrash)
        if not self._coins_path:
            log.warning("dynamic: COINS_CONFIG_PATH не задан — вселенную не пишу")
            return
        self._write_atomic({s: dict(_DEFAULT_COIN) for s in symbols})
        self._written = symbols
        self._last_write_mono = now_mono

    def _write_atomic(self, coins: dict) -> None:
        """coins.json атомарно (tmp+os.replace: разъём читает целый файл) + gen для супервизора."""
        path = self._coins_path
        d = os.path.dirname(path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".coins.", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(coins, fh, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        # .gen тоже атомарно (tmp+os.replace): иначе рваное чтение cat'ом → спурьёзный рестарт
        gen_tmp = path + ".gen.tmp"
        with open(gen_tmp, "w", encoding="utf-8") as fh:
            fh.write(str(self._last_scan_ms))   # супервизор сверяет gen → рестарт ТОЛЬКО движка
        os.replace(gen_tmp, path + ".gen")
        log.info("dynamic: вселенная (%d монет): %s", len(coins), ",".join(sorted(coins)))

    def _write_positions_flag(self) -> None:
        """F-restart «а» (ADR-0019): адаптер пишет флаг открытых позиций/ордеров рядом с coins.json;
        супервизор start.sh проверяет `[ -s ]` ПЕРЕД мягким рестартом движка. Непусто = есть held
        (рестарт отложить — не бросать позицию мид-ордер). Пусто (0 байт) = слотов нет (рестарт ок).
        Атомарно (tmp+os.replace): супервизор не прочтёт рваную строку."""
        if not self._coins_path:
            return
        path = self._coins_path + ".positions"
        payload = " ".join(sorted(self._held))   # непусто = есть позиции/ордера; "" = 0 байт
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, path)
        except OSError:
            log.exception("dynamic: не смог записать флаг позиций %s", path)

    def view(self) -> dict:
        """Снимок стека для engine_state.stack (карточка Борса): cap/count/items (+pinned)."""
        items = sorted(
            ({"symbol": s, "stage": v.get("stage"), "score": v.get("score"), "tf": v.get("tf"),
              "pinned": s in self._held}         # пришпилена под живую позицию/ордер (ADR-0019 «б»)
             for s, v in self._stack.items()),
            key=lambda i: (i["score"] is not None, i["score"] or 0), reverse=True,
        )
        return {"cap": self._n, "count": len(items), "items": items}

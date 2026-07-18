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
_ACTIVE_STAGES = ("forming", "tracking", "ready")   # committed — производная UI, не стадия печки


def _score_key(v):
    """Ключ сортировки по скору (None — в хвост)."""
    s = v.get("score")
    return (s is not None, s or 0)


class DynamicUniverse:
    """Мост печка→рабочие монеты бота. Гейт — у вызывающего (dynamic_enabled + scout_reader)."""

    def __init__(self, cfg, scout_reader) -> None:
        self._scout = scout_reader
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
        self._pending: dict[str, int] = {}      # кандидат → сканов подряд виден (гистерезис входа)
        self._last_scan_ms = 0
        self._written: frozenset[str] = frozenset()
        self._last_write_mono = float("-inf")

    def _load_criteria(self) -> None:
        """ADR-0020 D1: критерии из файла (re-fetch пишет), fallback = ген-дефолты cfg. Читаются на
        КАЖДОМ скане → правка в консоли доезжает до Борса без рестарта. `stack_max` → живой кап
        (EDIT 2: сжатие 10→5 не выгоняет — естественное убытие; view() честен: 7·кап5)."""
        c = read_criteria(self._criteria_path) if self._criteria_path else {}
        self._n = max(1, int(c.get("stack_max", self._cfg_n)))
        self._min_score = int(c.get("min_score", self._cfg_min_score))
        self._fresh_bars = int(c.get("fresh_bars", self._cfg_fresh_bars))

    def tick(self, now_mono: float) -> None:
        """Один заход. No-op без нового скана (анти-thrash). Сбой печки → стек/файл не трогаем."""
        try:
            scan_ms, findings = self._scout.findings_for_universe()
        except Exception:  # noqa: BLE001 — печка недоступна → не роняем цикл, набор держим
            log.exception("dynamic: чтение печки упало — пропуск")
            return
        if scan_ms == 0 or scan_ms == self._last_scan_ms:
            return                              # скаут не готов / скан не новый → тишина
        self._last_scan_ms = scan_ms
        self._recompute(findings)
        self._maybe_write(now_mono)

    def _recompute(self, findings: list[dict]) -> None:
        self._load_criteria()                   # ADR-0020 D1: критерии ЖИВЬЁМ (кап/скор/свежесть)
        fresh = {}
        for f in findings:
            if str(f.get("state") or "") not in _ACTIVE_STAGES:
                continue                        # неактивная стадия — не кандидат
            score = f.get("score")
            if self._min_score > 0 and (score is None or score < self._min_score):
                continue                        # доп-порог скора ПОВЕРХ дозорного (0 = выкл)
            if self._fresh_bars > 0:            # свежесть: слишком старый сетап — мимо (0 = выкл)
                bsa = f.get("bars_since_anchor")
                if bsa is None or bsa > self._fresh_bars:
                    continue
            sym = str(f.get("symbol") or "").strip().upper()   # нормализация регистра
            if sym:
                fresh[sym] = {"stage": f["state"], "score": score,
                              "tf": f.get("tf") or "4h"}
        for sym in list(self._stack):           # обновление/выход существующих
            if sym in fresh:
                self._stack[sym].update(fresh[sym])
                self._stack[sym]["missed"] = 0
            else:
                self._stack[sym]["missed"] += 1
                if self._stack[sym]["missed"] >= self._exit:
                    del self._stack[sym]        # слот свободен (сетап ушёл/протух)
        cands = sorted((s for s in fresh if s not in self._stack),
                       key=lambda s: _score_key(fresh[s]), reverse=True)
        for sym in cands:                       # вход: гистерезис enter_scans + кап N, по скору
            self._pending[sym] = self._pending.get(sym, 0) + 1
            if self._pending[sym] >= self._enter and len(self._stack) < self._n:
                self._stack[sym] = {**fresh[sym], "missed": 0}
                self._pending.pop(sym, None)
        self._pending = {s: c for s, c in self._pending.items()
                         if s in fresh and s not in self._stack}

    def _maybe_write(self, now_mono: float) -> None:
        symbols = frozenset(self._stack)
        if not symbols:
            return                              # ПОЛ НА ПУСТОТУ: не пишем, gen не бампаем
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
        with open(path + ".gen", "w", encoding="utf-8") as fh:
            fh.write(str(self._last_scan_ms))   # супервизор сверяет gen → рестарт ТОЛЬКО движка
        log.info("dynamic: вселенная (%d монет): %s", len(coins), ",".join(sorted(coins)))

    def view(self) -> dict:
        """Снимок стека для engine_state.stack (карточка Борса): cap/count/items."""
        items = sorted(
            ({"symbol": s, "stage": v.get("stage"), "score": v.get("score"), "tf": v.get("tf")}
             for s, v in self._stack.items()),
            key=lambda i: (i["score"] is not None, i["score"] or 0), reverse=True,
        )
        return {"cap": self._n, "count": len(items), "items": items}

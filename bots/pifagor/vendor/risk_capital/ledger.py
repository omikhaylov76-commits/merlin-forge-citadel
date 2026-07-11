# -*- coding: utf-8 -*-
"""risk_capital.ledger — учётный леджер working/cushion (Веха 4 фича 1, ADR 0010).

`working` — БАЗА сайзинга (компаундится реализованным PnL, паритет с port_lib.compound: размер =
доля working). `cushion` — подушка (трогается только рефинансом, под-шаг 3). `ratio` =
cushion/(working+cushion). Леджер чистый от config/времени: стартовые значения инъектятся в seed(),
персистентность — через CapitalStore (инъекция). Контракт get() — docs/06.

peak_equity и защёлки kill-switch живут в той же строке capital_state, но их ведут refinance/
killswitch (под-шаги 3–4); здесь — только working/cushion/ratio + apply_pnl.
"""
import json


def compute_ratio(working, cushion):
    """Доля подушки cushion/(working+cushion) (0.0 при total<=0). Единый источник для ledger/refinance."""
    total = working + cushion
    return (cushion / total) if total > 0 else 0.0


class Ledger:
    """Леджер капитала поверх CapitalStore (одна строка id=1). seed/get/apply_pnl."""

    def __init__(self, store):
        self.store = store

    def seed(self, working_start, cushion_start):
        """Инициализировать леджер, если строки ещё нет (идемпотентно: повторный seed НЕ затирает
        живой капитал). peak_equity = стартовый total (HWM); защёлки сняты; last_refinance_* —
        baseline для рефинанса (ts=None: первый месяц установит refinance, под-шаг 3). Возвращает get()."""
        if self.store.get() is None:
            working_start, cushion_start = float(working_start), float(cushion_start)
            total = working_start + cushion_start
            self.store.put({
                "working": working_start,
                "cushion": cushion_start,
                "ratio": compute_ratio(working_start, cushion_start),
                "peak_equity": total,
                "killswitch_active": 0,
                "alarm_active": 0,
                "last_refinance_ts": None,
                "last_refinance_total": total,
            })
        return self.get()

    def get(self):
        """Публичный контракт (docs/06): {working, cushion, ratio}, либо None если не засеян."""
        row = self.store.get()
        if row is None:
            return None
        return {"working": row["working"], "cushion": row["cushion"], "ratio": row["ratio"]}

    def apply_pnl(self, realized):
        """Реализованный PnL закрытой ноги -> working (компаундинг). Guard: working не уходит ниже 0
        (база сайзинга неотрицательна; working==0 -> провайдер/сайзинг не ставит ног — kill-switch
        по total сработал бы раньше). Пересчитывает ratio, персист атомарно (read-modify-write под
        локом). Возвращает get() (None, если леджер не засеян — mutate вернёт False, состояние не тронуто)."""
        def _apply(row):
            row["working"] = max(0.0, row["working"] + realized)
            row["ratio"] = compute_ratio(row["working"], row["cushion"])
            return True
        self.store.mutate(_apply)
        return self.get()

    # ── delta-курсор компаунд (под-шаг 5a) ──────────────────────────────────────
    def ensure_cursor_seeded(self, now_ms):
        """Штамп delta-курсора компаунда (`last_closed_ms`) = now_ms ТОЛЬКО если ещё NULL (идемпотентно:
        живой продвигающийся курсор НЕ затираем). Закрывает «проглот истории»: на засеянной ДО 5a строке
        после ALTER колонка = NULL, и без штампа первый компаунд ушёл бы в now-7d. Время — ПАРАМЕТРОМ
        (леджер чист от времени). Вызывать в boot для обеих строк — свежей и существующей-после-ALTER."""
        def _seed(row):
            if row.get("last_closed_ms") is None:
                row["last_closed_ms"] = int(now_ms)
                row["last_closed_ids"] = "[]"
                return True
            return False
        self.store.mutate(_seed)

    def apply_pnl_with_cursor(self, realized, new_ms, new_ids):
        """Компаунд реализованного PnL В working + сдвиг delta-курсора (`last_closed_ms`/`last_closed_ids`)
        АТОМАРНО в ОДНОМ mutate — рестарт между bump'ом working и сдвигом курсора невозможен → нет двойного
        счёта. working≥0 (floor); при floor-to-0 ставит флаг наружу → caller WARN'ит (working=0 = независимое
        halt-условие: сайзинг 0 ног до пополнения). new_ids — множество orderId на равном new_ms (identity-set
        дедупа). Возвращает (get(), floored:bool)."""
        box = {"floored": False}

        def _apply(row):
            nw = row["working"] + realized
            if nw < 0.0:
                box["floored"] = True
            row["working"] = max(0.0, nw)
            row["ratio"] = compute_ratio(row["working"], row["cushion"])
            row["last_closed_ms"] = int(new_ms)
            row["last_closed_ids"] = json.dumps(sorted(str(i) for i in new_ids))
            return True
        self.store.mutate(_apply)
        return self.get(), box["floored"]

    def mark_idle_gap_alerted(self, cursor_ms):
        """Латч тревоги «долгий простой >7д» (под-шаг 5.7 п.5). Compare-and-set: штампует `idle_gap_ms` =
        позицию курсора (`last_closed_ms`), на которой тревожили, и возвращает True ТОЛЬКО если это свежий
        эпизод (латч ещё не стоял на этом курсоре). Пока курсор не двигается (сделок нет) — повторный зов
        вернёт False → одна тревога на эпизод; пришла сделка → курсор сдвинулся → следующий простой (другой
        курсор) снова вооружает. Персист в capital_state → переживает рестарт (нет шторма тревог на флаппинге)."""
        box = {"fresh": False}

        def _mark(row):
            if row.get("idle_gap_ms") == int(cursor_ms):
                return False
            row["idle_gap_ms"] = int(cursor_ms)
            box["fresh"] = True
            return True
        self.store.mutate(_mark)
        return box["fresh"]

# -*- coding: utf-8 -*-
"""state.store — снимок карточек сетапов поверх storage.db (переживает рестарт; ADR 0008).

StateStore сериализует/восстанавливает карточку execution.actions ЦЕЛИКОМ (JSON-блоб на символ).
Ключевое: JSON приводит float-ключи ног (0.382/0.5/0.618) к строкам — при restore возвращаем float
(иначе legs[lv] / lv in legs ломаются: lifecycle.py, actions.py). Латчи migrated/closed и
target/resting_stop переживают рестарт (Python json round-trip float — точный). mark_filled —
атомарная пометка ноги залитой по link_id (гонка WS-залив vs тик), через db.state_mutate под локом.
"""
def _restore_legs(setup):
    """JSON-ключи ног (строки) -> float (иначе legs[lv] по float-ключу не находит)."""
    legs = setup.get("legs")
    if isinstance(legs, dict):
        setup["legs"] = {float(k): v for k, v in legs.items()}
    return setup


class StateStore:
    """Снимок сетапов поверх storage.db.DB. get/put/clear/all/has_active + атомарный mark_filled."""

    def __init__(self, db):
        self.db = db

    def get(self, symbol):
        setup = self.db.state_get(symbol)
        return _restore_legs(setup) if setup is not None else None

    def put(self, symbol, setup):
        self.db.state_put(symbol, setup)            # db json.dumps; float-ключи -> строки (restore вернёт)

    def clear(self, symbol):
        self.db.state_clear(symbol)

    def all(self):
        return {s: _restore_legs(c) for s, c in self.db.state_all().items()}

    def has_active(self, symbol):
        return self.db.state_get(symbol) is not None

    def mark_filled(self, symbol, link_id=None, ebar=None, *, kind="entry", lv=None, price=None,
                    runner_tp_hold=False, leg2_ext=None, cond05=None, tol05=0.0, trail_r=0.0):
        """Атомарно (под локом БД) обработать залив/выход ноги ЧЕРЕЗ lifecycle.on_fill — ЕДИНЫЙ источник
        перехода (entry: state=OPEN/filled + istop/resting_stop=stop0 + commit-латч; exit: state=CLOSED +
        profit_taken-латч + completion), чтобы WS-путь (под-шаг 6) и тиковый poll-diff (под-шаг 4) давали
        ОДНО состояние (без расхождения parity). Возвращает Action (что executor должен сделать), либо None.

        kind="entry" (дефолт, обратносовместимо): резолв ноги по link_id (PENDING, ещё не filled).
        kind="exit": резолв по lv (нога OPEN); price ОБЯЗАТЕЛЕН (знак profit_taken-латча, цена с уровня
        карточки — Q2). РЕЗОЛВ И ПРОВЕРКА ФАЗЫ — ВНУТРИ мутатора под локом: повторное наблюдение того же
        выхода (линк исчез навсегда) НЕ пере-закрывает ногу (идемпотентность). Гонка WS↔тик закрыта локом."""
        from execution import lifecycle as LC   # локальный импорт: state -> lifecycle (без цикла)
        from execution.actions import OPEN
        box = {}

        def _mut(setup):
            _restore_legs(setup)                # float-ключи: on_fill сверяет lv с LV/COMMIT_LV (float)
            if kind == "exit":
                leg = setup["legs"].get(lv)
                if leg is None or leg.get("state") != OPEN:   # резолв+фаза ПОД локом → идемпотентность
                    return False
                box["action"] = LC.on_fill(symbol, setup,
                                           {"kind": "exit", "lv": lv, "price": price, "link_id": link_id},
                                           runner_tp_hold=runner_tp_hold, leg2_ext=leg2_ext,
                                           cond05=cond05, tol05=tol05, trail_r=trail_r)
                return True
            # entry (дефолт): резолв по link_id среди ещё не залитых
            elv = next((l for l, leg in setup["legs"].items()
                        if leg.get("link_id") == link_id and not leg.get("filled")), None)
            if elv is None:
                return False
            box["action"] = LC.on_fill(symbol, setup,
                                       {"kind": "entry", "lv": elv, "ebar": ebar, "link_id": link_id},
                                       runner_tp_hold=runner_tp_hold, leg2_ext=leg2_ext,
                                       cond05=cond05, tol05=tol05, trail_r=trail_r)
            return True

        changed = self.db.state_mutate(symbol, _mut)
        return box.get("action") if changed else None

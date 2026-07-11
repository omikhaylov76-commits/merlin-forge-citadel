# -*- coding: utf-8 -*-
"""state.capital — снимок леджера капитала поверх storage.db (одна строка id=1; ADR 0010).

Тонкая обёртка над db.capital_get/put/mutate (как StateStore для сетапов): только персистентность.
Бизнес-логику (working/cushion/ratio, apply_pnl, peak/защёлки, рефинанс) ведут risk_capital.ledger/
refinance/killswitch — они получают этот стор инъекцией (модули risk_capital чистые от storage)."""


class CapitalStore:
    """Снимок леджера поверх storage.db.DB: get()->dict|None, put(row), mutate(mutator)->bool."""

    def __init__(self, db):
        self.db = db

    def get(self):
        return self.db.capital_get()

    def put(self, row):
        self.db.capital_put(row)

    def mutate(self, mutator):
        return self.db.capital_mutate(mutator)

    # ── курсор исполненного «Закрыть всё» (durable-намерение, 5.3b): id последней СВЕРШЁННОЙ CLOSE_ALL.
    # Воркер сверяет config_log_latest("CLOSE_ALL").id > ack ⇒ намерение новое (энфорсмент — 5.3c).
    def get_close_all_ack(self):
        """id последней исполненной CLOSE_ALL или None (леджер не засеян / курсор NULL)."""
        row = self.get()
        return row.get("close_all_ack_id") if row else None

    def set_close_all_ack(self, ack_id):
        """Атомарно сдвинуть ack-курсор на ack_id. True если строка есть (леджер засеян)."""
        return self.mutate(lambda row: (row.__setitem__("close_all_ack_id", ack_id), True)[1])

    # ── курсор исполненного «Прогреть выбранные» (durable-намерение WARM_APPLY, 5.8 п.4): id последней
    # СВЕРШЁННОЙ WARM_APPLY. Воркер сверяет config_log_latest("WARM_APPLY").id > ack ⇒ намерение новое (грев — 4b).
    def get_warm_ack(self):
        """id последней исполненной WARM_APPLY или None (леджер не засеян / курсор NULL)."""
        row = self.get()
        return row.get("warm_ack_id") if row else None

    def set_warm_ack(self, ack_id):
        """Атомарно сдвинуть warm-ack-курсор на ack_id. True если строка есть (леджер засеян)."""
        return self.mutate(lambda row: (row.__setitem__("warm_ack_id", ack_id), True)[1])

    # ── метка-якорь backfill таймаута-72 (5.7 п.6): последняя 4h-граница (мс), за которую воркер был ЖИВ
    # и оттикал. На старте `missed = (текущая − seen)/4h` догоняет `wait_postcommit` за простой. Штамп ВЕДЁТ
    # счётчик (в начале _poll_tick) → краш даёт недосчёт (поздний таймаут — безопасно), не пере-счёт.
    def get_last_4h_seen(self):
        """Последняя виденная 4h-граница (мс) или None (леджер не засеян / метка NULL = первый запуск/сброс БД)."""
        row = self.get()
        return row.get("last_4h_seen_ms") if row else None

    def set_last_4h_seen(self, boundary_ms):
        """Атомарно записать метку-границу. True если строка есть (леджер засеян)."""
        return self.mutate(lambda row: (row.__setitem__("last_4h_seen_ms", int(boundary_ms)), True)[1])

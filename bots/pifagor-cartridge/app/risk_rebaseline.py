"""Разовая ре-база kill-switch движка после ручной смены баланса (#Персиваль-ks).

Проблема: durable HWM (peak_equity) растёт только вверх и переживает рестарт. Ручная смена
биржевого баланса ВНИЗ ($20K при прежнем пике ~$100K) → equity читается как ~80% просадка от
пика ≥ KILLSWITCH_DD → kill-switch защёлкивается, хотя реальной ТОРГОВОЙ просадки нет (0 сделок).
Штатная кнопка сброса чистит только флаг — на след. тике evaluate снова видит просадку vs старый
пик и защёлкивает обратно. Нужен разовый сброс защёлки + РЕ-БАЗА пика на новый баланс.

Гейт: env MF_RISK_REBASELINE_ONCE=1 (Персиваль-only; убрать после). Правит capital_state ДО старта
движка (иначе singleton-lock движка занимает БД). ВСЁ логируется (аудит). Прочие боты — no-op.
Vendor не трогаем — чистый stdlib sqlite3 по известной схеме capital_state (storage/db.py).
"""

from __future__ import annotations

import logging
import os
import sqlite3

log = logging.getLogger("mfc.risk-rebaseline")

_SEL = ("SELECT peak_equity, killswitch_active, alarm_active, stop_streak, working "
        "FROM capital_state WHERE id=1")
_UPD = ("UPDATE capital_state SET killswitch_active=0, alarm_active=0, stop_streak=0, "
        "peak_equity=? WHERE id=1")


def rebaseline(db_path: str, new_peak: float) -> bool:
    """Сброс защёлки kill-switch + ре-база peak_equity в capital_state(id=1). True, если применено.
    Логирует состояние ДО и ПОСЛЕ (диагностика реальных цифр + аудит)."""
    con = sqlite3.connect(db_path, timeout=5.0)
    try:
        row = con.execute(_SEL).fetchone()
        if row is None:
            log.warning("risk-rebaseline: capital_state(id=1) пуст — свежая БД, нечего сбрасывать")
            return False
        log.warning("risk-rebaseline ДО: peak=%s killswitch=%s alarm=%s streak=%s working=%s",
                    row[0], row[1], row[2], row[3], row[4])
        con.execute(_UPD, (float(new_peak),))
        con.commit()
        a = con.execute(_SEL).fetchone()
        log.warning("risk-rebaseline ПОСЛЕ: peak=%s killswitch=%s alarm=%s streak=%s "
                    "(защёлка снята, HWM ре-базирован)", a[0], a[1], a[2], a[3])
        return True
    finally:
        con.close()


def main() -> None:
    home = os.environ.get("PIFAGOR_HOME", "/pifagor")
    db_path = os.environ.get("DB_PATH") or os.path.join(home, "pifagor.db")
    new_peak = float(os.environ.get("MF_RISK_REBASELINE_TO", "20000"))
    log.warning("risk-rebaseline: старт (db=%s → peak=%s)", db_path, new_peak)
    if not os.path.exists(db_path):
        log.warning("risk-rebaseline: БД %s не найдена — пропуск (свежая БД)", db_path)
        return
    try:
        rebaseline(db_path, new_peak)
    except sqlite3.Error as e:
        log.warning("risk-rebaseline: sqlite-ошибка (старт НЕ валю): %s", e)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    main()

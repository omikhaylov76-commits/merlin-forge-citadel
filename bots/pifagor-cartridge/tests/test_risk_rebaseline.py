"""Тест ре-базы риск-состояния (#Персиваль-ks): защёлкнутый kill-switch → сброс + ре-база пика."""

import sqlite3

from app.risk_rebaseline import rebaseline

_SCHEMA = (
    "CREATE TABLE capital_state(id INTEGER PRIMARY KEY, working REAL, cushion REAL, ratio REAL, "
    "peak_equity REAL, killswitch_active INTEGER, alarm_active INTEGER, stop_streak INTEGER, "
    "updated_ts TEXT)"
)


def _db(tmp_path, **row):
    p = str(tmp_path / "pifagor.db")
    con = sqlite3.connect(p)
    con.execute(_SCHEMA)
    cols = ",".join(row)
    ph = ",".join("?" * len(row))
    con.execute(f"INSERT INTO capital_state(id,{cols}) VALUES (1,{ph})", tuple(row.values()))
    con.commit()
    con.close()
    return p


def test_rebaseline_снимает_защёлку_и_ребазит_пик(tmp_path):
    # защёлкнуто: старый высокий пик $100K, killswitch=1, streak=2 (смена баланса на $20K)
    p = _db(tmp_path, working=10000, peak_equity=100000, killswitch_active=1,
            alarm_active=1, stop_streak=2)
    assert rebaseline(p, 20000) is True
    con = sqlite3.connect(p)
    peak, ks, al, streak = con.execute(
        "SELECT peak_equity, killswitch_active, alarm_active, stop_streak "
        "FROM capital_state WHERE id=1").fetchone()
    con.close()
    assert ks == 0 and al == 0 and streak == 0     # защёлка/тревога/серия сброшены
    assert peak == 20000                            # HWM ре-базирован на новый баланс


def test_rebaseline_пустая_бд_ноуп(tmp_path):
    p = str(tmp_path / "pifagor.db")
    con = sqlite3.connect(p)
    con.execute(_SCHEMA)  # таблица есть, строки id=1 нет
    con.commit()
    con.close()
    assert rebaseline(p, 20000) is False            # нечего сбрасывать — не падаем

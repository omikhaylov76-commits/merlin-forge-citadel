"""Тесты решателя здоровья скаута (ADR-0016 в.4, #51): чистые функции вердикта + чтение heartbeat.

Гейт SCOUT_ENABLED и рестарт-петля — в start.sh (shell), доказаны локальным прогоном (а)-(г).
Здесь — тестируемая часть (4д «тесты на гейт/парсинг»): порог RSS, залипание heartbeat, grace-окно.
"""

import sqlite3

from app import scout_health as sh

_MIN = 60_000  # 1 мин в мс


def _mk_scout_db(path, heartbeat_ms=None):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE scout_control(id INTEGER PRIMARY KEY, heartbeat_ms BIGINT)")
    if heartbeat_ms is not None:
        con.execute("INSERT INTO scout_control(id, heartbeat_ms) VALUES (1, ?)", (heartbeat_ms,))
    con.commit()
    con.close()


def test_read_heartbeat_ms_present(tmp_path):
    db = tmp_path / "scout.db"
    _mk_scout_db(db, heartbeat_ms=1234567890)
    assert sh.read_heartbeat_ms(str(db)) == 1234567890


def test_read_heartbeat_ms_missing_row(tmp_path):
    db = tmp_path / "scout.db"
    _mk_scout_db(db, heartbeat_ms=None)  # таблица есть, строки нет
    assert sh.read_heartbeat_ms(str(db)) is None


def test_read_heartbeat_ms_no_db(tmp_path):
    # БД/таблицы нет (скаут ещё не инициализировал) → None, не исключение
    assert sh.read_heartbeat_ms(str(tmp_path / "nope.db")) is None


def test_rss_over_cap():
    assert sh.rss_over_cap(400 * 1024, 300) is True       # 400МБ > 300МБ
    assert sh.rss_over_cap(200 * 1024, 300) is False
    assert sh.rss_over_cap(999_999, 0) is False            # кап 0 = выключен


def test_heartbeat_stale():
    now = 1_000_000_000_000
    assert sh.heartbeat_stale(now - 10 * _MIN, now, 3 * _MIN) is True   # молчит 10 мин > 3
    assert sh.heartbeat_stale(now - 1 * _MIN, now, 3 * _MIN) is False   # свежий
    assert sh.heartbeat_stale(None, now, 3 * _MIN) is True              # нет строки = залип


def _verdict(**kw):
    base = dict(rss_kb=1000, cap_mb=300, heartbeat_ms=1_000_000_000_000,
                now_ms=1_000_000_000_000, max_silence_ms=3 * _MIN,
                elapsed_ms=10 * _MIN, grace_ms=3 * _MIN)
    base.update(kw)
    return sh.verdict(**base)


def test_verdict_ok():
    assert _verdict() == "ok"


def test_verdict_rss_beats_everything_even_in_grace():
    # RSS-кап — жёсткая защита от OOM, действует ДАЖE в grace-окне
    assert _verdict(rss_kb=400 * 1024, elapsed_ms=0) == "restart:rss"


def test_verdict_stale_after_grace():
    assert _verdict(heartbeat_ms=1_000_000_000_000 - 10 * _MIN) == "restart:stale"


def test_verdict_grace_suppresses_stale():
    # тот же залипший heartbeat, но скаут ещё в стартовом окне (bootstrap Этапа A) → не рестартим
    assert _verdict(heartbeat_ms=1_000_000_000_000 - 10 * _MIN, elapsed_ms=1 * _MIN) == "ok"


def test_boundary_equality_not_over_threshold():
    # строгие сравнения: ровно на пороге — ещё НЕ превышение (off-by-one зона)
    assert sh.rss_over_cap(300 * 1024, 300) is False                 # ровно кап
    now = 1_000_000_000_000
    assert sh.heartbeat_stale(now - 3 * _MIN, now, 3 * _MIN) is False  # ровно max_silence


def test_verdict_grace_boundary_lets_stale_through():
    # elapsed == grace → grace УЖЕ не действует (строгое <) → залипший heartbeat даёт рестарт
    assert _verdict(heartbeat_ms=1_000_000_000_000 - 10 * _MIN,
                    elapsed_ms=3 * _MIN, grace_ms=3 * _MIN) == "restart:stale"


def test_cli_prints_verdict_stale(tmp_path, capsys):
    db = tmp_path / "scout.db"
    _mk_scout_db(db, heartbeat_ms=1)  # древний heartbeat
    rc = sh.main([
        "--db", str(db), "--rss-kb", "1000", "--cap-mb", "300",
        "--max-silence-sec", "180", "--elapsed-sec", "600", "--grace-sec", "180",
    ])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "restart:stale"


def test_cli_prints_ok_fresh(tmp_path, capsys):
    db = tmp_path / "scout.db"
    _mk_scout_db(db, heartbeat_ms=int(__import__("time").time() * 1000))  # свежий
    sh.main(["--db", str(db), "--elapsed-sec", "600", "--grace-sec", "180"])
    assert capsys.readouterr().out.strip() == "ok"


def test_cli_prints_rss_over_cap(tmp_path, capsys):
    # RSS выше капа → restart:rss даже при свежем heartbeat (конверсия МБ↔КБ в CLI)
    db = tmp_path / "scout.db"
    _mk_scout_db(db, heartbeat_ms=int(__import__("time").time() * 1000))
    sh.main(["--db", str(db), "--rss-kb", str(400 * 1024), "--cap-mb", "300",
             "--elapsed-sec", "600", "--grace-sec", "180"])
    assert capsys.readouterr().out.strip() == "restart:rss"

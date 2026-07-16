"""Решатель здоровья скаута для супервизора в start.sh (ADR-0016 в.4, #51).

Stdlib-only (sqlite3/argparse/time) — без новых зависимостей. Супервизор (shell-loop в start.sh)
зовёт этот CLI на каждой проверке и получает вердикт: `ok` | `restart:rss` | `restart:stale`.
Чистые функции — юнит-тестируемы. НЕ импортирует движок/vendor (читает scout.db сырым sqlite3),
чтобы решение о рестарте не зависело от состояния движка. Труба scout→ядро→консоль — #52/#53.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time


def read_heartbeat_ms(db_path: str) -> int | None:
    """Последний heartbeat_ms скаута из scout_control (id=1). None, если БД/таблицы/строки нет
    (скаут ещё не инициализировал снимок) — супервизор трактует через grace-окно, не как смерть."""
    try:
        con = sqlite3.connect(db_path, timeout=1.0)
        try:
            row = con.execute(
                "SELECT heartbeat_ms FROM scout_control WHERE id=1"
            ).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    if not row or row[0] is None:
        return None
    return int(row[0])


def rss_over_cap(rss_kb: int, cap_mb: int) -> bool:
    """RSS скаута выше капа (защита от OOM — иначе OOM-killer контейнера убил бы движок)."""
    return cap_mb > 0 and rss_kb > cap_mb * 1024


def heartbeat_stale(heartbeat_ms: int | None, now_ms: int, max_silence_ms: int) -> bool:
    """Скаут завис: heartbeat молчит дольше max_silence (нет строки → залип)."""
    if heartbeat_ms is None:
        return True
    return (now_ms - heartbeat_ms) > max_silence_ms


def verdict(
    *, rss_kb: int, cap_mb: int, heartbeat_ms: int | None, now_ms: int,
    max_silence_ms: int, elapsed_ms: int, grace_ms: int,
) -> str:
    """`ok` | `restart:rss` | `restart:stale`. RSS-кап действует ВСЕГДА (жёсткая защита от OOM).
    В grace-окне stale не флагаем: свежий скаут ещё в bootstrap (heartbeat не записан)."""
    if rss_over_cap(rss_kb, cap_mb):
        return "restart:rss"
    if elapsed_ms < grace_ms:
        return "ok"
    if heartbeat_stale(heartbeat_ms, now_ms, max_silence_ms):
        return "restart:stale"
    return "ok"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Вердикт здоровья скаута для супервизора start.sh")
    ap.add_argument("--db", required=True, help="путь к scout.db")
    ap.add_argument("--rss-kb", type=int, default=0, help="RSS процесса скаута, КБ (из ps)")
    ap.add_argument("--cap-mb", type=int, default=300, help="RSS-кап, МБ")
    ap.add_argument("--max-silence-sec", type=int, default=180, help="порог залипания heartbeat")
    ap.add_argument("--elapsed-sec", type=int, default=0, help="сколько скаут живёт с рестарта")
    ap.add_argument("--grace-sec", type=int, default=180, help="стартовое окно без stale-проверки")
    a = ap.parse_args(argv)
    print(verdict(
        rss_kb=a.rss_kb, cap_mb=a.cap_mb,
        heartbeat_ms=read_heartbeat_ms(a.db), now_ms=int(time.time() * 1000),
        max_silence_ms=a.max_silence_sec * 1000,
        elapsed_ms=a.elapsed_sec * 1000, grace_ms=a.grace_sec * 1000,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Автотест fail-closed гейта скаута (ADR-0016 в.1, #51 п.4д).

Сорсим НАСТОЯЩИЙ start.sh (main НЕ стартует — source-guard) и зовём start_scout_if_enabled.
Фиксируем в CI безопасное направление: при SCOUT_ENABLED≠1 обёртка НЕ запускает команду скаута
(vendor-дефолт True не решает). Включённый путь + супервизор (рестарт/RSS) доказаны локальным
прогоном (а)-(г) — фоновая петля в CI-юните не гоняется (риск осиротевших процессов). Требует `sh`.
"""

import subprocess
from pathlib import Path

_START = Path(__file__).resolve().parents[1] / "start.sh"


def _run_gate(scout_enabled, marker):
    # SCOUT_CMD трогает marker — если гейт пропустил скаут, файл появится; при fail-closed его нет.
    env_line = "" if scout_enabled is None else f"SCOUT_ENABLED={scout_enabled} "
    script = (
        f'. "{_START}"\n'
        f'export SCOUT_CMD="touch {marker}"\n'
        f"{env_line}start_scout_if_enabled\n"
        "sleep 0.3\n"
    )
    r = subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=15)
    return r.stdout + r.stderr


def test_gate_fail_closed_unset(tmp_path):
    marker = tmp_path / "ran"
    out = _run_gate(None, marker)
    assert "fail-closed" in out and "НЕ поднят" in out
    assert not marker.exists()          # скаут НЕ запущен без явного SCOUT_ENABLED=1


def test_gate_fail_closed_zero(tmp_path):
    marker = tmp_path / "ran"
    out = _run_gate("0", marker)
    assert "fail-closed" in out
    assert not marker.exists()


def test_scout_child_clears_database_url(tmp_path):
    """Хвост #51 (ADR-0016 в.2, #52): дочерний скаут получает DATABASE_URL ЗАЧИЩЕННЫМ (env -u) —
    иначе на Postgres-движке скаут делил бы его БД вместо своей scout.db."""
    marker = tmp_path / "dburl"
    dump = tmp_path / "dump.sh"
    dump.write_text('echo "DBURL=[${DATABASE_URL:-EMPTY}]" > "$1"; sleep 2\n')
    script = (
        f'. "{_START}"\n'
        'export DATABASE_URL="postgresql://engine/db"\n'
        f'SCOUT_DB="{tmp_path}/scout.db"\n'
        'SCOUT_RSS_CAP_MB=300 SCOUT_CHECK_SEC=2 SCOUT_MAX_SILENCE_SEC=99 SCOUT_GRACE_SEC=99\n'
        'SCOUT_RPS=1 SCOUT_LIST_MAX=50 SCOUT_CAL_UTC_HOUR=5 SCOUT_TFS=4h\n'
        f'SCOUT_CMD="sh {dump} {marker}"\n'
        'scout_supervise >/dev/null 2>&1 &\n'   # редирект: фон не держит captured-пайп subprocess
        'SUP=$!\n'
        f'i=0; while [ ! -f "{marker}" ] && [ $i -lt 20 ]; do sleep 0.2; i=$((i+1)); done\n'
        'kill $SUP 2>/dev/null\n'
        f'pkill -f "{dump}" 2>/dev/null\n'
        'exit 0\n'
    )
    subprocess.run(["sh", "-c", script], capture_output=True, text=True, timeout=20)
    assert marker.exists(), "SCOUT_CMD не запустился"
    assert "DBURL=[EMPTY]" in marker.read_text()  # DATABASE_URL зачищен для скаута

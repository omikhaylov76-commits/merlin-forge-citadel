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

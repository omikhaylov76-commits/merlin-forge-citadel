"""Тестовая проводка: кладём вендоренный снимок Пифагора на sys.path (для parity-теста).

Юнит-тесты client/mapper/bot вендор НЕ импортируют — вставка пути им безвредна (импорт ленивый).
PIFAGOR_HOME выставляем тем же путём, чтобы reader и прямой build_monitor смотрели в один вендор.
"""

import os
import sys

_VENDOR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "pifagor", "vendor"))
os.environ.setdefault("PIFAGOR_HOME", _VENDOR)
if _VENDOR not in sys.path:
    # APPEND: вендор содержит пакет `app` (коллизия с адаптерным) — адаптерный `app` должен остаться
    # первым (rootdir pytest). Уникальные dashboard/storage/state/config находятся в вендоре и так.
    sys.path.append(_VENDOR)

"""Потолок конкуренции 24 (ADR-0023, S8) — тесты против НАСТОЯЩЕГО vendored config.knobs, НЕ моков
(урок S7: вендор-интеграции проверяем на живом коде).

Санкц-дельта генома: `CONCURRENCY_CAP hi:16→24` — валидатор принимает до 24 (Борс, демо). Логика
движка не тронута. Дефолт эталона/флота (`risk.CONCURRENCY_CAP=8`) НЕ сдвигается правкой потолка —
регресс: граница не переопределяет дефолт (флот на env=16, эталон=8 остаются валидны)."""
import config.knobs as knobs


def test_ceiling_raised_to_24():
    # Геном: единственный потолок cap = 24 (была 16).
    assert knobs.KNOB_SPECS["CONCURRENCY_CAP"]["hi"] == 24


def test_validate_accepts_24_rejects_25():
    assert knobs.validate("CONCURRENCY_CAP", 24) == (True, None)   # новый потолок принят
    ok, err = knobs.validate("CONCURRENCY_CAP", 25)                 # 25 — за границей
    assert ok is False and "верхнюю границу" in err


def test_fleet_and_etalon_values_still_valid():
    # Демо-флот (16), эталон/дефолт (8), нижняя граница (1) — по-прежнему валидны.
    assert knobs.validate("CONCURRENCY_CAP", 16) == (True, None)
    assert knobs.validate("CONCURRENCY_CAP", 8) == (True, None)
    assert knobs.validate("CONCURRENCY_CAP", 1) == (True, None)


def test_lower_bound_intact():
    # Нижняя граница lo:1 не тронута — 0 отвергается (потолок правили только сверху).
    ok, err = knobs.validate("CONCURRENCY_CAP", 0)
    assert ok is False and "нижнюю границу" in err


def test_default_unchanged_etalon_8():
    # Регресс: дефолт эталона/флота = 8 (risk.py env_int(...,8); env не задан в тестах/CI).
    # Правка ПОТОЛКА (hi) дефолт не переопределяет — Персиваль/Галахад/эталон не сдвигаются.
    assert knobs.default("CONCURRENCY_CAP") == 8

"""Гвозди на оверрайды дозора (Разведка-стол): whitelist-скоуп (страж 3), анти-инъекция coercion
(страж 2), атомарная запись + gen-бамп. Чистые функции — без сети/БД."""

import os

from app.scout_overrides import to_env_lines, write_overrides


def test_whitelist_scope_only_scout_keys():
    # движковый/риск-ключ НЕ должен просочиться в SCOUT_*-оверрайды (страж 3: whitelist в коде)
    s = {
        "min_age_days": 200, "primary_tf": "1h", "tfs": ["4h", "1h"],
        "LIVE_TRADING_ENABLED": 1, "risk_dd_pct": 5, "COINS_CONFIG": "BTCUSDT",
    }
    lines = to_env_lines(s)
    joined = "\n".join(lines)
    assert "export SCOUT_MIN_AGE_DAYS=200" in lines
    assert "export SCOUT_TF=1h" in lines
    assert "export SCOUT_TFS=4h,1h" in lines
    assert "LIVE_TRADING" not in joined
    assert "risk" not in joined.lower()
    assert "COINS_CONFIG" not in joined


def test_injection_coerced_not_raw():
    # строка-инъекция в числовой ключ → coercion падает → ключ ПРОПУСКАЕТСЯ (не пишем сырьё в файл)
    s = {"min_age_days": "180; rm -rf /", "rps": "$(touch pwned)", "min_score": 40}
    lines = to_env_lines(s)
    joined = "\n".join(lines)
    assert "rm -rf" not in joined
    assert "touch" not in joined
    assert "$(" not in joined
    assert "export SCOUT_MIN_SCORE=40" in lines  # валидный сосед прошёл


def test_bad_tf_enum_dropped():
    s = {"primary_tf": "15m", "tfs": ["4h", "15m", "1h"]}
    lines = to_env_lines(s)
    joined = "\n".join(lines)
    assert "15m" not in joined
    assert "export SCOUT_TFS=4h,1h" in lines  # 15m выброшен из списка ТФ
    assert not any(x.startswith("export SCOUT_TF=") for x in lines)  # primary 15m отброшен целиком


def test_write_overrides_atomic_and_gen(tmp_path):
    p = str(tmp_path / "scout_overrides.env")
    n = write_overrides({"min_age_days": 365, "primary_tf": "1h", "tfs": ["1h"]}, p)
    assert n == 3
    content = open(p).read()
    assert "export SCOUT_MIN_AGE_DAYS=365" in content
    assert "export SCOUT_TF=1h" in content
    assert os.path.exists(p + ".gen")
    assert int(open(p + ".gen").read()) > 0
    assert not os.path.exists(p + ".tmp")  # tmp прибран (атомарная замена)

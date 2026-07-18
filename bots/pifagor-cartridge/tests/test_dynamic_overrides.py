"""Гвозди на критерии «Динамики» (S8/ADR-0020): whitelist-скоуп (страж 3), анти-инъекция coercion
в int (страж 2), запись ТОЛЬКО при изменении + атомарность, read_criteria robustness, fetch_self
парс, refetch_loop пишет и переживает сбой ядра (страж 1). Сеть замокана — БД/бирж не трогаем."""

import json
import os

import app.dynamic_overrides as mod
from app.dynamic_overrides import read_criteria, to_criteria, write_criteria


def test_whitelist_scope_only_dynamic_keys():
    # дозор/движок/риск-ключ НЕ должен просочиться в критерии (страж 3: whitelist в коде)
    c = to_criteria({
        "min_score": 50, "stack_max": 5, "fresh_bars": 48,
        "min_age_days": 200, "LIVE_TRADING_ENABLED": 1, "COINS_CONFIG": "BTCUSDT",
    })
    assert c == {"min_score": 50, "stack_max": 5, "fresh_bars": 48}
    assert "min_age_days" not in c and "LIVE_TRADING_ENABLED" not in c


def test_injection_coerced_to_int_not_raw():
    # строка-инъекция в числовой ключ → int() падает → ключ ПРОПУСКАЕТСЯ (не пишем сырьё в файл)
    c = to_criteria({"min_score": "35; rm -rf /", "stack_max": "$(touch pwned)", "fresh_bars": 48})
    assert c == {"fresh_bars": 48}                      # валидный сосед прошёл, инъекции выброшены
    assert all(isinstance(v, int) for v in c.values())


def test_read_criteria_robust(tmp_path):
    p = str(tmp_path / "dynamic_criteria.json")
    assert read_criteria(p) == {}                       # нет файла → {}
    open(p, "w").write("{не json")
    assert read_criteria(p) == {}                       # битый JSON → {}
    open(p, "w").write('[1,2,3]')
    assert read_criteria(p) == {}                       # не-dict → {}
    open(p, "w").write('{"min_score": 40, "junk": "x"}')
    assert read_criteria(p) == {"min_score": 40}        # валидный dict → только whitelist


def test_write_only_on_change_and_atomic(tmp_path):
    p = str(tmp_path / "dynamic_criteria.json")
    base = {"min_score": 50, "stack_max": 5, "fresh_bars": 48}
    assert write_criteria(base, p) is True
    assert json.load(open(p)) == base
    assert write_criteria(base, p) is False                     # не менялось → не пишем
    assert write_criteria({**base, "min_score": 60}, p) is True  # изменилось → пишем
    assert json.load(open(p))["min_score"] == 60
    assert not any(f.startswith(".dyncrit.") for f in os.listdir(tmp_path))  # tmp прибран


def test_fetch_self_parses(monkeypatch):
    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"settings": {"min_score": 35, "stack_max": 8, "fresh_bars": 72}}'

    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda req, timeout=10.0: FakeResp())
    s = mod.fetch_self("http://core", "tok")
    assert s == {"min_score": 35, "stack_max": 8, "fresh_bars": 72}


def test_refetch_loop_writes_then_stops(tmp_path, monkeypatch):
    p = str(tmp_path / "dynamic_criteria.json")
    settings = {"min_score": 50, "stack_max": 5, "fresh_bars": 48, "junk": "x"}
    monkeypatch.setattr(mod, "fetch_self", lambda url, tok: settings)
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 1                           # первый проход пишет, затем стоп

    mod.refetch_loop("http://core", "tok", p, interval=0, sleep=lambda s: None, stop=stop)
    assert json.load(open(p)) == {"min_score": 50, "stack_max": 5, "fresh_bars": 48}  # junk отсеян


def test_refetch_loop_survives_core_down(tmp_path, monkeypatch):
    p = str(tmp_path / "dynamic_criteria.json")

    def boom(url, tok):
        raise OSError("ядро недоступно")

    monkeypatch.setattr(mod, "fetch_self", boom)
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 2

    mod.refetch_loop("http://core", "tok", p, interval=0, sleep=lambda s: None, stop=stop)
    assert not os.path.exists(p)                         # сбой ядра не уронил цикл (страж 1)

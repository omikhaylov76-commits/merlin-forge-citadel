"""S8 F-warm-button (ADR-0022) — против НАСТОЯЩЕГО вендора (app==vendor) + адаптер-сема.

Регулярный пакет `app` есть и у картриджа, и у вендора → вендорный app.cycle из общего набора
картриджа не импортируется. Вендор-проверки (`maybe_warm`/`_warm_one_button`) гоняем изолированным
subprocess (cwd=vendor, как движок в проде), скрипт `_warm_apply_vendor.py`. Плюс адаптер-тест
`reader.warm_apply` (контекст картриджа): что кладём корректный WARM_APPLY-интент (CSV), который
вендор парсит (сема producer↔consumer)."""
import os
import subprocess
import sys
from unittest import mock


def test_warm_apply_vs_real_vendor():
    here = os.path.dirname(os.path.abspath(__file__))
    vendor = os.path.abspath(os.path.join(here, "..", "..", "pifagor", "vendor"))
    script = os.path.join(here, "_warm_apply_vendor.py")
    env = dict(os.environ, PYTHONPATH=vendor, PIFAGOR_HOME=vendor, BYBIT_API_KEY="test",
               BYBIT_API_SECRET="test", BYBIT_DEMO="1", LIVE_TRADING_ENABLED="0")
    r = subprocess.run([sys.executable, script], cwd=vendor, env=env,
                       capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, ("ADR-0022 F-warm-button vendor-прогон упал:\n"
                               f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}")


def test_warm_apply_reader_writes_intent():
    """Адаптер: `reader.warm_apply(coins)` кладёт WARM_APPLY-интент с CSV монет (source=button) —
    ровно тот формат, что вендорный `_parse_warm_approved` читает (проверено в vendor-прогоне).
    Нормализация: upper/strip, пустые/None выкидываются."""
    from app.reader import PifagorReader

    r = PifagorReader.__new__(PifagorReader)  # без __init__ (нужен только self.db)
    r.db = mock.Mock()
    r.warm_apply(["1inchusdt", " epicusdt ", "", None])
    r.db.config_log_append.assert_called_once_with(
        "WARM_APPLY", None, "1INCHUSDT,EPICUSDT", source="button")

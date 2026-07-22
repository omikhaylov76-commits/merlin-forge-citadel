"""S8 Борс горн + самоход (ADR-0021) — прогон против НАСТОЯЩЕГО вендора (app==vendor).

Регулярный пакет `app` есть и у картриджа, и у вендора → вендорный app.cycle/app.main из
общего набора картриджа не импортируется. Проверки движка гоняем изолированным subprocess
(cwd=vendor, как движок в проде), скрипт `_warm_gorn_samohod_vendor.py`. Покрывает условия
подписи Куратора: тождество 4h, границы, флаг fail-closed, горн single-shot, routing через
_warm_one (auto_eligible, не _warm_one_button), has_active-skip (урок 18.07).
"""
import os
import subprocess
import sys


def test_adr0021_warm_rhythm_vs_real_vendor():
    here = os.path.dirname(os.path.abspath(__file__))
    vendor = os.path.abspath(os.path.join(here, "..", "..", "pifagor", "vendor"))
    script = os.path.join(here, "_warm_gorn_samohod_vendor.py")
    # дефолт флота: флаг самохода НЕ задан (проверяем fail-closed). Demo-заглушки — на случай
    # импорт-валидации config (движок не бутим, только импорт + функции).
    env = dict(os.environ, PYTHONPATH=vendor, PIFAGOR_HOME=vendor, BYBIT_API_KEY="test",
               BYBIT_API_SECRET="test", BYBIT_DEMO="1", LIVE_TRADING_ENABLED="0")
    env.pop("WARM_EACH_CYCLE", None)
    r = subprocess.run([sys.executable, script], cwd=vendor, env=env,
                       capture_output=True, text=True, timeout=90)
    assert r.returncode == 0, ("ADR-0021 vendor-прогон упал:\n"
                               f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}")

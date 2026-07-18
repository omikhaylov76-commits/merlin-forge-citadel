"""Критерии «Динамики» (S8/ADR-0020): ядро = durable-истина, картридж = stateless-применитель.

Зеркало `scout_overrides.py`, но с ключевым отличием механизма (ADR-0020 D1): дозор source'ит
shell-файл и рестартит СКАУТ (отдельный супервизорный процесс). Провайдер же живёт В адаптере-
foreground (PID 1) — рестартить нельзя. Поэтому здесь: фоновая нить ПЕРИОДИЧЕСКИ (re-fetch) тянет
`GET /v1/dynamic/settings/self` и пишет JSON-файл критериев атомарно ТОЛЬКО при изменении; провайдер
читает этот файл ЖИВЬЁМ в каждом `_recompute` (без рестарта). Периодический re-fetch (не одноразовый
boot) = живое применение за минуты → команда `dynamic_apply` не нужна (D2).

СТРАЖИ (зеркало дозора):
1. Re-fetch НЕ блокирует движок/провайдер: провайдер стартует на ген-дефолтах cfg; нить ретраит
   фоном, по успеху пишет файл → провайдер подхватит на след. скане.
2. Анти-инъекция: пишем ТОЛЬКО whitelist-ключи, значения строго приводим к int (никогда не пишем
   сырую строку из сети в файл, который читает провайдер).
3. Скоуп: через канал ходят ТОЛЬКО движко-критерии отбора (min_score/stack_max/fresh_bars). Дозор/
   риск — никогда (whitelist в коде; дозор-скоуп идёт своим каналом 0018).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
import urllib.request

log = logging.getLogger("mfc.dynamic-overrides")

# Страж 2+3: whitelist движко-критериев (все int). Дозор-скоуп (капитализация/оборот/возраст)
# физически отсутствует — он идёт каналом дозора (ADR-0018), не смешиваем (ADR-0018 п.3 зеркально).
_WHITELIST = ("min_score", "stack_max", "fresh_bars")


def to_criteria(settings: dict) -> dict:
    """Собрать {ключ: int} из whitelist. Кривое/чужое — молча пропуск (провайдер → ген-дефолт).
    НИКОГДА не кладём сырую строку из сети (страж 2: только int)."""
    out: dict = {}
    for key in _WHITELIST:
        if key in settings:
            try:
                out[key] = int(settings[key])
            except (TypeError, ValueError):
                log.warning("критерий %s: не число (%r) — пропуск", key, settings[key])
    return out


def read_criteria(path: str) -> dict:
    """Прочитать JSON-файл критериев → {ключ: int} (только whitelist). Нет файла / битый / чужие
    ключи → {} (провайдер возьмёт ген-дефолты cfg). Используется и провайдером (живое чтение), и
    write_criteria (сравнение для «писать только при изменении»)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return to_criteria(data) if isinstance(data, dict) else {}


def write_criteria(criteria: dict, path: str) -> bool:
    """Атомарно записать файл-критерии ТОЛЬКО при изменении (tmp+os.replace: провайдер читает целый
    файл). Возвращает True, если файл изменился. Лог смены по ключам (D1: канал виден глазами)."""
    old = read_criteria(path)
    if criteria == old:
        return False
    changed = [f"{k} {old.get(k)}→{criteria.get(k)}" for k in _WHITELIST
               if old.get(k) != criteria.get(k)]
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".dyncrit.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(criteria, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    log.info("критерии динамики: %s", ", ".join(changed) or "инициализация")
    return True


def fetch_self(core_url: str, token: str, *, timeout: float = 10.0) -> dict:
    """GET /v1/dynamic/settings/self (instance-токен). Возвращает settings. Рейзит на сбое."""
    req = urllib.request.Request(
        core_url.rstrip("/") + "/v1/dynamic/settings/self",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (наш core_url)
        data = json.loads(resp.read())
    return data.get("settings") or {}


def refetch_loop(
    core_url: str, token: str, path: str, *,
    interval: float = 300.0, sleep=time.sleep, stop=None,
) -> None:
    """Страж 1: фоновая ПЕРИОДИЧЕСКАЯ нить (D1). Каждые ~interval сек тянет /self и пишет файл-
    критерии при изменении. Сбой (сеть/ядро) — лог + продолжаем (не падаем; провайдер держит
    последнее валидное/ген-дефолты). `stop` — callable для теста (True → выход из цикла)."""
    while stop is None or not stop():
        try:
            crit = to_criteria(fetch_self(core_url, token))
            # пустой (кривой 200 без settings) → НЕ клоббрим файл: держим прежние критерии
            if crit:
                write_criteria(crit, path)
            else:
                log.warning("re-fetch: ядро вернуло пусто — файл не трогаю (держу прежние)")
        except Exception as exc:  # noqa: BLE001 — сеть/ядро недоступно: ретрай на след. цикле
            log.info("re-fetch критериев: не удалось (%s), повтор через %.0fс", exc, interval)
        sleep(interval)

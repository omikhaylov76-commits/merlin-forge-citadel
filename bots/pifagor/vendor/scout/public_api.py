# -*- coding: utf-8 -*-
"""scout.public_api — KEYLESS клиент публичных эндпоинтов Bybit v5 для скаута (Веха 7).

Только stdlib `urllib` к ПУБЛИЧНЫМ эндпоинтам (instruments/tickers/kline) — БЕЗ pybit/ключей/broker
(граница безопасности advisory-фазы: скаут физически не может ставить ордера). Формат klines 1:1 с
broker/bybit_client.get_klines (duck-type → market/fetch работают без изменений).

Троттл и модель ошибок (§H плана, аудит 2026-07-08): публичный лимит per-IP = 600 запросов/5с; превышение
→ HTTP 403 «access too frequent» + бан IP на 10 минут (429/retCode 10006 — это per-UID ПРИВАТНЫХ эндпоинтов,
у keyless-скаута их нет). Единый токен-бакет `SCOUT_RPS` (3 = 15/5с = 2.5% квоты). 403 = circuit-breaker:
`RateLimitBan` → вызывающий обязан прервать ВЕСЬ прогон и ждать ≥10 мин (per-запрос backoff на 403 лишь
продлевает бан). 429/сеть — второстепенная ветка: backoff+джиттер, продолжение с места.
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import scout.config as scfg


class RateLimitBan(Exception):
    """HTTP 403 публичного per-IP лимита (бан IP ~10 мин). Circuit-breaker: прервать прогон, ждать."""


class ExchangeError(Exception):
    """Не-403 сбой публичного запроса (сеть/парс/retCode) после ретраев."""


def parse_kline_rows(rows):
    """Сырые строки Bybit kline (`result.list`: [start,open,high,low,close,volume,turnover]) → список
    dict в ХРОНОЛОГИИ (по возрастанию времени), формат 1:1 с broker/bybit_client.get_klines. Пустой/None → []."""
    out = []
    for x in sorted(rows or [], key=lambda r: int(r[0])):
        out.append({"time": int(x[0]), "open": float(x[1]), "high": float(x[2]),
                    "low": float(x[3]), "close": float(x[4]), "volume": float(x[5])})
    return out


class PublicMarket:
    """Публичный keyless-доступ к рынку с единым троттл-бакетом и 403-circuit-breaker.

    duck-type `get_klines(symbol, interval, limit)` совпадает с broker/bybit_client → market/fetch-обвязка
    работает без правок. get_instruments()/get_tickers() отдают сырые list Bybit (result.list)."""

    def __init__(self, *, base_url=None, rps=None, timeout=None):
        self.base = (base_url or scfg.SCOUT_BASE_URL).rstrip("/")
        rps = float(scfg.SCOUT_RPS if rps is None else rps)
        self._min_interval = (1.0 / rps) if rps > 0 else 0.0
        self.timeout = int(scfg.SCOUT_HTTP_TIMEOUT if timeout is None else timeout)
        self._lock = threading.Lock()      # единый бакет на ВСЕ вызовы (§H: не по-потоку)
        self._last = 0.0

    def _throttle(self):
        """Держим ≤ rps: спим до следующего разрешённого слота (единый бакет под lock)."""
        with self._lock:
            now = time.time()
            wait = self._last + self._min_interval - now
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()

    def _get(self, path, params, *, retries=3):
        url = self.base + path + "?" + urllib.parse.urlencode(params)
        last_err = None
        for attempt in range(retries):
            self._throttle()
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "pifagor-scout/1.0"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.loads(r.read().decode("utf-8"))
                rc = data.get("retCode")
                if rc not in (0, None):
                    raise ExchangeError(f"retCode={rc} retMsg={data.get('retMsg')}")
                return data.get("result", {}) or {}
            except urllib.error.HTTPError as e:
                if e.code == 403:                       # per-IP бан — НЕ ретраить, прервать прогон
                    raise RateLimitBan(f"HTTP 403 (per-IP ban ~10 мин): {path}") from e
                last_err = e
            except Exception as e:
                last_err = e
            time.sleep(min(2 ** attempt, 8) + 0.1)      # backoff (429/сеть), затем ретрай
        raise ExchangeError(f"GET {path} failed after {retries} tries: {last_err}")

    def get_instruments(self):
        """Все линейные перпы (постранично через nextPageCursor). Сырые dict Bybit (symbol/status/settleCoin/…)."""
        out, cursor = [], None
        for _ in range(20):
            params = {"category": "linear", "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            res = self._get("/v5/market/instruments-info", params)
            out.extend(res.get("list", []) or [])
            cursor = res.get("nextPageCursor")
            if not cursor:
                break
        return out

    def get_tickers(self):
        """Тикеры всей линейной категории ОДНИМ батчем (turnover24h/bid1/ask1/lastPrice/fundingRate)."""
        res = self._get("/v5/market/tickers", {"category": "linear"})
        return res.get("list", []) or []

    def get_klines(self, symbol, interval=None, limit=1000, end=None):
        """Свечи в хронологии (формат = broker/bybit_client). interval Bybit: '240'=4h, '60'=1h, '5'=5m."""
        params = {"category": "linear", "symbol": symbol,
                  "interval": interval or "240", "limit": limit}
        if end is not None:
            params["end"] = end
        res = self._get("/v5/market/kline", params)
        return parse_kline_rows(res.get("list", []))

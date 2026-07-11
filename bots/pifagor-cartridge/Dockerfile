# Образ картриджа Пифагора — деплоится оркестратором через InfraDriver (шов S5), как paper-bot.
# ВНИМАНИЕ: build context = каталог `bots/` (нужны И адаптер, И вендоренный снимок движка):
#   docker build -f bots/pifagor-cartridge/Dockerfile -t mfc-pifagor-cartridge bots
FROM python:3.12-slim

WORKDIR /app

# 1. Вендоренный снимок Пифагора @b75bd17 (read-only движок) → /pifagor (PIFAGOR_HOME).
#    Снимок по существу не правим (ADR-0001) — адаптер отдельным слоем ниже.
COPY pifagor/vendor /pifagor

# 2. Зависимости движка (pandas/numpy/pybit/websocket/psycopg2) — сначала манифест, кэш слоя стабилен.
RUN pip install --no-cache-dir -r /pifagor/requirements.txt

# 3. Адаптер-обёртка (единственная новая зависимость — httpx, клиент API ядра S4).
COPY pifagor-cartridge/pyproject.toml ./pyproject.toml
COPY pifagor-cartridge/app ./app
RUN pip install --no-cache-dir .

COPY pifagor-cartridge/start.sh ./start.sh
RUN chmod +x ./start.sh

ENV PIFAGOR_HOME=/pifagor
# БЕЗОПАСНЫЙ РЕЖИМ (гейт Ф2): dry-run (брокера не трогаем) + demo-домен. Реальные ключи/торговля —
# ОТДЕЛЬНЫЙ гейт go-live (только по явному «go» Оператора). MAINNET доп. заперт ALLOW_MAINNET.
ENV LIVE_TRADING_ENABLED=0 BYBIT_DEMO=1

# restartPolicy=never ставит инфра (OPS1): stop_close гасит процесс насовсем, без авто-перезапуска.
CMD ["./start.sh"]

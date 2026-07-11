# Образ картриджа paper-bot — деплоится оркестратором через InfraDriver (шов S5).
# Слим-база 3.12 (цель деплоя, ADR-0003); единственная зависимость — httpx.
FROM python:3.12-slim

WORKDIR /app

# Сначала манифест — кэш слоя зависимостей не рвётся при правке кода.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

# Картридж читает вход из env по Контракту (MF_INSTANCE_ID/TOKEN/CORE_URL). restartPolicy=never
# ставит инфра (OPS1): stop_close должен гасить процесс насовсем, без авто-перезапуска.
CMD ["python", "-m", "app.main"]

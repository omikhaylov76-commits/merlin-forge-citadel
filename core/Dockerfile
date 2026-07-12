# Образ ядра Merlin Forge Citadel для облака (Railway, #15). Собирается в CI (ghcr), не локально (#12).
# Контрол-плейн: FastAPI + Alembic + Postgres (Railway). Публичный URL, плотная авторизация (ADR-0008v2).
FROM python:3.12-slim

WORKDIR /app

# Манифест первым — кэш слоя зависимостей стабилен при правках кода.
COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN pip install --no-cache-dir .

COPY start.sh ./start.sh
RUN chmod +x ./start.sh

# Railway задаёт $PORT; DATABASE_URL — от Railway Postgres (шему правит start.sh).
ENV PORT=8000
CMD ["./start.sh"]

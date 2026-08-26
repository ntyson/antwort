# Deploy from the antwort monorepo root (Railway default).
# Prefer setting Root Directory to `alpaca-bot` instead; this is a fallback.
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    DATA_DIR=/app/data \
    LOG_DIR=/app/logs

COPY alpaca-bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alpaca-bot/pyproject.toml .
COPY alpaca-bot/src ./src
RUN pip install --no-cache-dir -e .

RUN mkdir -p /app/data /app/logs

EXPOSE 8080
CMD ["python", "-m", "alpaca_bot", "run"]

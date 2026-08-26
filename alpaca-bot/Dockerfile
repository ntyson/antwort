FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    DATA_DIR=/app/data \
    LOG_DIR=/app/logs

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml .
COPY src ./src
RUN pip install --no-cache-dir -e .

RUN mkdir -p /app/data /app/logs

# Long-running worker (not a web server)
CMD ["python", "-m", "alpaca_bot", "run"]

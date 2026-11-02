# BIZKHATA backend — Render / Docker
# Render: New Web Service → Docker → root directory = backend
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    WEB_CONCURRENCY=2 \
    THREADS=4

WORKDIR /app

# libpq for psycopg2-binary runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser

# Render injects $PORT. Local default is 8000.
EXPOSE 8000
CMD ["sh", "-c", "gunicorn -b 0.0.0.0:${PORT:-8000} -w ${WEB_CONCURRENCY:-2} --threads ${THREADS:-4} --timeout 120 --graceful-timeout 30 --keepalive 5 --access-logfile - --error-logfile - wsgi:application"]

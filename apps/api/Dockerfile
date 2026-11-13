# yaprr API: Cloud Run (or any container host). Listens on $PORT.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY yaprr_api ./yaprr_api
COPY migrations ./migrations
COPY alembic.ini .
# Migrations run on startup (yaprr_api.db.migrate), so a new revision ships with the image.
CMD ["sh", "-c", "uvicorn yaprr_api.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]

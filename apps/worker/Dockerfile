# yaprr voice worker: long-running process that connects OUT to LiveKit (no inbound port needed).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Bake the turn-detector / VAD model files into the image (no download at call time).
RUN python main.py download-files
CMD ["python", "main.py", "start"]

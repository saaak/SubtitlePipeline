FROM node:22-bookworm AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json frontend/tsconfig.json frontend/tsconfig.node.json frontend/vite.config.ts frontend/index.html ./
COPY frontend/src ./src
RUN npm ci && npm run build

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SUBPIPELINE_DB_PATH=/config/subpipeline.db \
    SUBPIPELINE_FRONTEND_DIST=/app/frontend/dist \
    SUBPIPELINE_PORT=8000

RUN apt-get update \
    && apt-get install -y --no-install-recommends supervisor ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt \
    && mkdir -p /data /output /models /config

COPY backend /app/backend
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist
COPY container/supervisord.conf /etc/supervisor/conf.d/subpipeline.conf

EXPOSE 8000
VOLUME ["/data", "/output", "/models", "/config"]

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/subpipeline.conf"]

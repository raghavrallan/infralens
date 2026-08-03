FROM node:22-alpine AS frontend-builder

WORKDIR /build/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
ARG PIP_TRUSTED_HOSTS=""
RUN if [ -n "$PIP_TRUSTED_HOSTS" ]; then \
      TRUSTED_ARGS=""; \
      for host in $PIP_TRUSTED_HOSTS; do TRUSTED_ARGS="$TRUSTED_ARGS --trusted-host $host"; done; \
      pip install $TRUSTED_ARGS --no-cache-dir -r requirements.txt; \
    else \
      pip install --no-cache-dir -r requirements.txt; \
    fi

COPY app ./app
COPY scripts ./scripts
COPY --from=frontend-builder /build/frontend/out ./frontend/out

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

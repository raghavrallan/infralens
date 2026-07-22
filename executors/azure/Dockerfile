# The official Azure CLI image is intentionally the runtime for this executor.
# It is minimal and has no package manager or pip, so install the Python worker
# dependencies in a builder stage and copy only those dependencies across.
FROM python:3.12-slim AS dependencies
ARG PIP_TRUSTED_HOSTS=""
RUN if [ -n "$PIP_TRUSTED_HOSTS" ]; then \
      TRUSTED_ARGS=""; \
      for host in $PIP_TRUSTED_HOSTS; do TRUSTED_ARGS="$TRUSTED_ARGS --trusted-host $host"; done; \
      pip install $TRUSTED_ARGS --no-cache-dir --target /opt/executor-deps httpx==0.28.1 redis==5.2.1 rq==2.1.0; \
    else \
      pip install --no-cache-dir --target /opt/executor-deps httpx==0.28.1 redis==5.2.1 rq==2.1.0; \
    fi

FROM mcr.microsoft.com/azure-cli:2.76.0

WORKDIR /app
COPY --from=dependencies /opt/executor-deps /opt/executor-deps
COPY app ./app
COPY executors ./executors
COPY executors/common/startup.sh /usr/local/bin/devsecops-startup
RUN chmod 0755 /usr/local/bin/devsecops-startup
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/opt/executor-deps
ENV EXECUTOR_PROVIDER=azure
ENTRYPOINT ["/usr/local/bin/devsecops-startup"]
CMD ["python3", "-c", "from rq.cli import main; main()", "worker", "provider.azure.read", "provider.azure.write", "--worker-class", "executors.common.worker.Worker", "--url", "redis://redis:6379/0"]

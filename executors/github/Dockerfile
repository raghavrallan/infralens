# Copy gh from the official GitHub CLI image; the worker runtime has no shell
# execution path and invokes only the copied gh binary with shell=False.
FROM ghcr.io/cli/cli:v2.76.2 AS github-cli
FROM python:3.12-slim

WORKDIR /app
COPY --from=github-cli /usr/bin/gh /usr/local/bin/gh
ARG PIP_TRUSTED_HOSTS=""
RUN if [ -n "$PIP_TRUSTED_HOSTS" ]; then \
      TRUSTED_ARGS=""; \
      for host in $PIP_TRUSTED_HOSTS; do TRUSTED_ARGS="$TRUSTED_ARGS --trusted-host $host"; done; \
      pip install $TRUSTED_ARGS --no-cache-dir httpx==0.28.1 redis==5.2.1 rq==2.1.0; \
    else \
      pip install --no-cache-dir httpx==0.28.1 redis==5.2.1 rq==2.1.0; \
    fi
COPY app ./app
COPY executors ./executors
COPY executors/common/startup.sh /usr/local/bin/devsecops-startup
RUN chmod 0755 /usr/local/bin/devsecops-startup
ENV PYTHONUNBUFFERED=1
ENV EXECUTOR_PROVIDER=github
ENTRYPOINT ["/usr/local/bin/devsecops-startup"]
CMD ["python3", "-m", "executors.common.entrypoint"]

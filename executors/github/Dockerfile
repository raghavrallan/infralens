# Install GitHub CLI from official release tarball (avoids ghcr.io pull restrictions).
FROM python:3.12-slim

WORKDIR /app
ARG GH_CLI_VERSION=2.76.2
ARG PIP_TRUSTED_HOSTS=""
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tar gzip \
    && curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_CLI_VERSION}/gh_${GH_CLI_VERSION}_linux_amd64.tar.gz" \
      -o /tmp/gh.tgz \
    && tar -xzf /tmp/gh.tgz -C /tmp \
    && install -m 0755 "/tmp/gh_${GH_CLI_VERSION}_linux_amd64/bin/gh" /usr/local/bin/gh \
    && rm -rf /tmp/gh.tgz "/tmp/gh_${GH_CLI_VERSION}_linux_amd64" /var/lib/apt/lists/* \
    && if [ -n "$PIP_TRUSTED_HOSTS" ]; then \
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

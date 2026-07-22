# Copy the AWS CLI from the official AWS CLI image into a Python worker image.
FROM public.ecr.aws/aws-cli/aws-cli:2.27.60 AS aws-cli
FROM python:3.12-slim

WORKDIR /app
COPY --from=aws-cli /usr/local/aws-cli /usr/local/aws-cli
COPY --from=aws-cli /usr/local/bin/aws /usr/local/bin/aws
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
ENV EXECUTOR_PROVIDER=aws
ENTRYPOINT ["/usr/local/bin/devsecops-startup"]
CMD ["rq", "worker", "provider.aws.read", "provider.aws.write", "--worker-class", "executors.common.worker.Worker", "--url", "redis://redis:6379/0"]

# Isolated Container Apps rollout

The API and intelligence worker remain separate from the provider CLI
executors. Build each image with a pinned tag and push them to the existing
`eqacrregistrydeveastus001.azurecr.io` registry:

```powershell
$TAG = "<git-sha>"
az acr build --registry eqacrregistrydeveastus001 --image devsecops-suite:$TAG .
az acr build --registry eqacrregistrydeveastus001 --image devsecops-suite-azure-executor:$TAG --file executors/azure/Dockerfile .
az acr build --registry eqacrregistrydeveastus001 --image devsecops-suite-aws-executor:$TAG --file executors/aws/Dockerfile .
az acr build --registry eqacrregistrydeveastus001 --image devsecops-suite-github-executor:$TAG --file executors/github/Dockerfile .
```

Each provider executor has a common startup entrypoint at
`executors/common/startup.sh`. It verifies the provider CLI before the RQ
worker starts and installs the missing CLI as a runtime fallback. The normal
images already contain pinned CLI versions, so a healthy revision does not
download anything during startup. The startup log includes the provider and
CLI version; it never logs connection fields or credentials.

For local Docker validation, use the single application profile. This starts
the API, intelligence worker, and all provider RQ workers together; no manual
RQ worker command is needed:

```powershell
docker compose --profile container-app up --build
```

Inspect provider startup and queue activity with, for example,
`docker logs devsecops-azure-executor`. Do not put provider credentials in the
compose file; the executor retrieves them from the API over the authenticated
internal claim endpoint for each action.

Deploy the worker apps in the same Container Apps environment as the API and
Redis. Keep each executor app at `minReplicas=1` so an approved action always
has a live RQ consumer; scale-out can be handled independently with a higher
`maxReplicas`. The executor apps should have no public ingress and receive
only these non-secret settings through Container App
configuration:

```text
REDIS_URL=redis://<private-redis-host>:6379/0
CONTROL_PLANE_URL=http://<internal-api-app-name>:8000
EXECUTOR_SERVICE_KEY=<secret-reference>
EXECUTOR_PROVIDER=azure|aws|github
```

Each app runs only its provider queues:

```text
provider.azure.read provider.azure.write
provider.aws.read provider.aws.write
provider.github.read provider.github.write
```

The API image must not include `az`, `aws`, or `gh`. Set
`CLI_EXECUTORS_ENABLED=false` and `WRITE_ACTIONS_ENABLED=false` for the first
deployment. After read parity and postcondition tests pass in a development
project, enable `CLI_EXECUTORS_ENABLED=true`; enable writes only after an
explicit development canary and approval review.

The API's public ingress can remain enabled for the browser. The executor
control-plane routes are protected by `X-Executor-Key` and
`X-Executor-Provider`, and should be reachable only through the private
Container Apps environment network. Do not put provider credentials in Redis,
Container App settings, image layers, or action payloads.

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
`executors/common/startup.sh` and an org-aware worker launcher at
`executors/common/entrypoint.py`. Startup verifies the provider CLI before the
RQ worker starts and installs the missing CLI as a runtime fallback. The
normal images already contain pinned CLI versions, so a healthy revision does
not download anything during startup. The startup log includes the org id,
provider, and CLI version; it never logs connection fields or credentials.

## Org-scoped executor pools

CLI queues are isolated per organization:

```text
org.{org_id}.provider.azure.read
org.{org_id}.provider.azure.write
org.{org_id}.provider.aws.read
org.{org_id}.provider.aws.write
org.{org_id}.provider.github.read
org.{org_id}.provider.github.write
```

All projects in an org share that org’s Azure/AWS/GitHub executor pool so
multiple projects can run concurrent CLI jobs. Credentials remain
project-scoped and are claimed per job.

Org admins control capacity from **Organizations → Executors**:

- **On demand** — `minReplicas=0`; wake on enqueue; scale to zero after idle
- **Timed window** — keep warm for the next 6 / 12 / 24 hours
- **Custom schedule** — weekly active windows (hard off outside the schedule)

The API scale controller (APScheduler) polls every ~30s and applies replica
targets. Set these on the API Container App to enable Azure scaling:

```text
ORG_EXECUTOR_SCALE_BACKEND=aca
ACA_RESOURCE_GROUP=<rg>
ACA_ENVIRONMENT=<container-apps-env-name>
ACA_EXECUTOR_IMAGE_PREFIX=eqacrregistrydeveastus001.azurecr.io/devsecops-suite
ACA_EXECUTOR_IMAGE_TAG=<git-sha>
CONTROL_PLANE_INTERNAL_URL=http://<internal-api-app-name>:8000
REDIS_URL=redis://<private-redis-host>:6379/0
EXECUTOR_SERVICE_KEY=<secret-reference>
AZURE_SUBSCRIPTION_ID=<optional>
```

Without `ACA_RESOURCE_GROUP`, the controller uses the local Docker stub
(start/stop known executor containers) so product logic still works in
development.

For local Docker validation, use the application profile. Default org id for
the seeded InfraLens org is `00000000-0000-4000-8000-000000000001`:

```powershell
$env:EXECUTOR_ORG_ID = "00000000-0000-4000-8000-000000000001"
docker compose --profile container-app up --build
```

Inspect provider startup and queue activity with, for example,
`docker logs devsecops-azure-executor`. Do not put provider credentials in the
compose file; the executor retrieves them from the API over the authenticated
internal claim endpoint for each action.

## Per-org executor Container Apps

Deploy one Azure / AWS / GitHub executor app **per organization** in the same
Container Apps environment as the API and Redis. The scale controller can
provision missing apps on first wake when `ACA_ENVIRONMENT` is set. Prefer
`minReplicas=0` for on-demand orgs; raise `maxReplicas` (1–5) during warm
windows for concurrent multi-project load.

Each executor app should have no public ingress and receive only:

```text
REDIS_URL=redis://<private-redis-host>:6379/0
CONTROL_PLANE_URL=http://<internal-api-app-name>:8000
EXECUTOR_SERVICE_KEY=<secret-reference>
EXECUTOR_PROVIDER=azure|aws|github
EXECUTOR_ORG_ID=<organization-uuid>
```

The worker entrypoint builds org queues from `EXECUTOR_ORG_ID` +
`EXECUTOR_PROVIDER`. Claim/event/result routes require matching
`X-Executor-Org-Id` so one org’s executors cannot pick up another org’s jobs.

The API image must not include `az`, `aws`, or `gh`. Set
`CLI_EXECUTORS_ENABLED=false` and `WRITE_ACTIONS_ENABLED=false` for the first
deployment. After read parity and postcondition tests pass in a development
project, enable `CLI_EXECUTORS_ENABLED=true`; enable writes only after an
explicit development canary and approval review.

The API's public ingress can remain enabled for the browser. The executor
control-plane routes are protected by `X-Executor-Key`,
`X-Executor-Provider`, and `X-Executor-Org-Id`, and should be reachable only
through the private Container Apps environment network. Do not put provider
credentials in Redis, Container App settings, image layers, or action
payloads.

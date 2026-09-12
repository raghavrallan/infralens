# EQIP AWS onboarding

Connect an AWS account so chat skills and structured actions can use **live**
Cost Explorer, CloudWatch, Config/Security Hub, and inventory data — the same
paths Azure already had.

## 1. Credentials to store

In **Settings → Connections → AWS**, save an access-key connection for the
project. Required fields:

| Field | Purpose |
| --- | --- |
| `access_key_id` | IAM user or temporary key id |
| `secret_access_key` | Matching secret |
| `region` | Default region for API calls (for example `us-east-1`) |

Optional fields (supported by the AWS connector):

| Field | Purpose |
| --- | --- |
| `session_token` | STS / temporary credentials session token |
| `role_arn` | AssumeRole target after the base key authenticates |
| `external_id` | External id required by the trust policy (when using `role_arn`) |
| `regions` | Comma-separated extra regions to scan (inventory / posture) |

Secrets are stored per project and never returned to the UI (only a masked hint).

Minimum IAM for read skills typically includes Cost Explorer
(`ce:GetCostAndUsage`), CloudWatch metrics/logs, EC2/S3/RDS describe, and
Security Hub / Config list APIs. Write chat actions (S3 bucket create, security
group ingress) need the matching `s3:CreateBucket` /
`ec2:AuthorizeSecurityGroupIngress` permissions when you enable write scope.

## 2. Onboarding cloud step

During project onboarding you can connect **Azure and/or AWS** on the cloud
step (alongside GitHub). Completing onboarding with AWS connected sets
`aws_connected` on the project status; the same connection is what Settings and
chat use afterward.

You can also connect AWS later from Settings without re-running the wizard.

## 3. Chat skills that work after connect

With AWS connected (and write scope only when you intentionally enable it),
these chat skills use **live cloud evidence** — Azure mentions remain valid
examples when Azure is connected; they are no longer Azure-only:

| Skill | What it uses on AWS |
| --- | --- |
| **Posture** (`cloud_posture`) | EC2, SG openness, VPC, ELB, Lambda, S3, RDS, IAM / Security Hub summaries |
| **Cost** (`cost_analyzer`) | Cost Explorer spend for the requested period |
| **Metrics** (`metrics_analyzer`) | CloudWatch metrics for discovered resources |
| **Logs** (`log_analyzer`) | CloudWatch Logs / request-style error evidence when available |

Solution Architect `get_cost_report` also concatenates Azure and AWS when both
are connected.

## 4. Structured chat write helpers

Deterministic chat intents (parallel to Azure resource-group helpers):

- Create an **S3 bucket** → `provider: "aws"`, `executable: "aws"`
- Create / update a **security group ingress rule** → `provider: "aws"`, `executable: "aws"`

These still require write action scope and the usual approval gates.

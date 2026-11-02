"""Long-form wiki pages for every registered skill."""
from __future__ import annotations

from app.skills.wiki_format import wiki_page

CHAT_HOW = [
    "Ask in chat in **Auto** or **Agent** mode. The orchestrator can pick this skill from the catalog.",
    "Force it with `/<skill_name>` (use the slug shown on this page).",
    "Use **Plan** mode to see the planned skill and objective before it runs.",
]

READ_WORKFLOW = [
    *CHAT_HOW,
    "Safe to attach to a **scheduled workflow** — it only reads and diagnoses.",
]

WRITE_HOW = [
    "Ask in chat in **Agent** mode, or force it with `/<skill_name>`.",
    "Use **Plan** mode first when the request would change infrastructure or delivery config.",
    "Not safe for unattended scheduled workflows. Live writes still go through the approval-gated execution control plane.",
]


PAGES: dict[str, str] = {
    "cloud_posture": wiki_page(
        "Cloud Posture",
        "Read-only review of the **connected** Azure subscription, AWS account, "
        "and/or GitHub organisation. It reasons over the live inventory InfraLens "
        "already fetched — you do not paste files.",
        does=[
            "Baselines the live estate: network exposure, data protection, IAM hygiene, tagging, and GitHub repo controls.",
            "Prioritises findings by exploitability (public management ports, open data stores, unprotected default branches).",
            "Recommends concrete fixes without applying them.",
        ],
        when=[
            "`Go through my Azure infrastructure and tell me what to improve.`",
            "`Review my AWS account for security issues.`",
            "`Check my GitHub org for repos missing branch protection.`",
            "Onboarding or inheriting a subscription you have not operated before.",
        ],
        how=READ_WORKFLOW,
        uses=[
            "Project **Settings** connections: Azure (Resource Graph plus storage, NSG, public IP, Key Vault, SQL, VM checks), AWS (identity, EC2, security groups, S3, RDS, IAM), GitHub (repos, visibility, default-branch protection, Dependabot).",
            "Parameter: `objective` — what to review or improve.",
            "Requires at least Reader-class access on the connected cloud account.",
        ],
        output=[
            "A posture summary (one sentence per connected provider).",
            "A findings table: Resource | Provider | Issue | Severity | Recommended change.",
            "An ordered `What I'd change first` list.",
        ],
        safety=[
            "**Read-only.** It never modifies cloud or GitHub state.",
            "It must not invent resources. Missing signals are called out as `check this`, not as confirmed failures.",
            "Typical remediation blast radius: medium (config/code changes if you later apply the advice).",
        ],
        related=[
            "`drift_auditor` — compare live cloud to IaC and pipelines.",
            "`iac_reviewer` — review Terraform/Helm/K8s **source** before apply.",
            "`compliance_mapper` — map the same estate to SOC 2 / ISO / PCI / NIST.",
            "`cost_analyzer` — spend, not security posture.",
        ],
        maps_to="Operating model: *Infrastructure & cloud security*.",
    ),
    "code_reviewer": wiki_page(
        "Code Reviewer",
        "Staff-level review of **real application source** fetched read-only from "
        "the project's mapped GitHub repositories on the environment branch "
        "(dev → develop/development, uat → uat, prod → main).",
        does=[
            "Reviews correctness, performance, readability, security (secrets, injection, unsafe APIs), and test gaps.",
            "Compares the same path across environment branches when asked.",
            "Cites repo, path, and branch on every finding.",
        ],
        when=[
            "`Review my backend code and tell me what to improve.`",
            "`Optimize / refactor this module.`",
            "`Find bugs or code smells in my repo.`",
            "`Compare the dev and uat versions of this file.`",
        ],
        how=READ_WORKFLOW,
        uses=[
            "GitHub connection on the active project, scoped to mapped repositories.",
            "Parameter: `objective` — review, optimize, compare, or explain.",
            "Do not paste source that is already in the connected repos.",
        ],
        output=[
            "A one-line verdict against the objective.",
            "Findings table: Severity | File:line (repo@branch) | Issue | Fix.",
            "Before/after snippets for the top issues, plus a short `What's solid` note.",
        ],
        safety=[
            "**Read-only.** It proposes diffs; it does not commit or open PRs.",
            "It must not invent files that were not fetched.",
            "Typical remediation blast radius: low (code changes you apply in git).",
        ],
        related=[
            "`iac_reviewer` — infrastructure code, not application code.",
            "`pipeline_auditor` — CI/CD YAML, not app logic.",
            "`vuln_triage` — scanner CVEs rather than a human-style review.",
            "`project_analyzer` — map repos and live infra before a deep review.",
        ],
        maps_to="Operating model: *Engineering quality & continuous improvement*.",
    ),
    "compliance_mapper": wiki_page(
        "Compliance Mapper",
        "Maps engineering evidence from connected cloud, GitHub, and CI onto a "
        "named framework (SOC 2, ISO 27001, PCI-DSS, NIST CSF) and shows Met / "
        "Partial / Gap with the artefact still needed.",
        does=[
            "Walks control families for the chosen framework (for example SOC 2 CC6/CC7, ISO Annex A, PCI requirement numbers, NIST CSF functions).",
            "Scores each control Met, Partial, or Gap against real evidence, not slogans.",
            "Distinguishes `unable to verify` (fetch failed / artefact missing) from a confirmed gap.",
        ],
        when=[
            "`Map my controls to SOC 2.`",
            "`Are we ISO 27001 compliant?`",
            "`Find compliance gaps for PCI.`",
            "Preparing an audit pack or a client Improve-phase review.",
        ],
        how=READ_WORKFLOW,
        uses=[
            "Evidence bundle from connected cloud inventory, repo security settings, dependency/CI config — not a pasted control spreadsheet unless you add extra context.",
            "Parameters: `controls` (evidence text) and `framework` (`soc2`, `iso27001`, `pci-dss`, `nist-csf`, `other`).",
        ],
        output=[
            "Coverage summary (Met / Partial / Gap counts and the biggest exposure).",
            "Mapping table: Control ref | Requirement | Status | Evidence | Next step.",
            "Prioritised remediation list.",
        ],
        safety=[
            "**Advisory only** — not a formal audit opinion or certification.",
            "Does not invent control identifiers. If a number is uncertain it describes intent instead.",
            "Typical remediation blast radius: medium (policy, logging, and config work).",
        ],
        related=[
            "`cloud_posture` — technical findings that often become compliance evidence.",
            "`pipeline_auditor` — delivery-chain controls (SAST, signing, approvals).",
            "`policy_generator` — turn a gap into OPA/Kyverno/Conftest.",
            "`report_writer` — executive narrative of the same posture.",
        ],
        maps_to="Operating model: *Risk & compliance visibility*.",
    ),
    "cost_analyzer": wiki_page(
        "Cost Analyzer",
        "FinOps answers from **Azure Cost Management** on the connected "
        "subscription. Live actual cost is fetched read-only — do not paste invoices.",
        does=[
            "Answers period questions (this month, June, last 30 days) with the currency returned by Azure.",
            "Breaks spend down by service and names the top cost drivers.",
            "Suggests right-sizing, idle resources, reservations, and storage tiering **only** for services that appear in the data.",
        ],
        when=[
            "`What's the billing for my subscription this month?`",
            "`How much did I spend on Azure in June?`",
            "`Which service is costing me the most?`",
            "`Compare this month to last month.`",
        ],
        how=READ_WORKFLOW,
        uses=[
            "Azure connection on the active project with a subscription id set.",
            "App registration needs **Cost Management Reader** (or Reader).",
            "Parameter: `objective` — the billing question, including the period if you named one.",
        ],
        output=[
            "Headline total and period.",
            "Table: Service | Cost | Share.",
            "`Where to look first` optimisation ideas. Chat may also plot spend when the orchestrator attaches charts.",
        ],
        safety=[
            "**Read-only.** It never changes SKUs, reservations, or budgets.",
            "Zero or missing charges are stated as such — figures are never invented.",
            "Typical remediation blast radius: low (reversible right-size / schedule changes).",
        ],
        related=[
            "`cloud_posture` — security and reliability of the same estate.",
            "`metrics_analyzer` — CPU/memory utilisation that often explains the bill.",
            "`report_writer` — include FinOps in an exec pack.",
        ],
        maps_to="Operating model: *FinOps & cost management*.",
    ),
    "deployment_manager": wiki_page(
        "Deployment Manager",
        "Builds a **governed rollout plan** (validate → plan → apply → verify → "
        "health-check) with optional canary/blue-green and rollback triggers. "
        "It does not silently deploy production.",
        does=[
            "Turns `deploy / promote / canary` into an ordered release plan grounded in project topology and existing pipelines.",
            "Separates preconditions, approval boundary, apply/promote, postcondition checks, and automatic rollback criteria.",
            "Prefers Terraform for infra and the repo's existing CI/CD for app artefacts.",
        ],
        when=[
            "`Deploy to production.`",
            "`Roll out a canary.`",
            "`Run the full deployment pipeline.`",
            "`Promote this release.`",
        ],
        how=WRITE_HOW,
        uses=[
            "Project topology, connected GitHub pipelines, and any live inventory already in context.",
            "Parameters: `objective` (what and where), optional `strategy` (`all_at_once` | `canary` | `blue_green`), optional `constraints` (SLO, freeze windows, traffic %).",
        ],
        output=[
            "Numbered deployment plan with approval and health-check gates.",
            "Canary slice and rollback triggers when blast radius is high or you asked for canary.",
            "Explicit note that a live deploy has **not** happened until an executor confirms it.",
        ],
        safety=[
            "Action class: **config/code change**. Applying it is **irreversible / high blast** and needs the execution control plane (preflight, approval, postcondition).",
            "Never claims success without executor confirmation.",
            "Not workflow-safe for unattended queues.",
        ],
        related=[
            "`pipeline_generator` — create the CI/CD definition this manager will follow.",
            "`terraform_executor` — infra apply path (init → validate → plan → approval → apply).",
            "`infra_debugger` — when a deploy already failed.",
            "`infrastructure_architect` — design the target topology first.",
        ],
        maps_to="Operating model: *Delivery & supply-chain controls*.",
    ),
    "drift_auditor": wiki_page(
        "Drift Auditor",
        "Compares **live cloud inventory** to **infrastructure code and pipelines** "
        "on the environment branch. Finds cloud-only, code-only, and mismatched config.",
        does=[
            "Builds a drift matrix: in cloud only (undeclared), in code only (not deployed), in both (config match?).",
            "Flags missing guardrails on what is actually running (diagnostics, public exposure, autoscale, hardcoded config).",
            "If the repo has no Terraform/Bicep and ships via Azure DevOps/`az`/Docker, it compares pipelines to live — it does not invent Terraform.",
        ],
        when=[
            "`Understand my infra, then compare it to my Terraform and tell me what's missing.`",
            "`What's running in Azure that isn't in my code?`",
            "`Is my IaC in sync with what's deployed?`",
            "`Compare my environment against my pipelines.`",
        ],
        how=READ_WORKFLOW,
        uses=[
            "Azure connection (live inventory) and GitHub connection (IaC / pipeline YAML on the resolved branch).",
            "Parameter: `objective` — the drift question.",
            "Uses connected subscription and mapped repos; it should not interview you for names already in topology.",
        ],
        output=[
            "One-line verdict on how in-sync code and cloud are.",
            "Drift table: Resource | In cloud | In code | Notes.",
            "Prioritised gaps and a reconciliation plan (import, add to code, or remove) as recommendations only.",
        ],
        safety=[
            "**Read-only.** Reconciliation is advice until you run generator/executor skills.",
            "Typical remediation blast radius: medium.",
        ],
        related=[
            "`project_analyzer` — first map of repos + live topology.",
            "`cloud_posture` — security of live resources, drift aside.",
            "`terraform_generator` — emit HCL to close cloud-only gaps.",
            "`iac_reviewer` — security of the IaC you already have.",
        ],
        maps_to="Operating model: *Infrastructure as code & configuration management*.",
    ),
    "iac_reviewer": wiki_page(
        "IaC Reviewer",
        "Static review of Infrastructure-as-Code (Terraform, CloudFormation, Helm, "
        "Kubernetes) for misconfiguration **before** it reaches the cloud.",
        does=[
            "Checks encryption, network exposure, IAM wildcards, logging, secrets in code, workload hardening, backups/deletion protection.",
            "Rates Critical / High / Medium / Low by exploitability (public unauthenticated or unencrypted sensitive resources are Critical/High).",
            "Returns corrected HCL/YAML snippets for the top issues.",
        ],
        when=[
            "`Review my Terraform.`",
            "`Check this Kubernetes manifest for security issues.`",
            "`Scan my Helm chart.`",
            "PR review or baselining inherited IaC.",
        ],
        how=READ_WORKFLOW,
        uses=[
            "Parameters: `iac_config` (source) and optional `iac_type` (`terraform`, `cloudformation`, `helm`, `kubernetes`, `other`).",
            "When GitHub is connected, the orchestrator can feed repo IaC instead of a paste.",
        ],
        output=[
            "Risk summary naming the most dangerous exposure.",
            "Findings table: Resource | Issue | Severity | CIS/benchmark (if known) | Fix.",
            "Corrected snippets for top issues.",
        ],
        safety=[
            "Does not apply infrastructure. Unshown defaults are labelled as assumptions.",
            "Never invents resources or attributes that are not in the input.",
            "Typical remediation blast radius: medium.",
        ],
        related=[
            "`terraform_generator` — produce new HCL after the review.",
            "`drift_auditor` — live vs declared.",
            "`policy_generator` — encode a finding as admission/pipeline policy.",
            "`cloud_posture` — live environment, not files.",
        ],
        maps_to="Operating model: *Infrastructure & cloud security*.",
    ),
    "incident_analyzer": wiki_page(
        "Incident Analyzer",
        "Staff SRE analysis under pressure: correlate logs, metrics, traces, alerts, "
        "and recent changes into a likely root cause, mitigation, and a blameless post-mortem draft.",
        does=[
            "States impact and blast radius strictly from the signals.",
            "Rebuilds a timeline, then proximate cause vs contributing factors.",
            "Gives a most-probable root cause with confidence, alternates, immediate mitigation, durable fix, and a short post-mortem.",
        ],
        when=[
            "`Help me analyse this incident.`",
            "`What's the root cause of these logs?`",
            "`Why is my service down?`",
            "Writing the post-mortem after the incident is contained.",
        ],
        how=READ_WORKFLOW,
        uses=[
            "Parameters: `signals` (required) and optional `recent_changes` (deploys/config).",
            "When Azure Monitor is connected, `log_analyzer` / `metrics_analyzer` evidence may already be in the thread — paste extra traces if they are not.",
        ],
        output=[
            "Impact, timeline, hypotheses with confidence, mitigation, durable fix, post-mortem draft (summary, timeline, root cause, action items).",
        ],
        safety=[
            "Does not invent log lines or metrics. Circumstantial causes stay labelled with confidence.",
            "Does not run rollbacks itself — it recommends them.",
            "Typical remediation blast radius: medium (rollback / scale / failover you still approve).",
        ],
        related=[
            "`log_analyzer` — HTTP 4xx/5xx counts from Container Apps.",
            "`metrics_analyzer` — CPU/memory time series.",
            "`infra_debugger` — failed Terraform/CLI/pipeline apply, not a user-facing outage.",
            "`report_writer` — later exec summary of incident trend.",
        ],
        maps_to="Operating model: *Observability & response*.",
    ),
    "infra_debugger": wiki_page(
        "Infra Debugger",
        "Diagnoses a **failed** Terraform apply, CLI provisioner, or pipeline deploy "
        "and proposes a minimal fix plus a bounded, approval-gated retry.",
        does=[
            "Restates the failure with the exact error signals.",
            "Names the most likely root cause and alternatives.",
            "Proposes a minimal HCL/CLI/config fix, retry budget (attempts, backoff), and rollback if the retry fails.",
        ],
        when=[
            "`Fix the failed deploy.`",
            "`Why did terraform apply fail?`",
            "`Debug the infrastructure error.`",
            "`Retry after the build failed.`",
        ],
        how=READ_WORKFLOW,
        uses=[
            "Failure evidence already in the thread (executor output, pipeline logs), project topology, and recent deployment outcomes.",
            "Parameters: `objective` (required), optional `error_output`, optional `attempted_change`.",
        ],
        output=[
            "Markdown sections: Root cause, Evidence, Fix, Retry plan, Rollback plan.",
        ],
        safety=[
            "The skill itself is **read/diagnose**. The retry still uses the same approval and rollback controls as the original change.",
            "Never invents credentials or bypasses gates.",
            "Typical remediation blast radius: medium.",
        ],
        related=[
            "`terraform_executor` — the governed init/validate/plan/apply path to retry.",
            "`deployment_manager` — full rollout plan when the failure is a release, not a single CLI error.",
            "`incident_analyzer` — production symptoms without a failed apply log.",
            "`iac_reviewer` — if the HCL itself is unsafe.",
        ],
        maps_to="Operating model: *Observability & response*.",
    ),
    "infrastructure_architect": wiki_page(
        "Infrastructure Architect",
        "Turns a compound cloud request into a **complete, dependency-aware "
        "implementation plan** (Azure, AWS, or GitHub). It does not drop resources "
        "and it does not claim the estate changed.",
        does=[
            "Extracts provider, region, names, resource types, and access level from the current turn and same-chat context.",
            "Orders a dependency graph: subscription / RG / VPC/VNet / repo before children.",
            "Splits every write into preflight, change, and post-write verification.",
        ],
        when=[
            "`Design my Azure infrastructure.`",
            "`Plan a VNet with subnets and network security.`",
            "`Create an infrastructure deployment plan.`",
            "`Review the dependencies in this cloud setup.`",
        ],
        how=READ_WORKFLOW,
        uses=[
            "Parameters: `objective` (required), optional `provider`, optional `constraints` (region, naming, networking, security, rollout).",
            "Uses project topology and values already supplied; it should ask only for genuinely missing required inputs.",
        ],
        output=[
            "Intent and provider scope.",
            "Ordered resources and dependencies.",
            "Per-resource preflight, change, verification, risk, and recovery.",
            "Missing inputs (if any) and an explicit `no change has been executed` note.",
        ],
        safety=[
            "Read/diagnose as a skill. Live writes are converted by the action controller into validated `az` / `aws` / `gh` operations with approval.",
            "Does not invent names, regions, address spaces, images, or subscription IDs.",
            "Typical follow-on change blast radius: medium.",
        ],
        related=[
            "`solution_architect` — product/HLD/ADR agent (T1–T3 rubric), not a resource-level CLI plan.",
            "`terraform_generator` — emit HCL from this plan.",
            "`terraform_executor` — apply after review.",
            "`project_analyzer` — discover what already exists first.",
        ],
        maps_to="Operating model: *Infrastructure & cloud delivery*.",
    ),
    "log_analyzer": wiki_page(
        "Log Analyzer",
        "Answers error and HTTP status questions for **connected Azure Container "
        "Apps** using the Azure Monitor `Requests` metric. Chat plots 4xx/5xx over time.",
        does=[
            "Returns exact counts for the codes and window you named (400s last hour, 500s last 2 hours, today, …).",
            "Breaks traffic into 2xx / 3xx / 4xx / 5xx and calls out notable codes.",
            "Interprets error rate only as far as the samples support.",
        ],
        when=[
            "`How many 400 errors are in my container app logs?`",
            "`Any 500 errors in the last hour?`",
            "`Show me the 4xx and 5xx counts for the last 2 hours.`",
            "`What's the error rate on my container app today?`",
        ],
        how=READ_WORKFLOW,
        uses=[
            "Azure connection, subscription id, **Monitoring Reader** (or Reader).",
            "Parameter: `objective` — include the status code and time window.",
            "Does not require pasted log files.",
        ],
        output=[
            "Headline counts and window.",
            "Table: Resource | 2xx | 3xx | 4xx | 5xx | Total.",
            "`What this means` plus a 4xx/5xx graph in chat.",
        ],
        safety=[
            "**Read-only.** Counts are never invented; a requested code with zero hits is stated as zero.",
            "Typical remediation blast radius: low.",
        ],
        related=[
            "`metrics_analyzer` — CPU/memory utilisation, not HTTP codes.",
            "`incident_analyzer` — narrative RCA when you have traces/alerts too.",
            "`infra_debugger` — deploy/apply failures rather than request errors.",
        ],
        maps_to="Operating model: *Observability & performance*.",
    ),
    "metrics_analyzer": wiki_page(
        "Metrics Analyzer",
        "Performance questions from **Azure Monitor** time series (Container Apps "
        "by default, VMs when asked). Chat renders line/bar graphs for each metric.",
        does=[
            "Reports average, peak, and minimum for every metric present (CPU, memory, …) using the unit Azure returned.",
            "Compares multiple resources when several series are in the payload.",
            "Interprets head-room, saturation, and possible scale events only from the samples.",
        ],
        when=[
            "`Give me the last 24 hour CPU metrics of my container app.`",
            "`What's the CPU utilization of my VM over the last day?`",
            "`Show me a graph of my container app CPU.`",
            "`How busy has my app been this week?`",
        ],
        how=READ_WORKFLOW,
        uses=[
            "Azure connection, subscription id, **Monitoring Reader** (or Reader).",
            "Parameter: `objective` — metric names, resource type, and window.",
            "If you said all/every Container App, it reports every series in the fetch rather than asking you to pick one.",
        ],
        output=[
            "Headline numbers and window.",
            "Per-metric table: Resource | Avg | Peak | Min.",
            "`What this means` plus graphs of the same series.",
        ],
        safety=[
            "**Read-only.** Missing metrics are called out, not dropped silently.",
            "Typical remediation blast radius: low (scale / SKU suggestions).",
        ],
        related=[
            "`log_analyzer` — HTTP error counts.",
            "`cost_analyzer` — whether utilisation matches spend.",
            "`incident_analyzer` — when metrics are one signal among many.",
        ],
        maps_to="Operating model: *Observability & performance*.",
    ),
    "pipeline_auditor": wiki_page(
        "Pipeline Auditor",
        "Audits an existing CI/CD definition (GitHub Actions, GitLab CI, Jenkins, "
        "Azure DevOps) against a DevSecOps supply-chain checklist, with copy-paste fixes.",
        does=[
            "Walks SAST, SCA, secrets/OIDC, image scan, IaC scan, SBOM, signing/provenance, approval gates, tests/coverage, runner/token posture (pinned actions, least privilege).",
            "Cites the exact job/step/line for Pass / Gap / Partial / Unknown.",
            "Rates gaps by exploitability (secret exfil, unsigned prod artefacts, unreviewed prod deploys are at least High).",
        ],
        when=[
            "`Audit my pipeline.`",
            "`Review this GitHub Actions workflow.`",
            "`Is my CI/CD secure?`",
            "`Check my Jenkinsfile.`",
        ],
        how=READ_WORKFLOW,
        uses=[
            "Parameters: `pipeline_config` (YAML/Jenkinsfile) and optional `framework`.",
            "Connected GitHub can supply workflow files so you do not paste them.",
        ],
        output=[
            "2–3 sentence posture summary with the single biggest risk.",
            "Findings table: Control | Status | Severity | Evidence | Recommendation.",
            "`Quick wins` with snippets in the pipeline's own syntax.",
        ],
        safety=[
            "Assess only what is present. Unverifiable controls are `Unknown`, not invented stages.",
            "Typical remediation blast radius: low (pipeline YAML).",
        ],
        related=[
            "`pipeline_generator` — greenfield secure pipeline instead of an audit.",
            "`code_reviewer` — application source.",
            "`vuln_triage` — scanner result dumps.",
            "`deployment_manager` — how a release should be gated at runtime.",
        ],
        maps_to="Operating model: *Source, quality & dependency security*.",
    ),
    "pipeline_generator": wiki_page(
        "Pipeline Generator",
        "Produces a **secure-by-default CI/CD file** for your stack and platform "
        "(GitHub Actions, GitLab CI, Jenkins, Azure DevOps), ready to commit after review.",
        does=[
            "Emits checkout, build, tests + coverage, SAST, SCA, secret scan, image build+scan, SBOM, signing/provenance, production approval, then deploy.",
            "Pins actions/images, prefers OIDC over long-lived keys, least-privilege job tokens.",
            "Adapts scanners to the ecosystem (Semgrep, Trivy, Gitleaks, Syft, Cosign by default) and says when it swapped a tool.",
        ],
        when=[
            "`Generate a secure pipeline.`",
            "`Create a GitHub Actions workflow for my Node app.`",
            "`Build a CI/CD pipeline with security scanning.`",
            "Launching a new capability with guardrails from day one.",
        ],
        how=WRITE_HOW,
        uses=[
            "Parameters: `stack` and `platform` required; optional `deploy_target` and `requirements`.",
            "Existing repo/topology in context is used so the file matches the real language and deploy target.",
        ],
        output=[
            "Short explanation of stage flow and security decisions.",
            "One complete pipeline file in a single code block.",
            "`What to configure` checklist: secrets, registry, OIDC, protected environments.",
        ],
        safety=[
            "Action class: **config/code change**. It does not push the workflow for you.",
            "Not workflow-safe (would generate new pipelines unattended).",
            "Typical remediation blast radius: medium.",
        ],
        related=[
            "`pipeline_auditor` — review what you already have.",
            "`deployment_manager` — operate the rollout this pipeline implements.",
            "`policy_generator` — extra admission/policy checks beside CI.",
        ],
        maps_to="Operating model: *Delivery & supply-chain controls*.",
    ),
    "policy_generator": wiki_page(
        "Policy Generator",
        "Turns a plain-English guardrail into **policy-as-code** (OPA/Rego, Kyverno, "
        "or Conftest) with pass and fail tests.",
        does=[
            "Restates the rule, the trigger, and the field it inspects.",
            "Writes deny-by-default, fail-closed policy with a human-readable denial message.",
            "Handles missing fields and trivial evasion; includes at least one PASS and one FAIL example.",
        ],
        when=[
            "`Write an OPA policy that blocks root containers.`",
            "`Create a Kyverno policy for image tags.`",
            "`Generate policy as code for S3 encryption.`",
            "Codifying a standard from a posture or IaC finding.",
        ],
        how=WRITE_HOW,
        uses=[
            "Parameters: `requirement` (required) and optional `engine` (`opa-rego`, `kyverno`, `conftest`). Default engine is OPA/Rego.",
        ],
        output=[
            "Complete policy in one code block.",
            "Where to enforce it (pipeline, admission controller, pre-commit).",
            "PASS/FAIL test inputs (Rego `test_` rules when applicable).",
        ],
        safety=[
            "Does not install the policy into the cluster or CI.",
            "Will not silently broaden or narrow the stated intent; ambiguous cases use the safest interpretation and say so.",
            "Typical remediation blast radius: medium.",
        ],
        related=[
            "`iac_reviewer` / `cloud_posture` — findings that often become policies.",
            "`pipeline_generator` — run Conftest/OPA in CI.",
            "`compliance_mapper` — map the new control back to a framework.",
        ],
        maps_to="Operating model: *Infrastructure & cloud security* (policy-as-code / quality gates).",
    ),
    "project_analyzer": wiki_page(
        "Project Analyzer",
        "Discovery pass over an **existing** project: backend/frontend repos, IaC, "
        "CI/CD, environment branches, and live cloud topology. Use it so later skills "
        "do not treat the estate as empty.",
        does=[
            "Confirms project mode is existing (not greenfield).",
            "Maps repositories (BE/FE/infra) and frameworks when evident.",
            "Inventories IaC, environments/branches, live topology, then gaps/drift/risks and recommended next skills.",
        ],
        when=[
            "`Analyze my project.`",
            "`What do we already have in GitHub and Azure?`",
            "`Map the existing infrastructure and repos.`",
            "`Understand this codebase and infra.`",
        ],
        how=READ_WORKFLOW,
        uses=[
            "PROJECT TOPOLOGY, live inventory, and repository evidence already fetched for the active project.",
            "Parameters: `objective` (required) and optional `focus` (`repos` | `iac` | `live_infra` | `pipelines` | `all`).",
            "Do not paste files that are already in context.",
        ],
        output=[
            "Concrete citations: repo paths, resource types, environments.",
            "Recommended next actions (generate TF, fix drift, deploy, debug) — not a fake empty-estate design.",
        ],
        safety=[
            "**Read-only** discovery. Typical follow-on blast radius: low until you run a write skill.",
        ],
        related=[
            "`drift_auditor` — detailed cloud vs code matrix.",
            "`solution_architect` — HLD/ADR when the ask is architectural, not inventory.",
            "`infrastructure_architect` — ordered resource plan after you know what exists.",
            "`code_reviewer` — deep dive on application source.",
        ],
        maps_to="Operating model: *Infrastructure & cloud delivery*.",
    ),
    "report_writer": wiki_page(
        "Report Writer",
        "Turns DORA, SLA, vulnerability, cost, and incident metrics into a "
        "**board-readable** monthly or quarterly narrative.",
        does=[
            "Leads with outcomes and trends, then supporting numbers.",
            "Benchmarks only against targets you provided (or DORA bands when a target exists).",
            "Balanced: wins and regressions, each risk tied to a next step.",
        ],
        when=[
            "`Write a monthly service report.`",
            "`Summarise these DORA metrics for execs.`",
            "`Create a quarterly review from this data.`",
        ],
        how=READ_WORKFLOW,
        uses=[
            "Parameters: `metrics` (required), optional `period`, optional `audience` (CTO, client execs, …).",
            "Can consume prior skill output in the same chat (cost, vulns, incidents) as the metrics blob.",
        ],
        output=[
            "Executive summary, release confidence, service resilience, risk & compliance, cost/FinOps, next-period priorities.",
            "Missing sections are `not reported this period` — figures are not invented.",
        ],
        safety=[
            "Read-only writing. Does not change production.",
            "Typical blast radius: low.",
        ],
        related=[
            "`cost_analyzer`, `vuln_triage`, `incident_analyzer`, `metrics_analyzer` — typical evidence sources.",
            "`compliance_mapper` — audit-oriented detail behind the risk section.",
        ],
        maps_to="Operating model: *Executive transparency*.",
    ),
    "solution_architect": wiki_page(
        "Solution Architect",
        "The **agentic** architect. It sizes the ticket (T1–T3), explores connected "
        "providers, designs against a quality-attribute rubric, critiques with the "
        "Risk Engine, senior-verifies, then hands off an HLD, Mermaid, and ADRs. "
        "ADRs land as gated findings in the existing Approvals inbox — there is no "
        "second approval product.",
        does=[
            "Runs a graph: clarify → explore → design → critique → senior verify → finalize (recursion cap 12).",
            "T1 stays thin; T2/T3 gather cost, code, precedent, optional PCI mapping, and an LLD via `infrastructure_architect`.",
            "May pause for a clarifying question on T2/T3 in Agent mode (`awaiting_input`). Plan mode records the question as an assumption instead.",
            "Records architecture decisions with risk class and blast radius using the same finding/approval path as other skills.",
        ],
        when=[
            "`Design the architecture for adding a job queue to my API.`",
            "`Solution architect a multi-region order platform.`",
            "`Write an ADR for moving session state off the app box.`",
            "Delivery **Architecture** stage / Dashboard Architecture panel — not a one-line chat answer.",
        ],
        how=[
            "Force it with `/solution_architect` in **Agent** or **Plan** mode. It is **not** in the Auto catalog and is **not auto-routable**.",
            "Requires the `run_architecture` capability (DevOps Lead and above).",
            "**Cannot** be attached to a scheduled workflow (interruptible, not headless).",
            "Delivery runs enqueue an architecture job (RQ, with in-process fallback).",
        ],
        uses=[
            "Azure OpenAI (platform Settings), plus whatever Azure/AWS/GitHub connections exist on the project for exploration.",
            "Parameters: `objective` (required), optional `constraints` (compliance, region, team, budget).",
            "Internal tools may call `cloud_posture` inventory, `cost_analyzer`, `compliance_mapper`, `drift_auditor`, and `infrastructure_architect` — you do not invoke those yourself for a normal architect run.",
        ],
        output=[
            "Clarified objective, tier (T1/T2/T3), greenfield vs brownfield mode.",
            "HLD outline, Mermaid diagram, candidate ADRs (options considered, consequences, risk class).",
            "Dashboard Architecture panel + `GET /api/architecture/runs` for persisted runs.",
            "Streamed status events (`Clarifying the ask`, `Exploring the environment`, …).",
        ],
        safety=[
            "Design-only. It must not claim infrastructure was changed.",
            "Not workflow-safe. Not Auto-routed, so it will not hijack a metrics or billing question.",
            "Clarifying interrupts persist as `ArchitectureRun.status=awaiting_input` (not a live LangGraph `interrupt()`).",
        ],
        related=[
            "`infrastructure_architect` — resource-level LLD / CLI-shaped plan (used inside T2/T3 design).",
            "`terraform_generator` / `terraform_executor` — implement after ADRs are accepted.",
            "`project_analyzer` — inventory-only discovery without the rubric/ADR graph.",
            "`deployment_manager` — rollout of what the architecture decided.",
        ],
        maps_to="Operating model: *Infrastructure & cloud delivery* (architecture stage).",
        extra=(
            "### Graph stages\n\n"
            "1. **Clarify** — objective, constraints, tier, optional question.\n"
            "2. **Explore** — live inventory; T2/T3 add cost, code, precedent, compliance, drift.\n"
            "3. **Design** — rubric + optional LLD; Mermaid HLD.\n"
            "4. **Critique** — Risk Engine / concern areas.\n"
            "5. **Senior verify** — challenge unjustified ADRs.\n"
            "6. **Finalize** — proposal text, findings, dashboard payload."
        ),
    ),
    "terraform_executor": wiki_page(
        "Terraform Executor",
        "Describes and drives Terraform through the **governed** path: init → "
        "validate → plan → **human approval** → apply. It never bypasses the "
        "execution control plane.",
        does=[
            "Translates `plan` / `apply` / `destroy` into a phase sequence for `terraform_runner`.",
            "Summarises expected adds/changes/destroys when a plan is in context.",
            "Requires a machine-executable rollback on every write (targeted destroy or restore previous state).",
        ],
        when=[
            "`Run terraform plan.`",
            "`Apply the terraform.`",
            "`Execute terraform apply.`",
            "`Provision with terraform.`",
        ],
        how=WRITE_HOW,
        uses=[
            "Project topology and HCL already in context (often from `terraform_generator`). If HCL is missing, this skill tells you to generate it first.",
            "Parameters: `objective` (required), optional `workspace`, optional `phase` (`init` | `validate` | `plan` | `apply` | `destroy`).",
        ],
        output=[
            "Phase sequence, workspace/provider assumptions, plan summary, risk, blast radius, rollback, and the next approval-gated action.",
        ],
        safety=[
            "Never claims `apply` succeeded without an executor result.",
            "Action class: **config/code change**; applying/destroying is **irreversible / high blast**.",
            "Not workflow-safe.",
        ],
        related=[
            "`terraform_generator` — produce HCL before execute.",
            "`infra_debugger` — when apply already failed.",
            "`infrastructure_architect` — ordered resource plan if you are not TF-first.",
            "`deployment_manager` — app+infra release, not a single Terraform workspace.",
        ],
        maps_to="Operating model: *Infrastructure & cloud delivery*.",
    ),
    "terraform_generator": wiki_page(
        "Terraform Generator",
        "Writes **production-grade Terraform** (providers, backend, variables, main, "
        "outputs, optional modules) for Azure or AWS from the request and existing topology. "
        "It does not apply.",
        does=[
            "Detects fresh vs existing project and extends discovered modules/state instead of duplicating resources.",
            "Prefers reusable modules, explicit dependencies, tagging, least-privilege identity, private networking defaults, remote-state placeholders.",
            "For deletes/updates, calls out blast radius and rollback (previous state / targeted destroy / recreate).",
        ],
        when=[
            "`Generate terraform.`",
            "`Create terraform for my infra.`",
            "`Write TF code for a VNet and AKS.`",
            "`Produce infrastructure as code.`",
        ],
        how=WRITE_HOW,
        uses=[
            "Parameters: `objective` (required), optional `provider` (`azure` / `aws`), `constraints`, `existing_state`.",
            "Uses PROJECT TOPOLOGY and live inventory. Does not invent subscription IDs, account IDs, regions, CIDRs, or names you did not supply or establish.",
        ],
        output=[
            "Intent, file tree, full HCL in fenced blocks with filenames (`providers.tf`, `backend.tf`, `variables.tf`, `main.tf`, `outputs.tf`, modules).",
            "Variables still required from you.",
            "Suggested next step: init → validate → plan → apply via `terraform_executor`. Nothing has been applied.",
        ],
        safety=[
            "Action class: **config/code change**. HCL is a proposal until executor + approval.",
            "Not workflow-safe.",
            "Typical blast radius: medium (high once applied).",
        ],
        related=[
            "`iac_reviewer` — scan the generated HCL.",
            "`terraform_executor` — plan/apply.",
            "`drift_auditor` — if you are generating to close cloud-only resources.",
            "`infrastructure_architect` — dependency plan before HCL.",
        ],
        maps_to="Operating model: *Infrastructure & cloud delivery*.",
    ),
    "vuln_triage": wiki_page(
        "Vuln Triage",
        "Cuts multi-scanner noise (Snyk, Trivy, Checkmarx, Prisma, lockfiles, SBOMs) "
        "into a **deduplicated, reachability-aware** action list. Output is structured JSON.",
        does=[
            "Normalises the same CVE from multiple tools into one finding.",
            "Weighs reachability and exploitability (internet-facing, KEV/EPSS-style reasoning) over raw CVSS.",
            "Prioritises fix now / this sprint / backlog / accept with an exact upgrade or compensating control.",
        ],
        when=[
            "`Triage these vulnerabilities.`",
            "`Prioritise my Snyk findings.`",
            "`Help me deduplicate scan results.`",
            "Daily Operate-phase vuln queue.",
        ],
        how=READ_WORKFLOW,
        uses=[
            "Parameters: `findings` (required) and optional `context` (internet-facing components, actually-used deps).",
            "When GitHub/cloud are connected, the orchestrator may assemble scanner reports, manifests, lockfiles, SBOMs, and workflow security settings — do not paste if that bundle is present.",
        ],
        output=[
            "JSON: `{ summary, highest_priority, findings: [{ cve_id, title, affected_component, sources, reachable, exploitable, priority, fix_action, reasoning }] }`.",
            "If there are no CVE-level results, `findings` is `[]` with an explanation of coverage — not a fabricated CVE list.",
        ],
        safety=[
            "Never invents CVEs, versions, or exploit status. Fetch failures are coverage limits, not findings.",
            "Typical remediation blast radius: medium (dependency bumps / config).",
        ],
        related=[
            "`pipeline_auditor` — whether scanners even run in CI.",
            "`code_reviewer` — code bugs that are not CVEs.",
            "`compliance_mapper` — vuln management as a control.",
            "`report_writer` — exec view of remediation trend.",
        ],
        maps_to="Operating model: *Observability & response*.",
    ),
}


def apply_wiki(skills: list) -> None:
    """Attach generated wiki Markdown onto registered skill instances."""
    for skill in skills:
        page = PAGES.get(getattr(skill, "name", ""))
        if page:
            skill.wiki = page.replace("/<skill_name>", f"/{skill.name}")

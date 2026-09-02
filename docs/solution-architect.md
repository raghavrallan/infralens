# Solution Architect workflow

How InfraLens turns a project into a structured architecture and executable delivery tasks.

## Pipeline

```text
Clarify → Explore (inventory + repo + discovery)
        → Design (candidates + mermaid + HLD)
        → Critique (gates + precedent)
        → Verify (ADRs + plan steps)
        → Finalize (architecture model + delivery tasks)
```

The graph lives in `app/agents/solution_architect/graph.py`. It is a sequential Python pipeline (not a remote LangGraph service). Delivery runs it as an RQ job (`generate_architecture`) with an in-process fallback if enqueue fails.

## Discovery

`discovery.discover()` is deterministic. It reads Azure/AWS/GitHub inventory text, mapped-repo file names, the ingested objective, and seed memory. Token matching uses word boundaries for short cloud names so phrases like “always” do not become AWS.

Signals drive the structured model: languages, frameworks, Postgres, Redis, workers, Container Apps, Terraform, GitHub Actions.

## Architecture model

`model.build_architecture()` persists on the architecture run checkpoint and on the delivery `architecture_proposal`:

- cloud, mode, tier, stack
- components (purpose, provider, service, artifacts, dependencies, security/cost/scale notes)
- analysis (security, cost, scaling, availability, brownfield vs greenfield)
- mermaid context diagram
- IaC strategy (Terraform via PR; Lead+ gated apply)

Delivery tasks are created from those components, not from keyword guessing, when the model is present.

## IaC generation

`POST /api/engineering/tasks/{id}/generate` writes architecture-aware files from `app/platform/engineering/iac_generate.py`:

- Azure: `providers.tf`, `backend.tf`, network, database, cache, secrets, IAM, monitoring, compute (Container Apps)
- CI workflow and a smoke test
- `architecture.md` from the model

`null_resource`-only stubs fail validation. Companion `.tf` fragments (no `provider` block) use a static check. `backend.tf` is validated as a backend companion. Full files run `terraform init -backend=false` then `terraform validate` when the binary is available.

Apply is never automatic. The apply stage stays Lead-gated and is not executed by the agent.

## Isolated IaC → GitHub → apply

Generated files are written to a **per-project, per-delivery-run** workspace
(`.terraform-workspaces/{project_id}/{run_id}`). Generate also syncs that workspace.

**Push IaC to GitHub** uses *this project's* GitHub token only and only the
mapped repository. Files land on `infralens/iac/{project}/{run}` under
`infra/infralens/{project_id}/` so application source is not overwritten. A PR
is opened against the default branch.

**Run isolated plan / Apply** injects this project's Azure (or AWS) credentials
and strips host `ARM_*` / `AWS_*` from the environment. Apply requires Lead+,
a successful plan in that workspace, and an extra confirm if the plan destroys
resources. Terraform state stays in the isolated workspace (not pushed).

## Observability

While architecture is generating, the job writes `architecture_progress` (clarify / explore / design / …). The delivery checklist polls and shows that text. Architecture runs stay in Postgres so a refresh does not lose the proposal.

Agent tools are read-only adapters (`tools.py`) with an allow-list for nested skills. The architect cannot apply infrastructure.

## UI

- Delivery checklist: stack, component diagram, security/cost notes, mermaid source, retry on failure
- Dashboard Architecture cards: same model from `GET` architect runs

## Local run

1. Configure platform Azure OpenAI in Settings (required; the graph fails closed if missing).
2. Connect Azure and GitHub on the project for brownfield inventory and repo discovery.
3. Start delivery → ingest requirements → generate architecture → accept (Lead+) → Generate artifact on each task → validate → advance stages.

Do not terraform apply against a live subscription from this workflow unless a human explicitly approves a real plan.

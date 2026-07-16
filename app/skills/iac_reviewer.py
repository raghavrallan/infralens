"""Skill: review Infrastructure-as-Code for security misconfigurations."""
from app.skills.base import Skill


class IaCReviewerSkill(Skill):
    name = "iac_reviewer"
    category = "Infrastructure & cloud security"
    description = (
        "Review Infrastructure-as-Code (Terraform, CloudFormation, Helm, "
        "Kubernetes manifests) for security misconfigurations and drift risk, "
        "with concrete fixes."
    )
    triggers = [
        "review my terraform",
        "check this kubernetes manifest for security issues",
        "scan my helm chart",
    ]
    parameters = {
        "type": "object",
        "properties": {
            "iac_config": {
                "type": "string",
                "description": "The IaC source to review.",
            },
            "iac_type": {
                "type": "string",
                "description": "The kind of IaC provided.",
                "enum": [
                    "terraform",
                    "cloudformation",
                    "helm",
                    "kubernetes",
                    "other",
                ],
            },
        },
        "required": ["iac_config"],
    }
    wiki = (
        "## IaC Reviewer\n\n"
        "Reads Infrastructure-as-Code and flags security misconfigurations "
        "before they reach the cloud.\n\n"
        "### When to use it\n"
        "- Reviewing Terraform/Helm/K8s changes in a pull request.\n"
        "- Baselining an inherited estate during transition.\n\n"
        "### What to give it\n"
        "- The IaC source (Terraform, CloudFormation, Helm, or Kubernetes "
        "manifests) and optionally its type.\n\n"
        "### What you get back\n"
        "A risk summary and a findings table (resource, issue, severity, fix) "
        "covering encryption, network exposure, IAM least-privilege, logging, "
        "secrets handling and pod/container security, with corrected snippets "
        "for the top issues. It never invents resources not in your input.\n\n"
        "### Maps to\n"
        "Operating model control point: *Infrastructure & cloud security*."
    )
    system_prompt = (
        "You are a principal cloud security architect reviewing "
        "Infrastructure-as-Code. You think in terms of attacker reachability, "
        "blast radius and the CIS Benchmarks / cloud Well-Architected security "
        "pillar, and you only assert what the code actually declares.\n\n"
        "METHOD — inspect every resource and evaluate:\n"
        "1. Encryption at rest (KMS/CMEK) and in transit (TLS) — flag "
        "unencrypted stores and permissive TLS.\n"
        "2. Network exposure — public ingress (0.0.0.0/0), open security "
        "groups/NSGs, public IPs, public buckets/blobs.\n"
        "3. Identity — IAM least-privilege; flag wildcard actions/resources, "
        "privilege escalation paths, overly broad trust policies.\n"
        "4. Auditing/observability — logging, flow logs, audit trails enabled "
        "and retained.\n"
        "5. Secrets — no plaintext secrets in code/variables/user-data; managed "
        "secret stores used.\n"
        "6. Workload hardening (K8s/containers) — non-root, no privileged, "
        "readonly root FS, dropped capabilities, resource limits, pinned image "
        "digests, network policies.\n"
        "7. Data protection — backups, deletion protection, versioning where "
        "appropriate.\n\n"
        "SEVERITY — Critical / High / Medium / Low based on exploitability and "
        "exposure. A publicly reachable, unauthenticated, or unencrypted "
        "sensitive resource is Critical/High.\n\n"
        "OUTPUT (Markdown):\n"
        "- A risk summary naming the most dangerous exposure.\n"
        "- A findings table: Resource (address) | Issue | Severity | CIS/benchmark "
        "reference (if known) | Fix.\n"
        "- Corrected HCL/YAML snippets for the top issues.\n\n"
        "GUARDRAILS — never invent resources, attributes or defaults not shown. "
        "If a risk depends on an unshown default, state the assumption "
        "explicitly and how to confirm it."
    )


skill = IaCReviewerSkill()

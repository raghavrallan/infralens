"""Skill: generate a secure CI/CD pipeline tailored to a stack."""
from app.skills.base import Skill


class PipelineGeneratorSkill(Skill):
    name = "pipeline_generator"
    category = "Delivery & supply-chain controls"
    description = (
        "Generate a secure CI/CD pipeline (with SAST, SCA, image scanning, "
        "SBOM, signing and approval gates) tailored to a given language, "
        "framework, platform and deployment target."
    )
    triggers = [
        "generate a secure pipeline",
        "create a github actions workflow for my node app",
        "build a ci/cd pipeline with security scanning",
    ]
    parameters = {
        "type": "object",
        "properties": {
            "stack": {
                "type": "string",
                "description": "Language/framework, e.g. 'Node.js + Express'.",
            },
            "platform": {
                "type": "string",
                "description": "CI platform to target.",
                "enum": [
                    "github-actions",
                    "gitlab-ci",
                    "jenkins",
                    "azure-devops",
                ],
            },
            "deploy_target": {
                "type": "string",
                "description": "Deployment target, e.g. 'AWS EKS', 'Azure AKS'.",
            },
            "requirements": {
                "type": "string",
                "description": "Any extra requirements or constraints.",
            },
        },
        "required": ["stack", "platform"],
    }
    wiki = (
        "## Pipeline Generator\n\n"
        "Produces a secure, production-ready CI/CD pipeline from scratch, "
        "tailored to your stack, CI platform and deployment target.\n\n"
        "### When to use it\n"
        "- *Launch new capability* engagements where you build guardrails from "
        "day one.\n"
        "- Standardising a secure pipeline template across many repos.\n\n"
        "### What to give it\n"
        "- Your stack (e.g. 'Node.js + Express'), the CI platform, and ideally "
        "the deploy target (e.g. 'AWS EKS') plus any constraints.\n\n"
        "### What you get back\n"
        "A ready-to-commit pipeline file with build, tests + coverage gate, "
        "SAST, SCA, secret scan, image build + scan, SBOM, signing/provenance "
        "and a production approval gate, followed by a 'what to configure' "
        "checklist for secrets, registries and OIDC.\n\n"
        "### Maps to\n"
        "Operating model control point: *Delivery & supply-chain controls*."
    )
    system_prompt = (
        "You are a principal DevSecOps automation engineer. You generate secure "
        "CI/CD pipelines that are correct on first run, secure by default, and "
        "idiomatic for the target platform — the kind a senior reviewer would "
        "approve without changes.\n\n"
        "REQUIRED STAGES, ordered as a real supply chain, each fail-closed:\n"
        "1. Checkout with least-privilege token scope.\n"
        "2. Build / compile.\n"
        "3. Unit tests with an enforced coverage threshold.\n"
        "4. SAST (default Semgrep) — fail on high severity.\n"
        "5. SCA / dependency scan (default Trivy or the ecosystem-native tool) "
        "with a severity budget.\n"
        "6. Secret scanning (default Gitleaks).\n"
        "7. Container image build, then image scan (default Trivy) before push.\n"
        "8. SBOM generation (default Syft, SPDX or CycloneDX).\n"
        "9. Artifact signing + provenance/attestation (default Cosign, keyless "
        "via OIDC).\n"
        "10. Manual approval gate / protected environment before production.\n"
        "11. Deploy to the requested target.\n\n"
        "SECURITY DEFAULTS — pin every action and base image by version or "
        "digest; use OIDC-federated short-lived cloud credentials instead of "
        "long-lived keys; grant the minimum token permissions per job; cache "
        "safely; never echo secrets. Adapt tool choices to the stack when an "
        "ecosystem-native scanner is clearly better, and say why.\n\n"
        "OUTPUT (Markdown):\n"
        "- A short paragraph explaining the stage flow and the key security "
        "decisions.\n"
        "- The complete pipeline file in ONE code block, valid for the target "
        "platform's syntax, ready to commit.\n"
        "- A 'What to configure' checklist: required secrets/variables, "
        "registry and OIDC/identity setup, and any protected-environment steps "
        "the user must create in the platform UI."
    )


skill = PipelineGeneratorSkill()

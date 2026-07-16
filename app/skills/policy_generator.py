"""Skill: generate policy-as-code from natural language requirements."""
from app.skills.base import Skill


class PolicyGeneratorSkill(Skill):
    name = "policy_generator"
    category = "Infrastructure & cloud security"
    description = (
        "Generate policy-as-code (OPA/Rego, Kyverno, or Conftest) from a "
        "natural-language guardrail requirement, with test cases."
    )
    triggers = [
        "write an opa policy that blocks root containers",
        "create a kyverno policy for image tags",
        "generate policy as code for s3 encryption",
    ]
    parameters = {
        "type": "object",
        "properties": {
            "requirement": {
                "type": "string",
                "description": "The guardrail in plain English.",
            },
            "engine": {
                "type": "string",
                "description": "Policy engine to target.",
                "enum": ["opa-rego", "kyverno", "conftest"],
            },
        },
        "required": ["requirement"],
    }
    wiki = (
        "## Policy Generator\n\n"
        "Turns a plain-English guardrail into working policy-as-code with tests, "
        "so you can enforce standards in the pipeline or admission controller.\n\n"
        "### When to use it\n"
        "- Codifying a new security standard (e.g. 'no root containers').\n"
        "- Building a policy library during the *Transform* phase.\n\n"
        "### What to give it\n"
        "- The rule in natural language and, optionally, the target engine "
        "(OPA/Rego, Kyverno, or Conftest).\n\n"
        "### What you get back\n"
        "A commented policy file, an explanation of how it evaluates, and both "
        "a passing and a failing example input so you can wire it into tests "
        "immediately. Rules default to deny where appropriate.\n\n"
        "### Maps to\n"
        "Operating model control point: *Infrastructure & cloud security* "
        "(policy-as-code / quality gates)."
    )
    system_prompt = (
        "You are a policy-as-code specialist who writes production-grade, "
        "test-backed guardrails. You translate intent into precise, "
        "deny-by-default rules that are safe against bypass and clear to "
        "reviewers.\n\n"
        "METHOD:\n"
        "1. Restate the guardrail as an explicit rule with its trigger "
        "conditions and the exact resource/field it inspects.\n"
        "2. Choose the engine (default OPA/Rego if unspecified) and write "
        "idiomatic, well-structured policy with meaningful rule names and a "
        "clear, human-readable denial message that tells the user how to fix "
        "the violation.\n"
        "3. Handle edge cases: missing/renamed fields, list vs single values, "
        "and default-deny so an unexpected shape fails closed rather than open.\n"
        "4. Consider evasion — do not let trivial reformatting bypass the rule.\n\n"
        "OUTPUT (Markdown):\n"
        "- The complete policy in one code block for the chosen engine.\n"
        "- A short explanation of how it evaluates and where to enforce it "
        "(pipeline step, admission controller, or pre-commit).\n"
        "- Test cases: at least one PASS and one FAIL input (in the engine's "
        "test format where one exists, e.g. Rego `test_` rules), showing the "
        "expected decision.\n\n"
        "GUARDRAILS — keep the rule scoped to the stated intent; do not silently "
        "broaden or narrow it. If the requirement is ambiguous, encode the "
        "safest reasonable interpretation and note the assumption."
    )


skill = PolicyGeneratorSkill()

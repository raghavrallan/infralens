"""Skill: review, optimize and compare application source code from GitHub."""
from app.skills.base import Skill


class CodeReviewerSkill(Skill):
    name = "code_reviewer"
    category = "Engineering quality"
    description = (
        "Review, optimize, refactor or compare the user's ACTUAL application "
        "source code, which the suite fetches read-only from their connected "
        "GitHub repos (on the right environment branch). Use this whenever they "
        "ask to 'review my code', 'optimize this', 'refactor', 'find bugs', "
        "'what can be improved', 'compare these files', or ask why a piece of "
        "code behaves a certain way — the real code is provided, so never ask "
        "them to paste it."
    )
    triggers = [
        "review my code and tell me what to improve",
        "optimize the backend code",
        "find bugs or code smells in my repo",
        "compare the dev and uat versions of this file",
    ]
    parameters = {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "description": "The code review / optimization / comparison request.",
            }
        },
        "required": ["objective"],
    }
    wiki = (
        "## Code Reviewer & Optimizer\n\n"
        "Reviews, optimizes and compares your *real* application source, fetched "
        "read-only from your connected GitHub repositories on the correct "
        "environment branch (dev → develop/development, uat → uat, prod → main). "
        "No pasting required.\n\n"
        "### When to use it\n"
        "- 'Review my backend code and tell me what to improve.'\n"
        "- 'Optimize / refactor this module.'\n"
        "- 'Find bugs, security issues or code smells.'\n"
        "- 'Compare how this behaves on dev vs uat.'\n\n"
        "### What it uses\n"
        "The GitHub connection saved in Settings for the active project, scoped to "
        "the repositories mapped to the project. It resolves the environment "
        "branch from your request and reads the relevant source files.\n\n"
        "### What you get back\n"
        "A prioritized review: correctness/bugs, performance, readability, "
        "security, and concrete before/after suggestions that reference the exact "
        "repo, path and branch. It never changes anything.\n\n"
        "### Maps to\n"
        "Operating model control point: *Engineering quality & continuous "
        "improvement*."
    )
    system_prompt = (
        "You are a staff engineer doing a rigorous, read-only code review of a "
        "customer's REAL source code, provided to you below (fetched from their "
        "GitHub on the resolved environment branch). Reason ONLY over the code "
        "provided; always cite the exact repo, path and branch shown. If you need "
        "a file that isn't included, say which one and why — do NOT ask the user "
        "to paste code that is already provided.\n\n"
        "METHOD:\n"
        "- Start from the user's actual objective (optimize, refactor, find bugs, "
        "compare, explain). Address it directly first.\n"
        "- Assess correctness and likely bugs, then performance/efficiency, then "
        "readability/maintainability, then security (secrets, injection, unsafe "
        "calls), then tests/observability gaps.\n"
        "- For comparisons, diff the behaviours and call out what differs and why "
        "it matters.\n"
        "- Prefer high-signal findings over nitpicks; group trivial ones.\n\n"
        "OUTPUT (Markdown):\n"
        "- A one-line verdict answering the objective.\n"
        "- A prioritized findings table: Severity | File:line (repo@branch) | Issue "
        "| Fix.\n"
        "- For the top issues, a short before/after code snippet showing the "
        "improvement.\n"
        "- A brief 'What's solid' note so it's balanced.\n\n"
        "GUARDRAILS — READ-ONLY. Propose diffs and improvements; never claim you "
        "applied them and never output shell/git commands to run unless the user "
        "explicitly asks."
    )


skill = CodeReviewerSkill()

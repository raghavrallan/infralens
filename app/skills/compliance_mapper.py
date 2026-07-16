"""Skill: map controls/evidence to compliance frameworks and find gaps."""
from app.skills.base import Skill


class ComplianceMapperSkill(Skill):
    name = "compliance_mapper"
    category = "Risk & compliance visibility"
    description = (
        "Map an inventory of existing controls/evidence to a compliance "
        "framework (SOC 2, ISO 27001, PCI-DSS, NIST) and highlight gaps."
    )
    triggers = [
        "map my controls to soc2",
        "are we iso 27001 compliant",
        "find compliance gaps for pci",
    ]
    parameters = {
        "type": "object",
        "properties": {
            "controls": {
                "type": "string",
                "description": "Description of current controls and evidence.",
            },
            "framework": {
                "type": "string",
                "description": "Target compliance framework.",
                "enum": ["soc2", "iso27001", "pci-dss", "nist-csf", "other"],
            },
        },
        "required": ["controls", "framework"],
    }
    wiki = (
        "## Compliance Mapper\n\n"
        "Maps your current controls and evidence to a compliance framework and "
        "shows exactly where the gaps are.\n\n"
        "### When to use it\n"
        "- Preparing for a SOC 2 / ISO 27001 / PCI-DSS audit.\n"
        "- Giving a client visibility of compliance posture during *Improve* "
        "reviews.\n\n"
        "### What to give it\n"
        "- A description of your current controls and evidence, and the target "
        "framework.\n\n"
        "### What you get back\n"
        "A coverage summary and a mapping table (control, status of Met / "
        "Partial / Gap, supporting evidence, next step) plus a prioritised "
        "remediation list. It is advisory guidance, not a formal audit "
        "opinion.\n\n"
        "### Maps to\n"
        "Operating model control point: *Risk & compliance visibility*."
    )
    system_prompt = (
        "You are a senior GRC analyst who maps engineering reality to "
        "compliance frameworks and produces audit-ready gap analyses. You are "
        "precise about control references and rigorous about evidence.\n\n"
        "METHOD:\n"
        "1. Identify the relevant control families/criteria of the target "
        "framework (e.g. SOC 2 Trust Services Criteria such as CC6/CC7; ISO "
        "27001 Annex A domains; PCI-DSS requirement numbers; NIST CSF "
        "functions).\n"
        "2. For each, map the described controls/evidence and assign a status: "
        "Met, Partial, or Gap.\n"
        "3. Cite the specific evidence that supports each mapping, and for "
        "Partial/Gap state exactly what is missing and the concrete artefact "
        "needed to close it (policy, log, config, ticket, test result).\n"
        "4. Prioritise remediation by audit risk and effort.\n\n"
        "OUTPUT (Markdown):\n"
        "- A coverage summary (roughly how many criteria are Met/Partial/Gap "
        "and the biggest exposure).\n"
        "- A mapping table: Control ref | Requirement (short) | Status | "
        "Evidence | Gap / Next step.\n"
        "- A prioritised remediation list.\n\n"
        "GUARDRAILS — cite only control references you are confident exist in "
        "the named framework; if unsure of an exact number, describe the "
        "control by its intent instead of inventing an identifier. State "
        "clearly that this is advisory guidance to prepare for audit, not a "
        "formal audit opinion or certification."
    )


skill = ComplianceMapperSkill()

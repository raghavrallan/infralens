"""Action-class taxonomy for every skill.

The DevOps Intelligence Layer gates work by *action class* and *blast radius*,
not by tool. This module records, for each registered skill, the class of action
it represents when run unattended and the class of action its remediation would
be, so the workflow engine can decide what is safe to run in a queue and the
Risk Engine can decide how any resulting change must be gated.
"""
from typing import Literal

ActionClass = Literal[
    "read_diagnose",
    "reversible_change",
    "config_code_change",
    "irreversible_high_blast",
    "safety_direction",
]

BlastRadius = Literal["low", "medium", "high"]

# What a skill DOES when it runs. Only "read_diagnose" skills may run unattended
# inside a scheduled/queued workflow.
SKILL_ACTION_CLASS: dict[str, ActionClass] = {
    "cloud_posture": "read_diagnose",
    "drift_auditor": "read_diagnose",
    "cost_analyzer": "read_diagnose",
    "metrics_analyzer": "read_diagnose",
    "log_analyzer": "read_diagnose",
    "vuln_triage": "read_diagnose",
    "compliance_mapper": "read_diagnose",
    "pipeline_auditor": "read_diagnose",
    "iac_reviewer": "read_diagnose",
    "code_reviewer": "read_diagnose",
    "incident_analyzer": "read_diagnose",
    "report_writer": "read_diagnose",
    "project_analyzer": "read_diagnose",
    "infra_debugger": "read_diagnose",
    "infrastructure_architect": "read_diagnose",
    "terraform_generator": "config_code_change",
    "terraform_executor": "config_code_change",
    "deployment_manager": "config_code_change",
    "pipeline_generator": "config_code_change",
    "policy_generator": "config_code_change",
}

# The class of the change that RESOLVING a finding from this skill would require.
# Used only to classify a finding's recommended action for gating; nothing is
# executed in this milestone.
SKILL_REMEDIATION_CLASS: dict[str, ActionClass] = {
    "cloud_posture": "config_code_change",
    "drift_auditor": "config_code_change",
    "cost_analyzer": "reversible_change",
    "metrics_analyzer": "reversible_change",
    "log_analyzer": "reversible_change",
    "vuln_triage": "config_code_change",
    "compliance_mapper": "config_code_change",
    "pipeline_auditor": "config_code_change",
    "iac_reviewer": "config_code_change",
    "code_reviewer": "config_code_change",
    "incident_analyzer": "reversible_change",
    "report_writer": "read_diagnose",
    "project_analyzer": "read_diagnose",
    "infra_debugger": "config_code_change",
    "infrastructure_architect": "config_code_change",
    "terraform_generator": "config_code_change",
    "terraform_executor": "irreversible_high_blast",
    "deployment_manager": "irreversible_high_blast",
    "pipeline_generator": "config_code_change",
    "policy_generator": "config_code_change",
}

# Baseline blast radius of a skill's typical remediation, before severity bumps.
SKILL_BLAST_RADIUS: dict[str, BlastRadius] = {
    "cloud_posture": "medium",
    "drift_auditor": "medium",
    "cost_analyzer": "low",
    "metrics_analyzer": "low",
    "log_analyzer": "low",
    "vuln_triage": "medium",
    "compliance_mapper": "medium",
    "pipeline_auditor": "low",
    "iac_reviewer": "medium",
    "code_reviewer": "low",
    "incident_analyzer": "medium",
    "report_writer": "low",
    "project_analyzer": "low",
    "infra_debugger": "medium",
    "infrastructure_architect": "medium",
    "terraform_generator": "medium",
    "terraform_executor": "high",
    "deployment_manager": "high",
    "pipeline_generator": "medium",
    "policy_generator": "medium",
}

# Skills that are safe to run autonomously inside a workflow queue.
WORKFLOW_SAFE: frozenset[str] = frozenset(
    name for name, cls in SKILL_ACTION_CLASS.items() if cls == "read_diagnose"
)


def is_workflow_safe(skill_name: str) -> bool:
    """True when a skill only reads/diagnoses and can run unattended."""
    return skill_name in WORKFLOW_SAFE


def action_class_for(skill_name: str) -> ActionClass:
    return SKILL_ACTION_CLASS.get(skill_name, "read_diagnose")


def remediation_class_for(skill_name: str) -> ActionClass:
    return SKILL_REMEDIATION_CLASS.get(skill_name, "config_code_change")


def blast_radius_for(skill_name: str) -> BlastRadius:
    return SKILL_BLAST_RADIUS.get(skill_name, "medium")

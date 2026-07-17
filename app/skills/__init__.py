"""Skill package: import each skill module and register it centrally.

Adding a new skill is a two-step process:
  1. Create app/skills/<your_skill>.py exposing a module-level `skill` instance.
  2. Import it here and register it.
"""
from app.skills.base import SkillResult, registry
from app.skills.cloud_posture import skill as cloud_posture
from app.skills.code_reviewer import skill as code_reviewer
from app.skills.compliance_mapper import skill as compliance_mapper
from app.skills.cost_analyzer import skill as cost_analyzer
from app.skills.drift_auditor import skill as drift_auditor
from app.skills.iac_reviewer import skill as iac_reviewer
from app.skills.incident_analyzer import skill as incident_analyzer
from app.skills.log_analyzer import skill as log_analyzer
from app.skills.metrics_analyzer import skill as metrics_analyzer
from app.skills.pipeline_auditor import skill as pipeline_auditor
from app.skills.pipeline_generator import skill as pipeline_generator
from app.skills.policy_generator import skill as policy_generator
from app.skills.report_writer import skill as report_writer
from app.skills.vuln_triage import skill as vuln_triage

for _skill in (
    pipeline_auditor,
    pipeline_generator,
    iac_reviewer,
    cloud_posture,
    cost_analyzer,
    code_reviewer,
    drift_auditor,
    metrics_analyzer,
    log_analyzer,
    policy_generator,
    vuln_triage,
    compliance_mapper,
    incident_analyzer,
    report_writer,
):
    registry.register(_skill)

__all__ = ["registry", "SkillResult"]

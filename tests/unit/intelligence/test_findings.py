"""Finding fingerprinting, title cleanup, and gated extraction fallbacks."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.intelligence import findings


@pytest.mark.unit
def test_normalize_issue_text_collapses_noise():
    assert findings.normalize_issue_text("  Foo, BAR!!  ") == "foo bar"
    assert findings.normalize_issue_text("") == ""


@pytest.mark.unit
def test_fingerprint_prefers_cve_then_resource_then_title():
    cve = findings.compute_fingerprint("p1", "vuln_triage", "", "Upgrade CVE-2024-1234 now")
    same = findings.compute_fingerprint("p1", "vuln_triage", "other", "see CVE-2024-1234")
    assert cve == same
    by_resource = findings.compute_fingerprint("p1", "iac_reviewer", "rg/app", "title a")
    same_resource = findings.compute_fingerprint("p1", "iac_reviewer", "RG/APP", "title b")
    assert by_resource == same_resource
    by_title = findings.compute_fingerprint("p1", "report_writer", "", "Open S3 bucket")
    other_title = findings.compute_fingerprint("p1", "report_writer", "", "Different")
    assert by_title != other_title


@pytest.mark.unit
def test_clean_title_recovers_json_echo():
    assert findings._clean_title('{"title": "Fix IAM"}') == "Fix IAM"
    assert findings._clean_title("# Heading") == "Heading"
    assert findings._clean_title("{not json")[:1] == "{"


@pytest.mark.unit
def test_severity_helpers():
    assert findings._clean_severity("CRITICAL") == "critical"
    assert findings._clean_severity("nope") == "low"
    assert findings._severity_from_text("this is High risk") == "high"
    assert findings._severity_from_text("all good") == "low"


@pytest.mark.unit
def test_build_findings_empty_output():
    assert findings.build_findings("cloud_posture", "security_patch", "", "obj") == []
    assert findings.build_findings("cloud_posture", "security_patch", "   ", "obj") == []


@pytest.mark.unit
def test_build_findings_uses_fallback_when_extract_fails():
    with patch("app.intelligence.findings._extract_structured", return_value=None):
        rows = findings.build_findings(
            "cloud_posture",
            "security_patch",
            "# Public NSG\nCritical exposure on nsg-1",
            "review posture",
            environment="prod",
        )
    assert len(rows) == 1
    assert rows[0]["skill"] == "cloud_posture"
    assert rows[0]["gate_decision"]
    assert rows[0]["severity"] == "critical"


@pytest.mark.unit
def test_build_findings_from_extracted_list():
    extracted = [
        {
            "title": "Pin actions",
            "severity": "medium",
            "resource": "acme/app",
            "category": "CI",
            "evidence": "unpinned",
            "recommended_action": "pin sha",
        }
    ]
    with patch("app.intelligence.findings._extract_structured", return_value=extracted):
        rows = findings.build_findings(
            "pipeline_auditor", "pipeline_intelligence", "analysis", "audit"
        )
    assert rows[0]["title"] == "Pin actions"
    assert rows[0]["resource"] == "acme/app"


@pytest.mark.unit
def test_extract_structured_parses_model_json():
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content='{"findings":[{"title":"A","severity":"high","resource":"r"}]}'
                )
            )
        ]
    )
    with patch("app.intelligence.findings.azure_client.chat", return_value=completion):
        items = findings._extract_structured("iac_reviewer", "text", "obj")
    assert items is not None
    assert items[0]["title"] == "A"
    assert items[0]["severity"] == "high"


@pytest.mark.unit
def test_extract_structured_returns_none_on_failure():
    with patch("app.intelligence.findings.azure_client.chat", side_effect=RuntimeError):
        assert findings._extract_structured("x", "out", "obj") is None
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="[]"))]
    )
    with patch("app.intelligence.findings.azure_client.chat", return_value=completion):
        assert findings._extract_structured("x", "out", "obj") is None

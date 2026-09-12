"""vuln_triage must render Markdown for chat, not raw JSON blobs."""
from app.skills.vuln_triage import format_vuln_triage_markdown


def test_format_vuln_triage_markdown_from_screenshot_shape() -> None:
    raw = """{
      "summary": "Reviewed the live Azure inventory and found 2 Azure SQL servers with public network access enabled.",
      "highest_priority": "High - fix now / this sprint",
      "findings": [
        {
          "cveid": "N/A",
          "title": "Disable public network access on SQL server",
          "affected_component": "Azure SQL servers: gs-sql-sqlserver-dev-eastus-001",
          "sources": [
            "Azure Resource Graph inventory: SQL servers (publicNetworkAccess=Enabled)"
          ],
          "priority": "High",
          "fix_action": "Set publicNetworkAccess=Disabled after validating private endpoint path",
          "reasoning": "Public SQL exposure increases attack surface."
        }
      ]
    }"""
    md = format_vuln_triage_markdown(raw)
    assert md.strip().startswith("Reviewed the live Azure inventory")
    assert "**Highest priority:** High - fix now / this sprint" in md
    assert "Disable public network access on SQL server" in md
    assert "**Affected:**" in md
    assert "**Evidence:**" in md
    assert '{"summary"' not in md
    assert "publicNetworkAccess=Enabled" in md


def test_format_vuln_triage_passthrough_non_json() -> None:
    text = "## Severity: high\nAlready markdown"
    assert format_vuln_triage_markdown(text) == text


def test_format_vuln_triage_empty_findings() -> None:
    raw = '{"summary": "No CVE scanner results.", "highest_priority": "n/a", "findings": []}'
    md = format_vuln_triage_markdown(raw)
    assert "No CVE scanner results." in md
    assert "No discrete vulnerability findings" in md

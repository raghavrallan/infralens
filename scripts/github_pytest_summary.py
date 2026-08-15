"""Write a GitHub Actions job summary from pytest JUnit and coverage.xml."""
from __future__ import annotations

import argparse
import os
import xml.etree.ElementTree as ET
from pathlib import Path


def _suites(root: ET.Element) -> list[ET.Element]:
    if root.tag == "testsuites":
        return list(root.findall("testsuite"))
    return [root]


def _junit_stats(path: Path) -> tuple[int, int, int, int, list[tuple[str, str]]]:
    root = ET.parse(path).getroot()
    tests = failures = errors = skipped = 0
    cases: list[tuple[str, str]] = []
    for suite in _suites(root):
        tests += int(float(suite.attrib.get("tests") or 0))
        failures += int(float(suite.attrib.get("failures") or 0))
        errors += int(float(suite.attrib.get("errors") or 0))
        skipped += int(float(suite.attrib.get("skipped") or 0))
        for case in suite.findall("testcase"):
            name = f"{case.attrib.get('classname', '')}::{case.attrib.get('name', '')}"
            if case.find("failure") is not None:
                status = "fail"
            elif case.find("error") is not None:
                status = "error"
            elif case.find("skipped") is not None:
                status = "skip"
            else:
                status = "pass"
            cases.append((status, name))
    return tests, failures, errors, skipped, cases


def _coverage(path: Path) -> tuple[float, float, int, int, int, int]:
    root = ET.parse(path).getroot()
    line_rate = float(root.attrib.get("line-rate") or 0) * 100
    branch_rate = float(root.attrib.get("branch-rate") or 0) * 100
    lines_covered = int(float(root.attrib.get("lines-covered") or 0))
    lines_valid = int(float(root.attrib.get("lines-valid") or 0))
    branches_covered = int(float(root.attrib.get("branches-covered") or 0))
    branches_valid = int(float(root.attrib.get("branches-valid") or 0))
    return line_rate, branch_rate, lines_covered, lines_valid, branches_covered, branches_valid


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--junit", required=True)
    parser.add_argument("--coverage")
    parser.add_argument("--note")
    args = parser.parse_args()

    out = Path(os.environ.get("GITHUB_STEP_SUMMARY") or "pytest-summary.md")
    lines = [f"## {args.title}", ""]

    junit = Path(args.junit)
    if junit.exists():
        tests, failures, errors, skipped, cases = _junit_stats(junit)
        passed = tests - failures - errors - skipped
        lines += [
            f"- **{passed} passed**, {failures} failed, {errors} errors, "
            f"{skipped} skipped (**{tests} total**)",
            "",
        ]
    else:
        cases = []
        lines += [f"- JUnit report not found: `{junit}`", ""]

    if args.coverage:
        cov = Path(args.coverage)
        if cov.exists():
            line_rate, branch_rate, lc, lv, bc, bv = _coverage(cov)
            lines += [
                f"- **Line coverage:** {line_rate:.2f}% ({lc}/{lv})",
                f"- **Branch coverage:** {branch_rate:.2f}% ({bc}/{bv})",
                "",
            ]
        else:
            lines += [f"- Coverage report not found: `{cov}`", ""]

    if args.note:
        lines += [f"> {args.note}", ""]

    if cases:
        lines += ["### Test cases", "", "| Result | Test |", "| --- | --- |"]
        for status, name in cases:
            lines.append(f"| {status} | `{name}` |")
        lines.append("")

    existing = out.read_text(encoding="utf-8") if out.exists() else ""
    out.write_text(existing + "\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()

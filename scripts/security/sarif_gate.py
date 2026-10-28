"""Fail-closed SARIF policy adapted from Padel. No source snippets exported."""
import json
from pathlib import Path
import sys


def evaluate(report):
    if report.get("version") != "2.1.0" or not isinstance(report.get("runs"), list) or not report["runs"]:
        raise ValueError("Missing or invalid SARIF report")
    findings = []
    for run in report["runs"]:
        driver = run.get("tool", {}).get("driver", {})
        if not driver.get("name") or not isinstance(run.get("results"), list):
            raise ValueError("Missing SARIF analysis or results")
        if any(invocation.get("executionSuccessful") is False for invocation in run.get("invocations", [])):
            raise ValueError("Static analysis did not complete")
        rules = {rule["id"]: rule for rule in driver.get("rules", [])}
        for extension in run.get("tool", {}).get("extensions", []):
            rules.update({rule["id"]: rule for rule in extension.get("rules", [])})
        for result in run["results"]:
            rule = rules.get(result.get("ruleId"))
            if rule is None:
                raise ValueError("SARIF references an unknown rule")
            score = float(rule.get("properties", {}).get("security-severity", 0))
            if not 0 <= score <= 10:
                raise ValueError("Invalid security severity")
            level = result.get("level", rule.get("defaultConfiguration", {}).get("level", "warning"))
            findings.append({"id": result["ruleId"], "level": level, "security_severity": score, "blocks": score >= 7 or level == "error"})
    return {"schema_version": 1, "gate": "FAILED" if any(item["blocks"] for item in findings) else "PASSED", "findings": findings}


if __name__ == "__main__":
    source, destination = map(Path, sys.argv[1:])
    report = evaluate(json.loads(source.read_text(encoding="utf-8-sig")))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"SARIF gate: {report['gate']}; {len(report['findings'])} findings. No snippets exported.")
    raise SystemExit(report["gate"] != "PASSED")

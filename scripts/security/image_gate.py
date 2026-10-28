"""Fail closed on image findings, incomplete inventory or unsupported OS.

Consumes local Trivy JSON; no uploads, vulnerability exclusions or severity waivers.
"""

import json
import re
from pathlib import Path
import sys


def evaluate(report):
    if not isinstance(report, dict) or report.get("SchemaVersion") != 2:
        raise ValueError("Missing or unsupported image scan report")
    if report.get("ArtifactType") != "container_image" or not report.get("ArtifactID"):
        raise ValueError("Report is not bound to an image")
    image_id = report.get("Metadata", {}).get("ImageID")
    if not isinstance(image_id, str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", image_id
    ):
        raise ValueError("Missing immutable Docker image identity")
    operating_system = report.get("Metadata", {}).get("OS", {})
    if not operating_system.get("Family") or not operating_system.get("Name"):
        raise ValueError("Missing operating system inventory")
    results = report.get("Results")
    if (
        not isinstance(results, list)
        or not results
        or any(not isinstance(r, dict) for r in results)
    ):
        raise ValueError("Missing image package scan results")
    if not {"os-pkgs", "lang-pkgs"}.issubset({r.get("Class") for r in results}):
        raise ValueError("Both OS and language package scans are required")
    findings = []
    for result in results:
        vulnerabilities = result.get("Vulnerabilities", [])
        if not isinstance(vulnerabilities, list):
            raise ValueError("Invalid vulnerability records")
        for item in vulnerabilities:
            if not isinstance(item, dict) or not all(
                isinstance(item.get(k), str) and item[k]
                for k in ("VulnerabilityID", "PkgName", "InstalledVersion", "Severity")
            ):
                raise ValueError("Incomplete vulnerability record")
            if item["Severity"] not in {"UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                raise ValueError("Unrecognized vulnerability severity")
            findings.append(
                {
                    k: item.get(k, "")
                    for k in (
                        "VulnerabilityID",
                        "PkgName",
                        "InstalledVersion",
                        "FixedVersion",
                        "Severity",
                    )
                }
            )
    blocked = operating_system.get("Eosl", False) or any(
        f["Severity"] in {"UNKNOWN", "HIGH", "CRITICAL"} for f in findings
    )
    return {
        "schema_version": 1,
        "gate": "FAILED" if blocked else "PASSED",
        "image": image_id,
        "scanner_artifact_id": report["ArtifactID"],
        "os": operating_system,
        "findings": findings,
        "limitations": "Advisory/package records are not deduplicated exploits. No reachability or production certification.",
    }


def main():
    source, target = map(Path, sys.argv[1:])
    result = evaluate(json.loads(source.read_text(encoding="utf-8-sig")))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"Image security gate: {result['gate']}; {len(result['findings'])} advisory/package records."
    )
    return int(result["gate"] != "PASSED")


if __name__ == "__main__":
    raise SystemExit(main())

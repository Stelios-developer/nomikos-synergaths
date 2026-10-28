"""Opt-in OSV audit of this project's isolated Python environment only.

Sends package names/versions, never documents, credentials or environment values.
The user explicitly approved this scope. Refuses system/other-project Python.
"""
from datetime import datetime, timezone
from importlib import metadata
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]


def project_environment(prefix):
    allowed = [ROOT / "backend/.venv", ROOT / "backend/.venv-build", ROOT / "backend/venv", ROOT / "security/pdf_worker/.venv"]
    return Path(prefix).resolve() in [path.resolve() for path in allowed]


def evaluate(packages, response):
    results = response.get("results") if isinstance(response, dict) else None
    if not isinstance(results, list) or len(results) != len(packages):
        raise ValueError("Missing or malformed OSV batch results")
    findings = []
    for package, result in zip(packages, results):
        if not isinstance(result, dict) or result.get("next_page_token"):
            raise ValueError("Incomplete OSV response; pagination needs review")
        vulns = result.get("vulns", [])
        if not isinstance(vulns, list) or any(not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"] for item in vulns):
            raise ValueError("Invalid OSV vulnerability records")
        if vulns:
            findings.append({**package, "advisory_records": sorted({item["id"] for item in vulns})})
    return findings


def main():
    if sys.argv[1:] != ["--allow-osv"] or not project_environment(sys.prefix):
        raise ValueError("Use a project virtualenv and --allow-osv to explicitly permit sending only its package names/versions to OSV.")
    prefix = Path(sys.prefix).resolve()
    packages = sorted({(dist.metadata["Name"], dist.version) for dist in metadata.distributions()
                       if Path(dist.locate_file("")).resolve().is_relative_to(prefix)})
    inventory = [{"name": name, "version": version} for name, version in packages]
    if not inventory or len(inventory) > 1000:
        raise ValueError("Unexpected inventory size; refusing an incomplete scan")
    queries = [{"package": {"name": item["name"], "ecosystem": "PyPI"}, "version": item["version"]} for item in inventory]
    request = Request("https://api.osv.dev/v1/querybatch", data=json.dumps({"queries": queries}).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(request, timeout=30) as response:
        body = response.read(8 * 1024 * 1024 + 1)
    if len(body) > 8 * 1024 * 1024:
        raise ValueError("Oversized OSV response")
    findings = evaluate(inventory, json.loads(body))
    report = {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "installed distributions in the approved project virtualenv; not container OS packages",
        "environment": prefix.relative_to(ROOT).as_posix(),
        "source": "https://api.osv.dev/v1/querybatch", "gate": "FAILED" if findings else "PASSED",
        "packages_checked": len(inventory), "inventory": inventory, "findings": findings,
        "limitations": "Advisory aliases are not deduplicated CVEs. No exploitability or production-readiness claim.",
    }
    target = ROOT / "output/security/python-audit.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    label = "pdf-worker" if prefix.parent.name == "pdf_worker" else "backend"
    target.with_name(f"python-audit-{label}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Python security gate: {report['gate']}; {len(inventory)} packages; {len(findings)} affected packages.")
    for item in findings:
        print(item["name"], item["version"], ", ".join(item["advisory_records"]))
    return int(bool(findings))


if __name__ == "__main__":
    raise SystemExit(main())

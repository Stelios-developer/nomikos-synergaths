"""Measure the local review gate with a deliberately overconfident mock model."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services import auditor  # noqa: E402

data = json.loads((Path(__file__).parent / "claim_gate_v1.json").read_text(encoding="utf-8"))
counts = {"cases": 0, "critical_review_missed": 0, "unsupported_marked_supported": 0}
for case in data["cases"]:
    with patch.object(auditor, "complete", return_value='[{"supported": true, "reason": "mock"}]'):
        result = auditor.audit_answer(case["claim"], [{"text": case["source"]}])[0]
    counts["cases"] += 1
    if case["expect_review"] and not result.get("verification_unavailable", False):
        counts["critical_review_missed"] += 1
    if not case["source_supports_claim"] and result["supported"]:
        counts["unsupported_marked_supported"] += 1
        print("Unsupported claim marked supported:", case["id"])
print(json.dumps({"corpus_version": data["version"], "mode": "offline mock", **counts}, indent=2))
sys.exit(1 if counts["critical_review_missed"] or counts["unsupported_marked_supported"] else 0)

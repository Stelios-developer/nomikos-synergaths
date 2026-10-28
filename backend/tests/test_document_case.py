import json
from unittest.mock import patch

import pytest

from services import document_case


DOCUMENT_CHUNKS = [
    {
        "text": "Acme must submit the monthly compliance report by 2026-10-15. Missing it triggers a 2% service credit.",
        "filename": "contract.pdf",
        "page_number": 1,
        "chunk_index": 0,
        "method": "pymupdf",
        "upload_date": "2026-01-01T00:00:00+00:00",
    },
    {
        "text": "The agreement is between Acme Ltd and Example Services Ltd and takes effect on 2026-09-01.",
        "filename": "contract.pdf",
        "page_number": 2,
        "chunk_index": 1,
        "method": "pymupdf",
        "upload_date": "2026-01-01T00:00:00+00:00",
    },
]


def _llm_response(prompt: str, max_tokens: int) -> str:
    if "Document DNA and Quality" in prompt:
        return json.dumps({
            "document_type": "contract",
            "language": "en",
            "parties": ["Acme Ltd", "Example Services Ltd"],
            "dates": ["2026-09-01", "2026-10-15"],
            "topics": ["monthly compliance reporting"],
            "confidentiality": "internal",
            "summary": "The agreement requires a monthly compliance report.",
            "confidence": "high",
            "citation_ids": ["C1", "C2"],
        })
    if "Facts, Obligations and Deadlines" in prompt:
        return json.dumps({
            "facts": [{
                "statement": "Acme must submit a monthly compliance report.",
                "category": "obligation",
                "confidence": "high",
                "citation_ids": ["C1"],
            }],
            "obligations": [{
                "owner": "Acme",
                "action": "Submit the monthly compliance report",
                "trigger": "Monthly",
                "due_date": "2026-10-15",
                "consequence_if_missed": "2% service credit",
                "severity": "high",
                "confidence": "high",
                "citation_ids": ["C1"],
            }],
            "deadlines": [{
                "event": "Monthly compliance report",
                "date": "2026-10-15",
                "owner": "Acme",
                "status": "open",
                "citation_ids": ["C1"],
            }],
            "open_questions": [],
        })
    if "Risk Prioritisation" in prompt:
        return json.dumps({
            "overall_risk": "high",
            "risks": [{
                "title": "Late compliance report",
                "level": "high",
                "likelihood": "medium",
                "impact": "financial",
                "rationale": "A missed report triggers a 2% service credit.",
                "mitigation": "Assign an owner and review the report before its due date.",
                "related_obligation_ids": ["O1"],
                "citation_ids": ["C1"],
            }],
        })
    if "Decision Brief agent" in prompt:
        return json.dumps({
            "executive_summary": "Acme must submit the monthly compliance report by 2026-10-15.",
            "decisions_required": [{
                "decision": "Confirm the report owner.",
                "citation_ids": ["C1"],
            }],
            "open_questions": [],
        })
    if "strict evidence auditor" in prompt:
        # One summary claim plus fact, deadline, and risk rationale.
        return json.dumps([
            {"supported": True, "reason": "The due date appears in C1."},
            {"supported": True, "reason": "The reporting obligation appears in C1."},
            {"supported": True, "reason": "The deadline appears in C1."},
            {"supported": True, "reason": "The service credit appears in C1."},
        ])
    raise AssertionError(f"Unexpected document-case prompt: {prompt[:80]}")


def _run_happy_path() -> dict:
    case = document_case.start_case("contract.pdf", "workspace-a")
    case = document_case.run_document_dna(case["case_id"], "workspace-a")
    case = document_case.run_facts_obligations(case["case_id"], "workspace-a")
    case = document_case.run_risk_prioritisation(case["case_id"], "workspace-a")
    case = document_case.run_draft_action_pack(case["case_id"], "workspace-a")
    case = document_case.run_mandatory_audit(case["case_id"], "workspace-a")
    return document_case.finalize_case(case["case_id"], "workspace-a")


def test_case_pipeline_creates_verified_human_review_action_pack():
    with patch("services.document_case._load_document_chunks", return_value=DOCUMENT_CHUNKS), \
         patch("services.document_case.pdf_path", return_value=None), \
         patch("services.document_case.complete", side_effect=_llm_response):
        case = _run_happy_path()

    assert case["stage"] == "finalized"
    assert case["status"] == "ready_for_human_review"
    assert case["document_profile"]["document_type"] == "contract"
    assert case["deadlines"][0]["date"] == "2026-10-15"
    assert case["risks"][0]["level"] == "high"
    assert case["audit"]["passed"] is True
    assert case["final_action_pack"]["verification_status"] == "verified"
    assert case["final_action_pack"]["action_items"][0]["approval_required"] is True
    assert case["final_action_pack"]["human_review_required"] is True


def test_case_blocks_final_action_pack_when_the_auditor_is_unavailable():
    def unavailable_auditor(prompt: str, max_tokens: int) -> str:
        if "strict evidence auditor" in prompt:
            return "not structured JSON"
        return _llm_response(prompt, max_tokens)

    with patch("services.document_case._load_document_chunks", return_value=DOCUMENT_CHUNKS), \
         patch("services.document_case.pdf_path", return_value=None), \
         patch("services.document_case.complete", side_effect=unavailable_auditor):
        case = _run_happy_path()

    assert case["status"] == "needs_human_review"
    assert case["audit"]["verification_available"] is False
    assert case["final_action_pack"]["verification_status"] == "needs_human_review"
    assert case["final_action_pack"]["action_items"] == []
    assert case["final_action_pack"]["deadline_calendar"] == []


def test_json_completion_recovers_a_valid_object_after_a_format_retry():
    with patch(
        "services.document_case.complete",
        side_effect=["Here is the result: {not valid}", '{"status": "ok"}'],
    ) as complete:
        result, warning = document_case._json_completion("Return a JSON object.")

    assert result == {"status": "ok"}
    assert warning is None
    assert complete.call_count == 2
    assert "IMPORTANT RETRY" in complete.call_args_list[1].args[0]


def test_json_parser_accepts_a_json_object_wrapped_in_provider_prose():
    assert document_case._parse_json_object('Result follows: {"status": "ok"}\nThank you.') == {"status": "ok"}


def test_case_stages_are_ordered_and_workspace_scoped():
    with patch("services.document_case._load_document_chunks", return_value=DOCUMENT_CHUNKS), \
         patch("services.document_case.pdf_path", return_value=None):
        case = document_case.start_case("contract.pdf", "workspace-a")

    with pytest.raises(document_case.CaseStageError):
        document_case.run_risk_prioritisation(case["case_id"], "workspace-a")
    with pytest.raises(ValueError, match="not found"):
        document_case.run_document_dna(case["case_id"], "workspace-b")


def test_normalisers_drop_unknown_or_uncited_findings():
    result = document_case._normalise_facts({
        "facts": [
            {"statement": "supported", "citation_ids": ["C1"]},
            {"statement": "not supported", "citation_ids": ["C99"]},
        ],
        "obligations": [{"action": "No evidence", "citation_ids": []}],
        "deadlines": [{"event": "Date", "date": "2026-10-15", "citation_ids": ["C99"]}],
    }, {"C1"})

    assert [fact["statement"] for fact in result["facts"]] == ["supported"]
    assert result["obligations"] == []
    assert result["deadlines"] == []

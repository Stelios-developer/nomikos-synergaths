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


def test_case_pipeline_withholds_pack_when_some_fields_are_not_audited():
    with patch("services.document_case._load_document_chunks", return_value=DOCUMENT_CHUNKS), \
         patch("services.document_case.pdf_path", return_value=None), \
         patch("services.document_case.complete", side_effect=_llm_response):
        case = _run_happy_path()

    assert case["stage"] == "finalized"
    assert case["status"] == "needs_human_review"
    assert case["document_profile"]["document_type"] == "contract"
    assert case["deadlines"][0]["date"] == "2026-10-15"
    assert case["risks"][0]["level"] == "high"
    assert case["audit"]["passed"] is False
    assert case["final_action_pack"]["verification_status"] == "needs_human_review"
    assert case["final_action_pack"]["action_items"] == []
    assert case["final_action_pack"]["human_review_required"] is True


def test_action_does_not_inherit_an_unrelated_deadline_from_same_owner():
    case = {
        "deadlines": [{"owner": "Finance", "date": "2026-10-15"}],
        "obligations": [{"id": "O1", "owner": "Finance", "action": "Review receipts", "severity": "high", "due_date": None, "citation_ids": ["C1"]}],
    }
    assert document_case._draft_actions(case)[0]["due_date"] is None


def test_old_verified_case_is_rechecked_without_modifying_stored_case():
    old = {
        "status": "ready_for_human_review",
        "draft_action_pack": {"action_items": [{"title": "Take action"}]},
        "audit": {"passed": True},
        "final_action_pack": {"verification_status": "verified", "action_items": [{"title": "Take action"}]},
    }
    result = document_case.public_case(old)
    assert result["status"] == "needs_human_review"
    assert result["final_action_pack"]["action_items"] == []
    assert old["audit"]["passed"] is True
    assert old["final_action_pack"]["verification_status"] == "verified"


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


def test_json_parser_does_not_accept_nested_fragment_of_truncated_object():
    assert document_case._parse_json_object('{"facts": [{"statement": "partial"}') == {}


def test_json_completion_retries_when_required_sections_are_missing():
    complete_response = '{"facts": [], "obligations": [], "deadlines": [], "open_questions": []}'
    with patch("services.document_case.complete", side_effect=['{"statement": "partial"}', complete_response]) as complete:
        result, warning = document_case._json_completion("Extract facts", required_lists=("facts", "obligations", "deadlines", "open_questions"))
    assert warning is None
    assert result["facts"] == []
    assert complete.call_count == 2


def test_extraction_warning_blocks_a_passing_auditor():
    case = {
        "stage": "draft_complete",
        "draft_action_pack": {"audit_claims": []},
        "citations": [],
        "warnings": [{"stage": "facts_obligations", "message": "Extraction incomplete"}],
    }
    audit = {"passed": True, "reason": "All claims were supported."}
    with patch.object(document_case, "_get_case", return_value=case), \
         patch.object(document_case, "_strict_audit", return_value=audit), \
         patch.object(document_case, "_save", side_effect=lambda c, stage, status: (c, stage, status)):
        result, stage, status = document_case.run_mandatory_audit("case", "workspace")
    assert result["audit"]["passed"] is False
    assert stage == "audited"
    assert status == "needs_human_review"


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


@pytest.mark.parametrize("claim", [
    "The Finance Director is the owner.",
    "The deadline is 20 October 2026.",
    "Η προθεσμία είναι εντός 30 ημερών.",
])
def test_case_audit_cannot_certify_sensitive_claims_using_model_verdict_alone(claim):
    claims = [{"text": claim, "citation_ids": ["C1"]}]
    evidence = [{"id": "C1", "page": 1, "excerpt": "Owner: R&D lead. Approval: Finance Director. Due 15 October 2026."}]
    with patch.object(document_case, "complete", return_value='[{"supported": true, "reason": "matches"}]'):
        result = document_case._strict_audit(claims, evidence)
    assert result["passed"] is False
    assert result["sentences"][0]["verification_unavailable"] is True
    assert result["summary"] == {"supported": 0, "unsupported": 0, "unverifiable": 1}


def test_case_audit_does_not_certify_any_claim_on_model_verdict_alone():
    claims = [{"text": "The agreement permits termination at will.", "citation_ids": ["C1"]}]
    evidence = [{"id": "C1", "page": 1, "excerpt": "The agreement describes delivery."}]
    with patch.object(document_case, "complete", return_value='[{"supported": true, "reason": "matches"}]'):
        result = document_case._strict_audit(claims, evidence)
    assert result["passed"] is False
    assert result["sentences"][0]["verification_unavailable"] is True


def test_old_verified_case_without_sensitive_keywords_requires_review():
    old = {"status": "verified", "draft_action_pack": {},
           "audit": {"passed": True, "sentences": [{"text": "The agreement permits termination at will.", "supported": True}]},
           "final_action_pack": {"verification_status": "verified", "executive_summary": "The agreement permits termination at will."}}
    result = document_case.public_case(old)
    assert result["final_action_pack"]["verification_status"] == "needs_human_review"
    assert result["audit"]["sentences"][0]["verification_unavailable"] is True
    assert old["audit"]["passed"] is True


def test_previously_verified_case_is_downgraded_without_mutating_stored_case():
    case = {
        "status": "verified", "draft_action_pack": {},
        "audit": {"passed": True, "sentences": [{"text": "Deadline: 20 October 2026.", "supported": True}],
                  "summary": {"supported": 1, "unsupported": 0, "unverifiable": 0}},
        "final_action_pack": {"verification_status": "verified", "executive_summary": "Deadline: 20 October 2026."},
    }
    result = document_case.public_case(case)
    assert result["status"] == "needs_human_review"
    assert result["audit"]["summary"]["unverifiable"] == 1
    assert result["final_action_pack"]["verification_status"] == "needs_human_review"
    assert "20 October" not in result["final_action_pack"]["executive_summary"]
    assert case["audit"]["passed"] is True

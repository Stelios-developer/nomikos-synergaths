from unittest.mock import patch

import services.auditor as auditor

CHUNKS = [{"text": "The R&D deduction rate is 24%.", "filename": "tax.pdf", "page_number": 2, "chunk_index": 0}]


def test_split_sentences_handles_basic_prose():
    result = auditor._split_sentences("The rate is 24% [1]. It applies to all R&D spend [2].")
    assert result == ["The rate is 24% [1].", "It applies to all R&D spend [2]."]


def test_split_sentences_empty_on_blank_input():
    assert auditor._split_sentences("   ") == []


def test_audit_answer_returns_empty_list_for_blank_answer():
    assert auditor.audit_answer("", CHUNKS) == []


def test_audit_answer_marks_all_unsupported_when_no_chunks_at_all():
    result = auditor.audit_answer("The rate is 24%. It applies to everyone.", [])
    assert len(result) == 2
    assert all(r["supported"] is False for r in result)


def test_audit_answer_parses_per_sentence_json_verdicts():
    answer = "The rate is 24% [1]. It also covers software costs [2]."
    fake_response = (
        '[{"supported": true, "reason": "matches chunk 1"}, '
        '{"supported": false, "reason": "not mentioned anywhere"}]'
    )
    with patch.object(auditor, "complete", return_value=fake_response):
        result = auditor.audit_answer(answer, CHUNKS)

    assert len(result) == 2
    assert result[0] == {"text": "The rate is 24% [1].", "supported": True, "reason": "matches chunk 1"}
    assert result[1] == {
        "text": "It also covers software costs [2].",
        "supported": False,
        "reason": "not mentioned anywhere",
    }


def test_audit_answer_fails_closed_on_unparseable_response():
    answer = "The rate is 24%. It applies broadly."
    with patch.object(auditor, "complete", return_value="I can't verify this right now."):
        result = auditor.audit_answer(answer, CHUNKS)

    assert len(result) == 2
    assert all(r["supported"] is False for r in result)
    assert all(r["verification_unavailable"] is True for r in result)
    assert all("δεν ήταν δυνατή" in r["reason"].lower() for r in result)


def test_audit_answer_falls_back_when_verdict_count_mismatches_sentence_count():
    answer = "First sentence. Second sentence. Third sentence."
    only_two = '[{"supported": true, "reason": "a"}, {"supported": true, "reason": "b"}]'
    with patch.object(auditor, "complete", return_value=only_two):
        result = auditor.audit_answer(answer, CHUNKS)

    assert len(result) == 3
    assert all(r["supported"] is False for r in result)
    assert all(r["verification_unavailable"] is True for r in result)


def test_audit_answer_falls_back_when_verdict_missing_supported_key():
    answer = "One sentence here."
    malformed = '[{"reason": "no supported key"}]'
    with patch.object(auditor, "complete", return_value=malformed):
        result = auditor.audit_answer(answer, CHUNKS)

    assert len(result) == 1
    assert result[0]["supported"] is False
    assert result[0]["verification_unavailable"] is True


def test_audit_answer_fails_closed_when_model_call_errors():
    with patch.object(auditor, "complete", side_effect=TimeoutError("provider unavailable")):
        result = auditor.audit_answer("The rate is 24%.", CHUNKS)

    assert result[0]["supported"] is False
    assert result[0]["verification_unavailable"] is True
    assert "provider unavailable" not in result[0]["reason"]

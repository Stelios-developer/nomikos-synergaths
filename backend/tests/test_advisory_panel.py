from unittest.mock import patch

import services.advisory_panel as advisory_panel

FAKE_CHUNKS = [{"text": "The R&D deduction rate is 24%.", "filename": "tax.pdf", "page_number": 2, "chunk_index": 0}]


def _fake_generate_with_system(question, chunks, system_prompt, history=None):
    # Each ADVISORS system_prompt is guaranteed to contain its persona
    # label, so the fake can tell which advisor is "speaking" without
    # relying on call order (the whole point is that order isn't fixed).
    if "Επιθετικός" in system_prompt:
        return "Aggressive take: claim the full 24%."
    if "Συντηρητικός" in system_prompt:
        return "Conservative take: document everything first."
    return "Risk take: medium risk, ambiguous wording."


def test_run_panel_stream_yields_citations_then_three_advisors_then_moderator():
    with patch.object(advisory_panel, "hybrid_search", return_value=FAKE_CHUNKS), \
         patch.object(advisory_panel, "generate_with_system", side_effect=_fake_generate_with_system), \
         patch.object(advisory_panel, "complete", return_value="Synthesis: panel agrees on 24%."):
        events = list(advisory_panel.run_panel_stream("what is the R&D deduction rate?"))

    kinds = [k for k, _ in events]
    assert kinds[0] == "citations"
    assert kinds[-1] == "done"
    assert kinds.count("advisor") == 3

    assert events[0][1] == [{"filename": "tax.pdf", "page": 2, "text": "The R&D deduction rate is 24%."}]

    # Order-independent: three advisors run concurrently, so completion
    # order isn't guaranteed — assert on the *set* of ids/answers instead.
    advisor_events = [payload for kind, payload in events if kind == "advisor"]
    by_id = {e["id"]: e for e in advisor_events}
    assert set(by_id) == {"aggressive", "conservative", "risk"}
    assert by_id["aggressive"]["answer"] == "Aggressive take: claim the full 24%."
    assert by_id["conservative"]["answer"] == "Conservative take: document everything first."
    assert by_id["risk"]["answer"] == "Risk take: medium risk, ambiguous wording."
    assert by_id["aggressive"]["emoji"] == "🚀"
    assert by_id["aggressive"]["label"] == "Επιθετικός Φοροτεχνικός"

    assert events[-1][1] == {"moderator_summary": "Synthesis: panel agrees on 24%."}


def test_moderator_prompt_includes_all_three_opinions():
    with patch.object(advisory_panel, "hybrid_search", return_value=FAKE_CHUNKS), \
         patch.object(advisory_panel, "generate_with_system", side_effect=_fake_generate_with_system), \
         patch.object(advisory_panel, "complete") as mock_complete:
        mock_complete.return_value = "final synthesis"
        list(advisory_panel.run_panel_stream("what is the rate?"))

    moderator_prompt = mock_complete.call_args.args[0]
    assert "Aggressive take: claim the full 24%." in moderator_prompt
    assert "Conservative take: document everything first." in moderator_prompt
    assert "Risk take: medium risk, ambiguous wording." in moderator_prompt


def test_run_panel_stream_short_circuits_when_no_chunks_retrieved():
    with patch.object(advisory_panel, "hybrid_search", return_value=[]), \
         patch.object(advisory_panel, "complete") as mock_complete:
        events = list(advisory_panel.run_panel_stream("nothing relevant uploaded"))

    kinds = [k for k, _ in events]
    assert kinds == ["citations", "done"]
    assert events[0][1] == []
    assert "Δεν βρέθηκαν" in events[-1][1]["moderator_summary"]
    mock_complete.assert_not_called()  # no advisors ran, so no moderator synthesis needed


def test_run_panel_stream_survives_one_advisor_failing():
    def flaky_generate(question, chunks, system_prompt, history=None):
        if "Συντηρητικός" in system_prompt:
            raise RuntimeError("upstream LLM error")
        return "ok answer"

    with patch.object(advisory_panel, "hybrid_search", return_value=FAKE_CHUNKS), \
         patch.object(advisory_panel, "generate_with_system", side_effect=flaky_generate), \
         patch.object(advisory_panel, "complete", return_value="synthesis despite one failure"):
        events = list(advisory_panel.run_panel_stream("what is the rate?"))

    advisor_events = [payload for kind, payload in events if kind == "advisor"]
    by_id = {e["id"]: e for e in advisor_events}
    assert len(by_id) == 3  # a failing advisor still yields an event, not a crash
    assert "upstream LLM error" not in str(events)
    assert "δεν ήταν διαθέσιμος" in by_id["conservative"]["answer"]
    assert events[-1][0] == "done"

from unittest.mock import patch

import services.debate as debate

FAKE_CHUNKS = [{"text": "The R&D deduction rate is 24%.", "filename": "tax.pdf", "page_number": 2, "chunk_index": 0}]


def _fake_generate_with_system(question, chunks, system_prompt, history=None):
    side = "for" if "Εισηγητής Υπέρ" in system_prompt else "against"
    if "μόλις υποστήριξε" in system_prompt:
        # Rebuttal prompts embed the opponent's previous argument between
        # triple quotes — extract it so tests can prove the CORRECT
        # opponent text was actually passed in, not just that a rebuttal
        # happened.
        quoted = system_prompt.split('"""')[1]
        return f"{side}-rebuttal-responding-to:{quoted}"
    return f"{side}-opening"


def test_run_debate_stream_yields_citations_then_two_rounds_then_verdict():
    with patch.object(debate, "hybrid_search", return_value=FAKE_CHUNKS), \
         patch.object(debate, "generate_with_system", side_effect=_fake_generate_with_system), \
         patch.object(debate, "complete", return_value="Judge: the FOR side wins on documentation."):
        events = list(debate.run_debate_stream("should we claim the full R&D deduction?"))

    kinds = [k for k, _ in events]
    assert kinds[0] == "citations"
    assert kinds[-1] == "verdict"
    assert kinds.count("argument") == debate.MAX_ROUNDS * 2

    assert events[0][1] == [{"filename": "tax.pdf", "page": 2, "text": "The R&D deduction rate is 24%."}]

    arguments = [payload for kind, payload in events if kind == "argument"]
    round1 = [a for a in arguments if a["round"] == 1]
    round2 = [a for a in arguments if a["round"] == 2]
    assert {a["side"] for a in round1} == {"for", "against"}
    assert {a["side"] for a in round2} == {"for", "against"}
    assert all(a["text"].endswith("-opening") for a in round1)
    assert all("-rebuttal-responding-to:" in a["text"] for a in round2)

    for_arg = next(a for a in round1 if a["side"] == "for")
    assert for_arg["label"] == "Εισηγητής Υπέρ"
    assert for_arg["emoji"] == "📢"

    assert events[-1][1] == {"summary": "Judge: the FOR side wins on documentation."}


def test_rebuttal_responds_to_opponents_previous_round_specifically():
    with patch.object(debate, "hybrid_search", return_value=FAKE_CHUNKS), \
         patch.object(debate, "generate_with_system", side_effect=_fake_generate_with_system), \
         patch.object(debate, "complete", return_value="verdict"):
        events = list(debate.run_debate_stream("q"))

    arguments = [payload for kind, payload in events if kind == "argument"]
    for_r2 = next(a for a in arguments if a["side"] == "for" and a["round"] == 2)
    against_r2 = next(a for a in arguments if a["side"] == "against" and a["round"] == 2)

    # FOR's round-2 rebuttal must respond to AGAINST's round-1 opening,
    # and vice versa — never to its own round-1 argument.
    assert "against-opening" in for_r2["text"]
    assert "for-opening" not in for_r2["text"]
    assert "for-opening" in against_r2["text"]
    assert "against-opening" not in against_r2["text"]


def test_judge_prompt_includes_the_full_transcript_from_both_sides():
    with patch.object(debate, "hybrid_search", return_value=FAKE_CHUNKS), \
         patch.object(debate, "generate_with_system", side_effect=_fake_generate_with_system), \
         patch.object(debate, "complete") as mock_complete:
        mock_complete.return_value = "final verdict"
        list(debate.run_debate_stream("q"))

    judge_prompt = mock_complete.call_args.args[0]
    assert "for-opening" in judge_prompt
    assert "against-opening" in judge_prompt
    assert "rebuttal-responding-to" in judge_prompt


def test_run_debate_stream_short_circuits_when_no_chunks_retrieved():
    with patch.object(debate, "hybrid_search", return_value=[]), \
         patch.object(debate, "complete") as mock_complete, \
         patch.object(debate, "generate_with_system") as mock_generate:
        events = list(debate.run_debate_stream("nothing relevant uploaded"))

    kinds = [k for k, _ in events]
    assert kinds == ["citations", "verdict"]
    assert events[0][1] == []
    assert "Δεν βρέθηκαν" in events[-1][1]["summary"]
    mock_complete.assert_not_called()
    mock_generate.assert_not_called()


def test_run_debate_stream_survives_one_side_failing():
    def flaky_generate(question, chunks, system_prompt, history=None):
        if "Εισηγητής Κατά" in system_prompt:
            raise RuntimeError("upstream LLM error")
        return "for-ok"

    with patch.object(debate, "hybrid_search", return_value=FAKE_CHUNKS), \
         patch.object(debate, "generate_with_system", side_effect=flaky_generate), \
         patch.object(debate, "complete", return_value="verdict despite failure"):
        events = list(debate.run_debate_stream("q"))

    arguments = [payload for kind, payload in events if kind == "argument"]
    against_args = [a for a in arguments if a["side"] == "against"]
    assert len(against_args) == debate.MAX_ROUNDS  # still yields an event per round, not a crash
    assert "upstream LLM error" in against_args[0]["text"]
    assert events[-1][0] == "verdict"

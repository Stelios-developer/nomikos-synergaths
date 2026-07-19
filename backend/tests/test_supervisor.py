from unittest.mock import patch

import services.agent as agent
import services.code_agent as code_agent
import services.evaluator as evaluator
import services.supervisor as supervisor


def _tool_call(name, **input_kwargs):
    return {"tool_call": {"name": name, "input": input_kwargs}, "text": ""}


FAKE_CHUNKS = [{"text": "The R&D deduction rate is 24%.", "filename": "tax.pdf", "page_number": 2, "chunk_index": 0}]


def _fake_stream_answer(question, chunks, history=None):
    for tok in ["The ", "rate ", "is ", "24%."]:
        yield tok


def _rag_mocks():
    """Context-managerless helper: returns the patch objects needed to
    exercise the search_documents path without hitting a real LLM/ChromaDB."""
    return [
        patch.object(agent, "hybrid_search", return_value=FAKE_CHUNKS),
        patch.object(agent, "_grade_chunks", return_value=[True]),
        patch.object(supervisor, "stream_answer", side_effect=_fake_stream_answer),
        patch.object(evaluator, "score", return_value=0.9),
    ]


def test_supervisor_docs_only_path():
    responses = [
        _tool_call("search_documents", query="depreciation rate"),
        _tool_call("finish", summary="The rate is 24%."),
    ]
    patches = _rag_mocks()
    for p in patches:
        p.start()
    try:
        with patch.object(supervisor, "call_with_tools", side_effect=responses):
            events = list(supervisor.run_supervisor_stream("what is the depreciation rate?"))
    finally:
        for p in patches:
            p.stop()

    kinds = [k for k, _ in events]
    assert kinds == ["route", "rag_token", "rag_token", "rag_token", "rag_token", "rag_done", "done"]
    assert events[0][1] == {"tool": "search_documents", "input": "depreciation rate"}
    assert events[-2][1]["citations"][0]["filename"] == "tax.pdf"
    assert events[-1][1]["summary"] == "The rate is 24%."


def test_supervisor_code_only_path():
    responses = [
        _tool_call("run_code", goal="simulate a die roll"),
        _tool_call("finish", summary="Simulation done."),
    ]
    coder_responses = [
        _tool_call("run_code", code="print('rolled a 4')"),
        _tool_call("finish", summary="Rolled a 4."),
    ]
    with patch.object(supervisor, "call_with_tools", side_effect=responses), \
         patch.object(code_agent, "complete", side_effect=['["one step"]', "APPROVE"]), \
         patch.object(code_agent, "call_with_tools", side_effect=coder_responses):
        events = list(supervisor.run_supervisor_stream("simulate a die roll"))

    kinds = [k for k, _ in events]
    assert kinds == ["route", "action_plan", "action_code", "action_review", "action_result", "done"]
    assert events[0][1] == {"tool": "run_code", "input": "simulate a die roll"}
    assert events[-2][1]["success"] is True
    assert events[-1][1]["summary"] == "Simulation done."


def test_supervisor_chains_docs_then_code():
    responses = [
        _tool_call("search_documents", query="depreciation rate"),
        _tool_call("run_code", goal="compute schedule using 24% rate"),
        _tool_call("finish", summary="Computed using the 24% rate found in the PDF."),
    ]
    coder_responses = [
        _tool_call("run_code", code="print('schedule computed')"),
        _tool_call("finish", summary="Done."),
    ]
    patches = _rag_mocks()
    for p in patches:
        p.start()
    try:
        with patch.object(supervisor, "call_with_tools", side_effect=responses), \
             patch.object(code_agent, "complete", side_effect=['["one step"]', "APPROVE"]), \
             patch.object(code_agent, "call_with_tools", side_effect=coder_responses):
            events = list(supervisor.run_supervisor_stream("find the rate and compute a schedule"))
    finally:
        for p in patches:
            p.stop()

    kinds = [k for k, _ in events]
    assert "rag_done" in kinds
    assert "action_result" in kinds
    assert kinds.index("rag_done") < kinds.index("action_result")  # docs happened before code
    assert events[-1][1]["summary"] == "Computed using the 24% rate found in the PDF."


def test_supervisor_finishes_immediately_without_any_tool():
    with patch.object(supervisor, "call_with_tools", return_value={"tool_call": None, "text": "Direct answer."}):
        events = list(supervisor.run_supervisor_stream("trivial question"))

    kinds = [k for k, _ in events]
    assert kinds == ["done"]
    assert events[0][1]["summary"] == "Direct answer."


def test_supervisor_gives_up_after_max_steps():
    always_search = _tool_call("search_documents", query="something")
    patches = _rag_mocks()
    for p in patches:
        p.start()
    try:
        with patch.object(supervisor, "call_with_tools", return_value=always_search):
            events = list(supervisor.run_supervisor_stream("endless question"))
    finally:
        for p in patches:
            p.stop()

    route_events = [e for e in events if e[0] == "route"]
    assert len(route_events) == supervisor.MAX_SUPERVISOR_STEPS

    final = events[-1]
    assert final[0] == "done"
    assert final[1]["error"] is True

from unittest.mock import patch

import services.agent as agent
import services.evaluator as evaluator
import services.supervisor as supervisor


FAKE_CHUNKS = [{"text": "The R&D deduction rate is 24%.", "filename": "tax.pdf", "page_number": 2, "chunk_index": 0}]


def _tool_call(name, **input_kwargs):
    return {"tool_call": {"name": name, "input": input_kwargs}, "text": ""}


def _fake_stream_answer(question, chunks, history=None):
    yield from ["The ", "rate ", "is ", "24%."]


def test_supervisor_routes_to_grounded_document_search():
    responses = [_tool_call("search_documents", query="deduction rate"), _tool_call("finish", summary="The rate is 24%.")]
    with patch.object(agent, "hybrid_search", return_value=FAKE_CHUNKS), \
         patch.object(agent, "_grade_chunks", return_value=[True]), \
         patch.object(supervisor, "stream_answer", side_effect=_fake_stream_answer), \
         patch.object(evaluator, "score", return_value=0.9), \
         patch.object(supervisor, "call_with_tools", side_effect=responses):
        events = list(supervisor.run_supervisor_stream("What is the deduction rate?"))

    assert [kind for kind, _ in events] == ["route", "rag_token", "rag_token", "rag_token", "rag_token", "rag_done", "done"]
    assert events[0][1] == {"tool": "search_documents", "input": "deduction rate"}
    assert events[-2][1]["citations"][0]["filename"] == "tax.pdf"
    assert events[-1][1]["summary"] == "The rate is 24%."


def test_supervisor_can_finish_without_search():
    with patch.object(supervisor, "call_with_tools", return_value={"tool_call": None, "text": "No document search is needed."}):
        events = list(supervisor.run_supervisor_stream("Hello"))

    assert events == [("done", {"summary": "No document search is needed."})]


def test_supervisor_stops_after_its_step_limit():
    with patch.object(agent, "hybrid_search", return_value=FAKE_CHUNKS), \
         patch.object(agent, "_grade_chunks", return_value=[True]), \
         patch.object(supervisor, "stream_answer", side_effect=_fake_stream_answer), \
         patch.object(evaluator, "score", return_value=0.9), \
         patch.object(supervisor, "call_with_tools", return_value=_tool_call("search_documents", query="again")):
        events = list(supervisor.run_supervisor_stream("Endless question"))

    assert len([event for event in events if event[0] == "route"]) == supervisor.MAX_SUPERVISOR_STEPS
    assert events[-1][1]["error"] is True

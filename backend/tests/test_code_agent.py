from unittest.mock import patch

import services.code_agent as code_agent


# --- Planner ---

def test_plan_steps_parses_json_list():
    with patch.object(code_agent, "complete", return_value='["do X", "do Y"]'):
        assert code_agent.plan_steps("some goal") == ["do X", "do Y"]


def test_plan_steps_extracts_json_even_with_surrounding_prose():
    response = 'Sure, here is the plan:\n["step one", "step two"]\nHope that helps!'
    with patch.object(code_agent, "complete", return_value=response):
        assert code_agent.plan_steps("some goal") == ["step one", "step two"]


def test_plan_steps_falls_back_to_whole_goal_on_unparseable_response():
    with patch.object(code_agent, "complete", return_value="not json at all"):
        assert code_agent.plan_steps("do the thing") == ["do the thing"]


def test_plan_steps_truncates_to_max_steps():
    steps = [f"step {i}" for i in range(10)]
    with patch.object(code_agent, "complete", return_value=str(steps).replace("'", '"')):
        result = code_agent.plan_steps("goal")
    assert len(result) == code_agent.MAX_PLAN_STEPS


# --- Reviewer ---

def test_review_code_approves():
    with patch.object(code_agent, "complete", return_value="APPROVE"):
        approved, feedback = code_agent.review_code("goal", "print(1)")
    assert approved is True
    assert feedback == ""


def test_review_code_rejects_with_reason():
    with patch.object(code_agent, "complete", return_value="REJECT: uses a disallowed import"):
        approved, feedback = code_agent.review_code("goal", "import os")
    assert approved is False
    assert feedback == "uses a disallowed import"


def test_review_code_rejects_without_colon_still_treated_as_rejection():
    with patch.object(code_agent, "complete", return_value="REJECT this looks wrong"):
        approved, feedback = code_agent.review_code("goal", "print(1)")
    assert approved is False
    assert "REJECT this looks wrong" in feedback


# --- Full multi-agent loop ---

def _tool_call(name, **input_kwargs):
    return {"tool_call": {"name": name, "input": input_kwargs}, "text": ""}


def test_run_agent_stream_happy_path_single_attempt():
    coder_responses = [
        _tool_call("run_code", code="print('42')"),
        _tool_call("finish", summary="The answer is 42."),
    ]
    with patch.object(code_agent, "complete", side_effect=['["compute the answer"]', "APPROVE"]), \
         patch.object(code_agent, "call_with_tools", side_effect=coder_responses):
        events = list(code_agent.run_agent_stream("compute the answer"))

    kinds = [k for k, _ in events]
    assert kinds == ["plan", "code", "review", "result"]

    plan_payload = events[0][1]
    assert plan_payload["steps"] == ["compute the answer"]

    result = events[-1][1]
    assert result["success"] is True
    assert result["attempts"] == 1
    assert result["summary"] == "The answer is 42."
    assert "42" in result["stdout"]


def test_run_agent_stream_reviewer_rejects_then_approves():
    coder_responses = [
        _tool_call("run_code", code="import os\nos.system('bad')"),
        _tool_call("run_code", code="print('safe')"),
        _tool_call("finish", summary="done"),
    ]
    with patch.object(code_agent, "complete", side_effect=[
            '["one step"]',
            "REJECT: dangerous import",
            "APPROVE",
        ]), \
         patch.object(code_agent, "call_with_tools", side_effect=coder_responses):
        events = list(code_agent.run_agent_stream("do something"))

    kinds = [k for k, _ in events]
    assert kinds == ["plan", "code", "review", "code", "review", "result"]

    first_review = events[2][1]
    assert first_review == {"attempt": 1, "approved": False, "feedback": "dangerous import"}
    second_review = events[4][1]
    assert second_review["approved"] is True

    result = events[-1][1]
    assert result["success"] is True
    assert result["attempts"] == 2


def test_run_agent_stream_approved_code_fails_at_runtime_then_self_corrects():
    coder_responses = [
        _tool_call("run_code", code="print(undefined_name)"),
        _tool_call("run_code", code="print('recovered')"),
        _tool_call("finish", summary="recovered fine"),
    ]
    with patch.object(code_agent, "complete", side_effect=['["one step"]', "APPROVE", "APPROVE"]), \
         patch.object(code_agent, "call_with_tools", side_effect=coder_responses):
        events = list(code_agent.run_agent_stream("goal"))

    kinds = [k for k, _ in events]
    assert kinds == ["plan", "code", "review", "error", "code", "review", "result"]

    error_payload = events[3][1]
    assert error_payload["attempt"] == 1
    assert "NameError" in error_payload["message"]

    result = events[-1][1]
    assert result["success"] is True
    assert result["attempts"] == 2


def test_run_agent_stream_finishes_immediately_without_any_code():
    with patch.object(code_agent, "complete", return_value='["trivial goal"]'), \
         patch.object(code_agent, "call_with_tools", return_value=_tool_call("finish", summary="No computation needed.")):
        events = list(code_agent.run_agent_stream("trivial goal"))

    kinds = [k for k, _ in events]
    assert kinds == ["plan", "result"]
    result = events[-1][1]
    assert result["attempts"] == 0
    assert result["summary"] == "No computation needed."


def test_run_agent_stream_treats_plain_text_response_as_finish():
    with patch.object(code_agent, "complete", return_value='["goal"]'), \
         patch.object(code_agent, "call_with_tools", return_value={"tool_call": None, "text": "Here's my answer directly."}):
        events = list(code_agent.run_agent_stream("goal"))

    result = events[-1][1]
    assert result["success"] is True
    assert result["summary"] == "Here's my answer directly."


def test_run_agent_stream_gives_up_after_max_tool_calls():
    always_run_code = _tool_call("run_code", code="print(still_broken)")
    with patch.object(code_agent, "complete", side_effect=['["goal"]'] + ["APPROVE"] * code_agent.MAX_TOOL_CALLS), \
         patch.object(code_agent, "call_with_tools", return_value=always_run_code):
        events = list(code_agent.run_agent_stream("impossible goal"))

    code_events = [e for e in events if e[0] == "code"]
    assert len(code_events) == code_agent.MAX_TOOL_CALLS

    result = events[-1][1]
    assert result["success"] is False
    assert result["attempts"] == code_agent.MAX_TOOL_CALLS
    assert "όριο ενεργειών" in result["error"]

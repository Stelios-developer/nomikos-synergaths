"""
Multi-agent, tool-calling, self-correcting code-execution agent —
deliberately independent of the document RAG pipeline (no retrieval, no
chunks, no ChromaDB).

Three roles, three separate LLM calls per cycle:
  - Planner  (plan_steps)   — breaks the goal into a short visible plan,
                              shown to the user before any code is written.
  - Coder    (run_agent_stream's loop) — a genuine ReAct agent: at each
                              step it either calls the `run_code` tool
                              (via native tool-calling, services/llm.py's
                              call_with_tools — not a regex-parsed code
                              fence) or calls `finish` to report a result.
  - Reviewer (review_code)  — vets every proposed code snippet *before* it
                              ever reaches the sandbox, and can reject it
                              (feeding a reason back to the Coder) without
                              spending a sandbox execution at all. This is
                              in addition to the sandbox's own runtime
                              error feedback, not instead of it — code can
                              still fail after being approved, and that
                              failure is fed back the same way as before.

Where the document assistant is a fixed graph (retrieve -> evaluate ->
rephrase -> generate), this is a genuine act -> observe -> reflect loop:
the number and content of steps aren't fixed in advance — they depend on
what the Coder decides to do and whether its code actually runs.
"""
import json
import re

from services.llm import complete, call_with_tools
from services.sandbox import run_python

MAX_TOOL_CALLS = 4     # Coder decisions per run (each run_code or finish call counts as one)
MAX_PLAN_STEPS = 4

RUN_CODE_TOOL = {
    "name": "run_code",
    "description": (
        "Execute a self-contained Python script in a sandbox and observe its stdout/stderr. "
        "Use this to actually compute results — never guess numbers. If a chart is useful, "
        "save it as exactly 'output.png' (e.g. plt.savefig('output.png'))."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Complete, self-contained Python source code to run."},
        },
        "required": ["code"],
    },
}

FINISH_TOOL = {
    "name": "finish",
    "description": "Call this once you have a satisfactory, already-computed result to report back to the user.",
    "parameters": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Short natural-language summary of the final result."},
        },
        "required": ["summary"],
    },
}

TOOLS = [RUN_CODE_TOOL, FINISH_TOOL]

PLANNER_INSTRUCTIONS = (
    "Είσαι ο planner ενός coding agent. Σπάσε τον παρακάτω στόχο σε 2 έως "
    f"{MAX_PLAN_STEPS} σύντομα, συγκεκριμένα βήματα (μία πρόταση το καθένα). "
    "Απάντα ΜΟΝΟ με μία JSON λίστα από strings, π.χ. [\"βήμα 1\", \"βήμα 2\"]."
)

CODER_INSTRUCTIONS = (
    "Είσαι ο coder ενός agent που πετυχαίνει στόχους γράφοντας και εκτελώντας Python. "
    "Επιτρέπονται imports: pandas, numpy, matplotlib(.pyplot), math, statistics, datetime, "
    "json, decimal, random, itertools, collections. ΜΗΝ κάνεις import os/sys/subprocess/"
    "socket/shutil/requests/urllib, ΜΗΝ ανοίγεις αρχεία εκτός του τρέχοντος φακέλου. "
    "Κάλεσε το εργαλείο 'run_code' με τον επόμενο κώδικα Python που χρειάζεται προκειμένου "
    "να προχωρήσεις το σχέδιο, ή κάλεσε 'finish' αν έχεις ήδη ένα ικανοποιητικό, ήδη "
    "υπολογισμένο αποτέλεσμα να αναφέρεις."
)

REVIEWER_INSTRUCTIONS = (
    "Είσαι ο reviewer ενός coding agent — ελέγχεις τον κώδικα ΠΡΙΝ εκτελεστεί. Ψάξε για: "
    "obvious bugs/typos, missing imports, λάθος λογική σε σχέση με τον στόχο, ή χρήση "
    "απαγορευμένων modules (os, sys, subprocess, socket, shutil, requests, urllib). "
    "Απάντα ΜΟΝΟ με 'APPROVE' αν ο κώδικας είναι εντάξει να τρέξει, ή 'REJECT: <σύντομος "
    "λόγος>' αν όχι."
)


def _extract_json_list(response: str) -> list[str]:
    match = re.search(r"\[.*\]", response, re.DOTALL)
    text = match.group(0) if match else response
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    if isinstance(parsed, list) and all(isinstance(s, str) for s in parsed):
        return parsed[:MAX_PLAN_STEPS]
    return []


def plan_steps(goal: str) -> list[str]:
    """Planner: breaks `goal` into a short list of steps. Falls back to
    treating the whole goal as a single step if the LLM doesn't return
    parseable JSON — the loop still works either way, it just won't have
    an intermediate breakdown to show."""
    prompt = f"{PLANNER_INSTRUCTIONS}\n\nΣτόχος: {goal}"
    response = complete(prompt, max_tokens=300)
    steps = _extract_json_list(response)
    return steps if steps else [goal]


def review_code(goal: str, code: str) -> tuple[bool, str]:
    """Reviewer: vets a proposed code snippet before it ever reaches the
    sandbox. Returns (approved, feedback) — feedback is empty when approved."""
    prompt = (
        f"{REVIEWER_INSTRUCTIONS}\n\nΣτόχος: {goal}\n\n"
        f"Κώδικας προς έλεγχο:\n```python\n{code}\n```"
    )
    verdict = complete(prompt, max_tokens=200).strip()
    if verdict.upper().startswith("APPROVE"):
        return True, ""
    reason = verdict.split(":", 1)[1].strip() if ":" in verdict else verdict
    return False, reason or "Ο reviewer απέρριψε τον κώδικα χωρίς συγκεκριμένο λόγο."


def _build_coder_prompt(goal: str, plan: list[str], transcript: list[str]) -> str:
    plan_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(plan))
    history_text = "\n\n".join(transcript) if transcript else "(καμία ενέργεια ακόμα)"
    return (
        f"{CODER_INSTRUCTIONS}\n\nΣτόχος: {goal}\n\nΣχέδιο:\n{plan_text}\n\n"
        f"Μέχρι στιγμής:\n{history_text}"
    )


def run_agent_stream(goal: str):
    """
    Generator over the full multi-agent trace. Yields:
      ("plan", {"steps": [...]})                                          — once, first
      ("code", {"attempt": int, "code": str})                             — every Coder run_code call
      ("review", {"attempt": int, "approved": bool, "feedback": str})     — Reviewer verdict per attempt
      ("error", {"attempt": int, "message": str})                        — only if approved code then fails at runtime
      ("result", {"success", "stdout", "image_bytes", "attempts",
                   "summary"?, "error"?, "sandbox_backend"})              — exactly once, last
    """
    plan = plan_steps(goal)
    yield ("plan", {"steps": plan})

    transcript: list[str] = []
    attempt = 0
    last_stdout, last_image_bytes, last_backend = "", None, None

    for _ in range(MAX_TOOL_CALLS):
        prompt = _build_coder_prompt(goal, plan, transcript)
        response = call_with_tools(prompt, TOOLS, max_tokens=1200)
        tool_call = response["tool_call"]

        if tool_call is None or tool_call["name"] == "finish":
            summary = None
            if tool_call is not None:
                summary = tool_call["input"].get("summary")
            if not summary:
                summary = response["text"] or "Ολοκληρώθηκε."
            yield ("result", {
                "success": True,
                "stdout": last_stdout,
                "image_bytes": last_image_bytes,
                "attempts": attempt,
                "summary": summary,
                "sandbox_backend": last_backend,
            })
            return

        # tool_call["name"] == "run_code"
        attempt += 1
        code = tool_call["input"].get("code", "")
        yield ("code", {"attempt": attempt, "code": code})

        approved, feedback = review_code(goal, code)
        yield ("review", {"attempt": attempt, "approved": approved, "feedback": feedback})

        if not approved:
            transcript.append(
                f"Προσπάθεια {attempt} — κώδικας:\n{code}\nΟ reviewer τον ΑΠΕΡΡΙΨΕ: {feedback}"
            )
            continue  # no sandbox execution spent on rejected code

        result = run_python(code)
        last_backend = result.get("backend")

        if result["success"]:
            last_stdout = result["stdout"]
            last_image_bytes = result["image_bytes"]
            transcript.append(
                f"Προσπάθεια {attempt} — κώδικας:\n{code}\n"
                f"Ο reviewer ενέκρινε. Η εκτέλεση ΠΕΤΥΧΕ. stdout:\n{result['stdout']}"
            )
        else:
            yield ("error", {"attempt": attempt, "message": result["stderr"]})
            transcript.append(
                f"Προσπάθεια {attempt} — κώδικας:\n{code}\n"
                f"Ο reviewer ενέκρινε, αλλά η εκτέλεση ΑΠΕΤΥΧΕ με σφάλμα:\n{result['stderr']}"
            )

    # Exhausted MAX_TOOL_CALLS without the Coder ever calling finish.
    have_result = bool(last_stdout or last_image_bytes)
    yield ("result", {
        "success": have_result,
        "stdout": last_stdout,
        "image_bytes": last_image_bytes,
        "attempts": attempt,
        "summary": None,
        "error": None if have_result else "Ο agent δεν κατάφερε να ολοκληρώσει μέσα στο όριο ενεργειών.",
        "sandbox_backend": last_backend,
    })

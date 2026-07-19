"""
Executes LLM-generated Python for the Action Agent (services/code_agent.py).

Two execution backends, tried in order:

1. Docker (`_run_docker`) — a real container per run: `--network none`,
   memory/CPU/pids limits, no inherited host environment (so no secrets to
   leak in the first place), nothing persists between runs. This is a
   genuine isolation boundary, not just a convention. Used automatically
   whenever the `docker` CLI is on PATH, the daemon responds, and the
   sandbox image (AGENT_SANDBOX_IMAGE) has been built — see
   backend/sandbox.Dockerfile for the one-time build step.
2. Subprocess (`_run_subprocess`) — the original implementation, used as a
   fallback when Docker isn't available (e.g. no Docker Desktop running).
   It isolates via a fresh temp dir, a stripped/secret-free environment,
   and a wall-clock timeout, but it's demo-grade: a determined adversary
   running in the same OS as the backend process is not truly contained.

Both backends share the same static source scan (`_static_safety_check`)
as a first line of defense, and both report which backend actually ran
(`result["backend"]`) so the UI can be honest about the isolation level in
effect for a given execution — see README for the full tradeoff writeup.
"""
import os
import shutil
import subprocess
import sys
import tempfile

TIMEOUT_SECONDS = int(os.getenv("AGENT_SANDBOX_TIMEOUT", 15))
DOCKER_IMAGE = os.getenv("AGENT_SANDBOX_IMAGE", "rag-agent-sandbox")

# Cheap defense-in-depth: reject code containing these substrings before
# ever executing it, on *either* backend. Not exhaustive (a determined
# adversary can dodge substring matching), but blocks the obvious escape
# hatches an LLM might reach for even when not explicitly asked to.
BLOCKED_PATTERNS = [
    "import os", "import sys", "import subprocess", "import socket",
    "import shutil", "import requests", "import urllib", "__import__",
    "eval(", "exec(", "open(\"/", "open('/",
]

_docker_available_cache: bool | None = None


def _static_safety_check(code: str) -> str | None:
    """Returns an error message if `code` contains a disallowed pattern,
    else None."""
    for token in BLOCKED_PATTERNS:
        if token in code:
            return f"Generated code uses a disallowed pattern: `{token}`."
    return None


def _docker_available() -> bool:
    """
    True only if all three hold: the `docker` CLI exists, its daemon
    actually responds (Docker Desktop might be installed but not running),
    and the sandbox image has been built locally. Result is cached for the
    life of the process — call reset_docker_availability_cache() (tests
    only) to force a re-check.
    """
    global _docker_available_cache
    if _docker_available_cache is not None:
        return _docker_available_cache

    if shutil.which("docker") is None:
        _docker_available_cache = False
        return False

    try:
        daemon_ok = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=3
        ).returncode == 0
    except Exception:
        daemon_ok = False

    if not daemon_ok:
        _docker_available_cache = False
        return False

    try:
        image_ok = subprocess.run(
            ["docker", "image", "inspect", DOCKER_IMAGE], capture_output=True, timeout=3
        ).returncode == 0
    except Exception:
        image_ok = False

    _docker_available_cache = image_ok
    return image_ok


def reset_docker_availability_cache() -> None:
    """Test-only hook — forces the next _docker_available() call to
    re-probe instead of returning the cached result."""
    global _docker_available_cache
    _docker_available_cache = None


def _read_output_image(workdir: str) -> bytes | None:
    image_path = os.path.join(workdir, "output.png")
    if os.path.exists(image_path):
        with open(image_path, "rb") as f:
            return f.read()
    return None


def _run_subprocess(code: str) -> dict:
    with tempfile.TemporaryDirectory() as workdir:
        script_path = os.path.join(workdir, "script.py")
        # Explicit UTF-8: without it, open()'s default is the OS locale
        # encoding, which on Windows is a codepage (e.g. cp1252) that can't
        # represent Greek text or the € sign — it would silently write the
        # wrong bytes, and Python 3's source-file reader (which always
        # assumes UTF-8 per PEP 3120) would then fail to parse its own
        # generated script with a confusing SyntaxError/UnicodeDecodeError.
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        clean_env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONDONTWRITEBYTECODE": "1",
            "MPLBACKEND": "Agg",  # headless matplotlib — no display available
            "PYTHONIOENCODING": "utf-8",  # child's own stdout/stderr — same Windows-codepage issue otherwise
        }

        try:
            proc = subprocess.run(
                [sys.executable, script_path],
                cwd=workdir,
                env=clean_env,
                capture_output=True,
                encoding="utf-8",
                errors="replace",  # never crash the agent loop over a decode hiccup in the child's own output
                timeout=TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Execution timed out after {TIMEOUT_SECONDS}s.",
                "image_bytes": None,
            }

        return {
            "success": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "image_bytes": _read_output_image(workdir),
        }


def _run_docker(code: str) -> dict:
    with tempfile.TemporaryDirectory() as workdir:
        script_path = os.path.join(workdir, "script.py")
        # Same UTF-8 note as _run_subprocess: this file is written by the
        # host (Windows) Python process regardless of whether Docker or a
        # bare subprocess runs it, so the encoding fix applies here too.
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        cmd = [
            "docker", "run", "--rm",
            "--network", "none",            # no network access at all
            "--memory", "256m",
            "--cpus", "0.5",
            "--pids-limit", "64",           # blocks fork-bombs
            "-e", "MPLBACKEND=Agg",
            "-e", "PYTHONIOENCODING=utf-8",
            "-v", f"{workdir}:/sandbox:rw",
            "-w", "/sandbox",
            DOCKER_IMAGE,
            "python", "script.py",
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT_SECONDS + 5,  # container start/stop overhead on top of the script's own budget
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Execution timed out after {TIMEOUT_SECONDS}s.",
                "image_bytes": None,
            }

        return {
            "success": proc.returncode == 0,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "image_bytes": _read_output_image(workdir),
        }


def run_python(code: str) -> dict:
    """
    Runs `code` and returns:
      {"success": bool, "stdout": str, "stderr": str,
       "image_bytes": bytes | None, "backend": "docker" | "subprocess" | "blocked"}
    If the code saves a file named exactly "output.png" in its working
    directory (e.g. via matplotlib's plt.savefig("output.png")), it's read
    back and returned as image_bytes.
    """
    safety_error = _static_safety_check(code)
    if safety_error:
        return {
            "success": False, "stdout": "", "stderr": safety_error,
            "image_bytes": None, "backend": "blocked",
        }

    if _docker_available():
        result = _run_docker(code)
        result["backend"] = "docker"
        return result

    result = _run_subprocess(code)
    result["backend"] = "subprocess"
    return result

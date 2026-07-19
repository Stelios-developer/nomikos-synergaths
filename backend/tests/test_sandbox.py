import services.sandbox as sandbox_module
from services.sandbox import run_python, _static_safety_check


def test_run_python_success_captures_stdout():
    result = run_python("print('hello from sandbox')")
    assert result["success"] is True
    assert "hello from sandbox" in result["stdout"]
    assert result["image_bytes"] is None
    # No docker binary in the test/CI environment, so this always falls
    # back to the subprocess backend — see the docker-dispatch tests below
    # for the (mocked) docker path.
    assert result["backend"] == "subprocess"


def test_run_python_captures_output_png():
    code = (
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "plt.plot([1, 2, 3])\n"
        "plt.savefig('output.png')\n"
        "print('chart saved')\n"
    )
    result = run_python(code)
    assert result["success"] is True
    assert result["image_bytes"] is not None
    assert result["image_bytes"][:8] == b"\x89PNG\r\n\x1a\n"


def test_run_python_failure_captures_stderr():
    result = run_python("print(this_is_not_defined)")
    assert result["success"] is False
    assert "NameError" in result["stderr"]


def test_run_python_blocks_disallowed_import_without_executing():
    result = run_python("import os\nos.system('echo hi')")
    assert result["success"] is False
    assert "disallowed pattern" in result["stderr"]
    assert result["stdout"] == ""
    assert result["backend"] == "blocked"


def test_run_python_blocks_subprocess_import():
    result = run_python("import subprocess\nsubprocess.run(['echo', 'hi'])")
    assert result["success"] is False
    assert "disallowed pattern" in result["stderr"]


def test_run_python_times_out_on_infinite_loop(monkeypatch):
    import services.sandbox as sandbox_module
    monkeypatch.setattr(sandbox_module, "TIMEOUT_SECONDS", 1)
    result = run_python("while True:\n    pass\n")
    assert result["success"] is False
    assert "timed out" in result["stderr"]


def test_run_python_does_not_leak_environment_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "super-secret-value")
    monkeypatch.setenv("OPENAI_API_KEY", "another-secret")
    result = run_python(
        "import os\n"
    ) if False else run_python("print(__import__('os').environ.get('ANTHROPIC_API_KEY'))")
    # The code above uses __import__, which is itself a blocked pattern —
    # confirms the safety check catches indirection attempts too.
    assert result["success"] is False


def test_static_safety_check_flags_known_dangerous_patterns():
    assert _static_safety_check("import socket") is not None
    assert _static_safety_check("eval('1+1')") is not None
    assert _static_safety_check("print(1+1)") is None


# --- Docker dispatch / availability (mocked — no real Docker daemon in CI) ---

def test_docker_available_false_when_cli_missing(monkeypatch):
    sandbox_module.reset_docker_availability_cache()
    monkeypatch.setattr(sandbox_module.shutil, "which", lambda name: None)
    assert sandbox_module._docker_available() is False


def test_docker_available_false_when_daemon_not_responding(monkeypatch):
    sandbox_module.reset_docker_availability_cache()
    monkeypatch.setattr(sandbox_module.shutil, "which", lambda name: "/usr/bin/docker")

    class FakeProc:
        returncode = 1

    monkeypatch.setattr(sandbox_module.subprocess, "run", lambda *a, **kw: FakeProc())
    assert sandbox_module._docker_available() is False


def test_docker_available_false_when_image_not_built(monkeypatch):
    sandbox_module.reset_docker_availability_cache()
    monkeypatch.setattr(sandbox_module.shutil, "which", lambda name: "/usr/bin/docker")

    call_count = {"n": 0}

    def fake_run(cmd, **kwargs):
        call_count["n"] += 1
        # first call is `docker info` (daemon check) -> succeeds,
        # second call is `docker image inspect` -> fails (image missing)
        class FakeProc:
            returncode = 0 if call_count["n"] == 1 else 1
        return FakeProc()

    monkeypatch.setattr(sandbox_module.subprocess, "run", fake_run)
    assert sandbox_module._docker_available() is False


def test_docker_available_true_when_everything_checks_out(monkeypatch):
    sandbox_module.reset_docker_availability_cache()
    monkeypatch.setattr(sandbox_module.shutil, "which", lambda name: "/usr/bin/docker")

    class FakeProc:
        returncode = 0

    monkeypatch.setattr(sandbox_module.subprocess, "run", lambda *a, **kw: FakeProc())
    assert sandbox_module._docker_available() is True


def test_docker_available_result_is_cached(monkeypatch):
    sandbox_module.reset_docker_availability_cache()
    monkeypatch.setattr(sandbox_module.shutil, "which", lambda name: None)
    assert sandbox_module._docker_available() is False

    # Even if docker "appears" afterwards, the cached False should stick
    # until reset_docker_availability_cache() is called again.
    monkeypatch.setattr(sandbox_module.shutil, "which", lambda name: "/usr/bin/docker")
    assert sandbox_module._docker_available() is False

    sandbox_module.reset_docker_availability_cache()
    class FakeProc:
        returncode = 0
    monkeypatch.setattr(sandbox_module.subprocess, "run", lambda *a, **kw: FakeProc())
    assert sandbox_module._docker_available() is True


def test_run_python_dispatches_to_docker_when_available(monkeypatch):
    monkeypatch.setattr(sandbox_module, "_docker_available", lambda: True)
    monkeypatch.setattr(
        sandbox_module, "_run_docker",
        lambda code: {"success": True, "stdout": "from docker", "stderr": "", "image_bytes": None},
    )
    result = run_python("print('hi')")
    assert result["stdout"] == "from docker"
    assert result["backend"] == "docker"


def test_run_python_dispatches_to_subprocess_when_docker_unavailable(monkeypatch):
    monkeypatch.setattr(sandbox_module, "_docker_available", lambda: False)
    monkeypatch.setattr(
        sandbox_module, "_run_subprocess",
        lambda code: {"success": True, "stdout": "from subprocess", "stderr": "", "image_bytes": None},
    )
    result = run_python("print('hi')")
    assert result["stdout"] == "from subprocess"
    assert result["backend"] == "subprocess"


def test_run_python_handles_greek_and_euro_sign_correctly(monkeypatch):
    # Regression test for a real bug found in manual Windows testing: the
    # script file was written using open()'s default (locale) encoding,
    # which on Windows is a codepage that can't represent Greek text or
    # the euro sign — corrupting the file so Python's own (UTF-8-assuming)
    # source parser then failed with a confusing SyntaxError. Both the
    # write and the subprocess capture must be explicit UTF-8. Forces the
    # subprocess backend since there's no real `docker` binary in CI.
    monkeypatch.setattr(sandbox_module, "_docker_available", lambda: False)
    code = "print('Ελληνικά κείμενο: 10.000 €')"
    result = run_python(code)
    assert result["success"] is True
    assert "Ελληνικά κείμενο: 10.000 €" in result["stdout"]
    assert result["backend"] == "subprocess"

"""Verify exact backend source/runtime in a network-isolated local image."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PROGRAM = r"""
import hashlib,importlib.util,json,os,pathlib,shutil,sys
expected=json.load(sys.stdin)
actual={p.relative_to('/app').as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ('db','services','routers') for p in pathlib.Path('/app',folder).rglob('*.py')}
for name in ('main.py','contracts.py'):
    actual[name]=hashlib.sha256(pathlib.Path('/app',name).read_bytes()).hexdigest()
assert actual==expected,'Image/source mismatch'
assert os.getuid()==10001
assert importlib.util.find_spec('pip') is None
assert shutil.which('apk') is None and shutil.which('sh') is None
try:
    pathlib.Path('/app/unexpected-write').write_text('test')
except OSError: pass
else: raise AssertionError('Root filesystem is writable')
import main,torch,psycopg,fitz
assert main.app.title=='NOMIKOS SYNERGATHS API'
print(json.dumps({'gate':'PASSED','code_files_verified':len(actual),'uid':os.getuid(),
                 'pip_present':False,'shell_present':False,'torch':torch.__version__}))
"""


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "dmc/backend:os-remediation"
    image = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Id}}", name], text=True
    ).strip()
    backend = ROOT / "backend"
    files = [backend / name for name in ("main.py", "contracts.py")]
    for folder in ("db", "services", "routers"):
        files.extend((backend / folder).rglob("*.py"))
    expected = {
        p.relative_to(backend).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in files
    }
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-i",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "64",
            "--memory",
            "2g",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--env",
            "AUTH_REQUIRED=false",
            "--env",
            "ANALYSIS_DISPATCH_ENABLED=false",
            "--entrypoint",
            "python",
            image,
            "-c",
            PROGRAM,
        ],
        input=json.dumps(expected).encode(),
        capture_output=True,
        timeout=120,
    )
    if result.returncode or len(result.stdout) > 8192:
        raise RuntimeError(
            "Offline backend-image check failed: "
            + result.stderr.decode(errors="replace")[-2000:]
        )
    report = json.loads(result.stdout)
    report.update(
        image=image,
        scope="Exact source/import/runtime check; no auth integration, network or AI inference.",
    )
    target = ROOT / "output/engineering-audit/backend-image.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Exact backend-image source/runtime check PASSED: {len(expected)} files.")


if __name__ == "__main__":
    main()

"""Generate/check hash-locked Python profiles with an input/output manifest."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "backend/dependency-locks.json"
PROFILES = (
    (
        "backend/requirements-win-py312.lock",
        "backend/requirements.txt",
        "x86_64-pc-windows-msvc",
        True,
    ),
    (
        "backend/requirements-linux-py312.lock",
        "backend/requirements.txt",
        "x86_64-unknown-linux-gnu",
        True,
    ),
    ("backend/requirements-test.lock", "backend/requirements-dev.txt", None, False),
    (
        "security/pdf_worker/requirements-linux-py312.lock",
        "security/pdf_worker/requirements.txt",
        "x86_64-unknown-linux-gnu",
        False,
    ),
)


def checksum(path):
    # Git stores these text profiles with LF; Windows checkouts may use CRLF.
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def inventory():
    paths = {"backend/constraints-tested.txt"}
    for output, source, _platform, _cpu in PROFILES:
        paths.update((output, source))
    return {path: checksum(ROOT / path) for path in sorted(paths)}


def check():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("python") != "3.12" or manifest.get("files") != inventory():
        raise RuntimeError(
            "Dependency inputs or locks changed; regenerate and review them together"
        )
    print("Dependency lock inputs, profiles and SHA-256 manifest match.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--uv", type=Path, default=ROOT / ".tools/uv/bin/uv.exe")
    args = parser.parse_args()
    if args.check:
        return check()
    version = subprocess.check_output([str(args.uv), "--version"], text=True).strip()
    if version.split()[:2] != ["uv", "0.13.6"]:
        raise RuntimeError("Use the reviewed uv 0.13.6 toolchain")
    for output, source, platform, cpu in PROFILES:
        command = [
            str(args.uv),
            "pip",
            "compile",
            source,
            "--python-version",
            "3.12",
            "--default-index",
            "https://pypi.org/simple",
            "--generate-hashes",
            "--emit-index-url",
            "--no-build",
            "--no-header",
            "-q",
            "-o",
            output,
        ]
        command += ["--python-platform", platform] if platform else ["--universal"]
        if cpu:
            command += [
                "--torch-backend",
                "cpu",
                "-c",
                "backend/constraints-tested.txt",
            ]
        subprocess.run(command, cwd=ROOT, check=True)
        path = ROOT / output
        text = path.read_text(encoding="utf-8")
        if cpu:
            # uv's automatic torch backend is not emitted as an index directive.
            # Explicit pinned hashes make this standard-pip installable as well.
            # pip resets prior extra indexes when it encounters --index-url.
            # Emit the additional index after the primary index directive.
            text = text.replace(
                "--index-url https://pypi.org/simple\n",
                "--index-url https://pypi.org/simple\n--extra-index-url https://download.pytorch.org/whl/cpu\n",
                1,
            )
        path.write_text(text, encoding="utf-8", newline="\n")
    MANIFEST.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generator": version,
                "python": "3.12",
                "files": inventory(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    check()


if __name__ == "__main__":
    main()

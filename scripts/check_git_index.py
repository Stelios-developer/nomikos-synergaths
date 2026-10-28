"""Read-only Git-index release check. Never print secret values.

Runs locally after selective staging and in CI against the checked-out index.
This is a limited safety check, not a replacement for a dedicated secret scanner.
"""
import re
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
TOKEN_PATTERNS = {
    "provider token": rb"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,}",
    "GitHub token": rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})",
    "AWS access key": rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    "private key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def forbidden_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    name = parts[-1].lower()
    if name.startswith(".env") and not name.endswith(".example"):
        return True
    if name.endswith((".log", ".pdf", ".sqlite", ".sqlite3", ".db", ".aesgcm", ".dpapi", ".pem", ".key", ".p12", ".pfx", ".jks", ".tfstate", ".tfplan", ".tfvars")):
        return True
    if any(part in {"node_modules", "venv", ".venv", "__pycache__", ".pytest_cache", "output", "tmp", "storage", "chroma_db", ".aws", ".runtime", ".tools", ".terraform", "playwright-report", "test-results"} for part in parts):
        return True
    if any(part.startswith(".codex-pytest-") for part in parts):
        return True
    return path.startswith("n8n/") and (name.endswith(".export.json") or name.startswith("exported-"))


def configured_secrets() -> list[tuple[str, bytes]]:
    found = []
    for path in ("backend/.env", "auth-service/.env", "n8n/.env", "security/pdf_worker/.env", "infra/vector/.env"):
        file = ROOT / path
        if not file.is_file():
            continue
        for line in file.read_text(encoding="utf-8-sig").splitlines():
            match = re.match(r"\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*)$", line)
            if not match or not re.search(r"SECRET|TOKEN|PASSWORD|API_KEY", match[1]):
                continue
            value = match[2].strip()
            if value.startswith(("'", '"')):
                value = value[1:value.rfind(value[0])]
            else:
                value = re.split(r"\s+#", value, maxsplit=1)[0]
            if len(value) >= 12 and not re.search(r"placeholder|your[-_]|change[-_]|replace[-_]", value, re.I):
                found.append((match[1], value.encode()))
    return found


def main() -> int:
    findings = []
    secrets = configured_secrets()
    entries = [entry for entry in git("ls-files", "--stage", "-z").split(b"\0") if entry]
    for entry in entries:
        metadata, raw_path = entry.split(b"\t", 1)
        mode, object_id, stage = metadata.decode().split()
        path = raw_path.decode("utf-8")
        if stage != "0":
            findings.append((path, "unresolved merge conflict"))
            continue
        if forbidden_path(path):
            findings.append((path, "private or generated runtime artifact"))
        if mode in {"120000", "160000"}:
            findings.append((path, "symlink or embedded repository requires manual review"))
            continue
        data = git("cat-file", "blob", object_id)
        if b"\0" in data:
            continue
        for label, pattern in TOKEN_PATTERNS.items():
            if re.search(pattern, data):
                findings.append((path, label))
        for key, value in secrets:
            if value in data:
                findings.append((path, "configured secret match: " + key))
    for path, reason in sorted(set(findings)):
        print(f"BLOCK: {path}: {reason}")
    print(f"Checked {len(entries)} indexed entries; {len(set(findings))} findings. Secret values were not printed.")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())

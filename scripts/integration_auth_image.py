"""Synthetic offline auth image smoke; no login, real DB, email or credentials."""

import json
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROGRAM = r"""
import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
let input=''; for await (const part of process.stdin) input+=part;
const config=JSON.parse(input); Object.assign(process.env,config.env);
assert.notEqual(process.getuid(),0);
assert.equal(existsSync('/usr/local/bin/npm'),false);
assert.throws(()=>{ const fs=process.getBuiltinModule('node:fs');fs.writeFileSync('/app/unexpected-write','test'); });
if(config.reject) {
  await assert.rejects(import('./src/auth.ts'), /mandatory in production|requires RESEND_API_KEY/);
  console.log(JSON.stringify({gate:'PASSED',scenario:config.name,rejected:true}));
} else {
  const {auth,pool}=await import('./src/auth.ts');
  assert.equal(auth.options.appName,'Documents Made Clear');
  if(config.production) assert.equal(auth.options.advanced.defaultCookieAttributes.secure,true);
  else {
    await import('./src/server.ts');
    const response=await fetch('http://127.0.0.1:3001/health');
    assert.equal(response.status,200);
    assert.deepEqual(await response.json(),{status:'ok'});
    const session=await fetch('http://127.0.0.1:3001/api/auth/get-session');
    assert.equal(session.status,500);
    assert.deepEqual(await session.json(),{detail:'Authentication service error.'});
  }
  await pool.end();
  console.log(JSON.stringify({gate:'PASSED',scenario:config.name,uid:process.getuid()}));
}
process.exit(0);
"""


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "dmc/auth:security-20261027-final"
    # Resolve an already-built local image before running; do not pull unreviewed code.
    image = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Id}}", name], text=True
    ).strip()
    common = {
        "DATABASE_URL": "postgresql://fixture:synthetic@127.0.0.1:1/fixture",
        "BETTER_AUTH_SECRET": secrets.token_urlsafe(48),
        "APP_ENV": "development",
        "NODE_ENV": "development",
        "APP_ORIGIN": "http://127.0.0.1:5198",
        "BETTER_AUTH_URL": "http://127.0.0.1:3001",
        "AUTH_HOST": "127.0.0.1",
        "AUTH_PORT": "3001",
        "REQUIRE_EMAIL_VERIFICATION": "false",
    }
    scenarios = [{"name": "local-health-and-unavailable-database", "env": common}]
    for flag in ("NODE_ENV", "APP_ENV"):
        scenarios.append(
            {
                "name": flag + "-guards",
                "reject": True,
                "env": {**common, flag: "production"},
            }
        )
    scenarios.append(
        {
            "name": "production-secure-cookie-config",
            "production": True,
            "env": {
                **common,
                "NODE_ENV": "production",
                "APP_ENV": "production",
                "APP_ORIGIN": "https://documents.test",
                "BETTER_AUTH_URL": "https://auth.documents.test",
                "REQUIRE_EMAIL_VERIFICATION": "true",
                "RESEND_API_KEY": "synthetic-not-a-real-key",
                "EMAIL_FROM": "Documents Made Clear <security@documents.test>",
            },
        }
    )
    reports = []
    for scenario in scenarios:
        command = [
            "docker",
            "run",
            "--rm",
            "--interactive",
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
            "256m",
            "--tmpfs",
            "/tmp:rw,nosuid,noexec,size=32m",
            "--entrypoint",
            "node",
            image,
            "--import",
            "tsx",
            "--input-type=module",
            "--eval",
            PROGRAM,
        ]
        result = subprocess.run(
            command,
            input=json.dumps(scenario).encode(),
            capture_output=True,
            timeout=40,
        )
        if result.returncode or len(result.stdout) > 8192:
            raise RuntimeError(
                "Synthetic auth-image smoke failed; no private diagnostics exported"
            )
        reports.append(json.loads(result.stdout.decode().strip().splitlines()[-1]))
    report = {
        "gate": "PASSED",
        "image": image,
        "scenarios": reports,
        "network": "none",
        "read_only": True,
        "scope": "Startup/configuration, health and fail-closed unavailable DB only; no live DB/login/email integration.",
    }
    target = ROOT / "output/engineering-audit/auth-image.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        "Exact auth image: four offline startup/HTTP/production-guard checks PASSED; no live login or email."
    )


if __name__ == "__main__":
    main()

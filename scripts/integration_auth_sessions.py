"""Real Better Auth cookies versus the backend, using a fresh disposable DB.

Creates synthetic accounts only; never reads/writes the active auth database,
sends email or prints test cookies/passwords/database credentials.
"""

import asyncio
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from types import SimpleNamespace
from urllib.parse import quote
import uuid

from setup_vector_database import ROOT, local_connections
import psycopg
from psycopg import sql

PROGRAM = r"""
let input='';for await(const part of process.stdin) input+=part;
const config=JSON.parse(input);
Object.assign(process.env,config.env);
const {auth,pool}=await import('./src/auth.ts');
const {getMigrations}=await import('better-auth/db/migration');
const assert=(value)=>{if(!value) throw new Error('Synthetic auth assertion failed');};
const origin=process.env.APP_ORIGIN;
const call=(path,method='GET',body,cookie)=>auth.handler(new Request(process.env.BETTER_AUTH_URL+'/api/auth'+path,
  {method,headers:{origin,'content-type':'application/json',...(cookie?{cookie}:{})},...(body?{body:JSON.stringify(body)}:{})}));
try {
  if(config.phase==='create') {
    const migration=await getMigrations(auth.options);
    await migration.runMigrations();
    const created=await call('/sign-up/email','POST',{name:'Synthetic Auth Fixture',email:'synthetic@example.test',password:config.password});
    assert(created.status===200);
    const data=await created.json();
    const cookie=created.headers.getSetCookie().map(item=>item.split(';',1)[0]).join('; ');
    assert(cookie.includes('session_token='));
    const session=await call('/get-session','GET',undefined,cookie);
    assert(session.status===200 && (await session.json()).user.id===data.user.id);
    const wrong=await call('/sign-in/email','POST',{email:'synthetic@example.test',password:'Wrong-synthetic-password-42'});
    assert(wrong.status===401);
    console.log(JSON.stringify({cookie,user_id:data.user.id}));
  } else {
    const response=await call('/sign-out','POST',{},config.cookie);assert(response.status===200);
    const session=await call('/get-session','GET',undefined,config.cookie);
    assert(session.status===200 && await session.json()===null);
    console.log(JSON.stringify({signed_out:true}));
  }
} finally {await pool.end();}
"""


def node(config):
    executable = shutil.which("node")
    if not executable:
        raise RuntimeError("Install the project Node runtime first")
    checked = subprocess.run(
        [executable, "--import", "tsx", "--input-type=module", "-e", PROGRAM],
        cwd=ROOT / "auth-service",
        input=json.dumps(config).encode(),
        capture_output=True,
        timeout=45,
    )
    if checked.returncode:
        # Subprocess output may contain sensitive test material; never echo it.
        raise RuntimeError(
            "Isolated Better Auth session check failed; no private output exported"
        )
    return json.loads(checked.stdout.splitlines()[-1])


async def backend_check(cookie, user_id, *, denied=False):
    from fastapi import HTTPException
    from starlette.requests import Request
    from services.authentication import (
        start_auth_pool,
        close_auth_pool,
        require_authenticated_user,
    )

    app = SimpleNamespace(state=SimpleNamespace())
    await start_auth_pool(app)
    try:
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/",
                "headers": [(b"cookie", cookie.encode())],
                "app": app,
            }
        )
        try:
            user = await require_authenticated_user(request)
        except HTTPException as exc:
            assert denied and exc.status_code == 401
        else:
            assert not denied and user.id == user_id
    finally:
        await close_auth_pool(app)


def main():
    owner, _ = local_connections()
    name = "dmc_auth_it_" + uuid.uuid4().hex
    uri = (
        f"postgresql://{quote(owner['user'], safe='')}:{quote(owner['password'], safe='')}"
        f"@127.0.0.1:{owner['port']}/{name}"
    )
    secret = secrets.token_urlsafe(48)
    env = {
        "DATABASE_URL": uri,
        "BETTER_AUTH_SECRET": secret,
        "AUTH_REQUIRED": "true",
        "REQUIRE_VERIFIED_EMAIL": "false",
        "REQUIRE_EMAIL_VERIFICATION": "false",
        "APP_ENV": "development",
        "NODE_ENV": "development",
        "APP_ORIGIN": "http://127.0.0.1:5174",
        "BETTER_AUTH_URL": "http://127.0.0.1:3002",
        "RESEND_API_KEY": "",
        "EMAIL_FROM": "",
    }
    os.environ.update(env)
    with psycopg.connect(**owner, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            created = node(
                {"phase": "create", "env": env, "password": secrets.token_urlsafe(24)}
            )
            asyncio.run(backend_check(created["cookie"], created["user_id"]))
            tampered = "; ".join(
                item + "x" if ".session_token=" in item else item
                for item in created["cookie"].split("; ")
            )
            assert tampered != created["cookie"]
            asyncio.run(backend_check(tampered, created["user_id"], denied=True))
            node({"phase": "signout", "env": env, "cookie": created["cookie"]})
            asyncio.run(
                backend_check(created["cookie"], created["user_id"], denied=True)
            )
        finally:
            if not name.startswith("dmc_auth_it_") or len(name) != 44:
                raise RuntimeError("Invalid temporary auth database cleanup target")
            admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
    report = {
        "gate": "PASSED",
        "checks": [
            "signup/session with real cookies and SQL",
            "backend accepts real signed cookie",
            "wrong password rejected",
            "tampered cookie rejected",
            "signout revokes session",
            "backend rejects revoked session",
        ],
        "scope": "Disposable database and synthetic account only; no email, user database or AI calls.",
    }
    target = ROOT / "output/engineering-audit/auth-sessions.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf8")
    print(
        "Real Better Auth/backend signed-cookie, tampering and revocation checks PASSED; disposable DB removed."
    )


if __name__ == "__main__":
    main()

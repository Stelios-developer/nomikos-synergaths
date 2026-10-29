# Local validation record

## Role and extraction follow-up, 2026-10-29

The Greek live demo identified a real error: the answer listed a Finance
Director as an owner where the synthetic policy names that role as approver.
The model-based check incorrectly reported all four units as supported. The
Greek video explicitly shows this historical failure.

The answer prompt now distinguishes owners, approvers, reviewers and notified
parties. The chat auditor splits on line boundaries, bounds the number of units,
and sends positive role claims for manual source review instead of treating a
model verdict as conclusive. A structured-output parser now rejects nested
fragments of truncated JSON; the facts stage validates the expected arrays,
retries malformed output once and blocks automatic approval if extraction needs
review. These controls are conservative and do not prove model accuracy.

Three real questions were run against two freshly indexed synthetic PDFs. The
answers distinguished the owner and approver in the tax and project examples,
and identified the two project risks and their stated mitigations. The model
auditor still returned some negative verdicts for apparently supported claims;
manual inspection remains necessary. A full rerun before the parser change
returned zero facts, obligations and deadlines despite their presence in the
source, while marking the case for review. It must not be treated as a successful
extraction. Local token accounting is an estimate; provider billing is separate.

One further full run after the JSON parser and schema change extracted six
facts, ten obligations and six deadlines from the same synthetic source. Spot
checks confirmed the 30 June and 15 July milestones and owners, but one risk
mitigation proposed 25 and 28 June dates that do not occur in the source. The
model audit nevertheless marked that run verified. The current release therefore
withholds final actions when decisions, actions or mitigations have not all been
audited; older verified cases are downgraded on read without overwriting stored
data. It also no longer copies an unrelated deadline merely because two items
share an owner. The final gate change was tested locally with mocked models; no
third full paid run is claimed. This safeguard is deliberately conservative and
does not establish that the remaining displayed findings are correct.

## OCR and retrieval follow-up, 2026-10-29

Two subsequent real AI questions used a synthetic PDF. The milestone answer
correctly identified the 30 June and 15 July dates and their owners; the risk
answer omitted three risks that continued in a neighboring chunk. The final
retrieval change was made after those calls: a no-provider check against the
newly indexed synthetic PDF confirms all four risk excerpts are now retrieved.
The model's final answer after that change has not been tested; retrieval alone
cannot establish answer correctness.

The PDF worker reconstructs and OCRs at 2x with higher JPEG quality and
Tesseract page segmentation mode 4. An exact-image test, a live gateway test,
and four additional synthetic PDF checks covered English, Greek, scanned text
and a table, including the sample's 15 July date. Hybrid retrieval adds limited
Greek/English query expansion, reserves lexical matches and includes a bounded
same-page continuation scoped to the same document and workspace. A partial
positive grader result retains the bounded candidates, prioritizing matches.
This is not general translation or a correctness guarantee.

OCR still confuses visually similar Greek/Latin characters, complex layouts may
behave differently, and review against the source remains necessary. A newly
indexed copy of the earlier synthetic demo document was created; its original
saved case was preserved. The new copy has not been analyzed by AI. The earlier
demonstration video is historical and does not validate the current changes.

## Current local completion, 2026-10-28

This section supersedes the dated checkpoints below. The three requested local
priorities are implemented and activated: Python image OS remediation, background
dispatch and safe reconciliation/cancellation of uncertain work. No production
deployment, paid AI evaluation or hosted CI run is claimed.

| Check | Result | Evidence boundary |
| --- | --- | --- |
| Backend regression, clean hash-locked environment | 269 passed | Temporary stores, mock providers, real SQLite and loopback transport faults. |
| Real PostgreSQL integration | 39 passed | Disposable DB; RLS, narrow dispatcher role, global/workspace concurrency, exact attempt/generation results, cancellation/commit serialization and actual child-process crash/restart with synthetic transport. |
| Repository/security-policy tests | 30 passed | Includes Docker image identity versus internal scanner artifact identity; incomplete inventories fail closed. |
| Frontend/auth unit tests | 29 / 6 passed | Not a live account/login/mail integration test. |
| Better Auth 1.7.14 session integration | Six checks passed | Actual signed cookies, wrong password, backend verification, tampering and sign-out revocation; synthetic account in a disposable PostgreSQL database, deleted afterward. No email. |
| Browser UI | 133 assertions per engine | Chromium, Firefox, WebKit; synthetic APIs; no live provider. |
| Accessibility | Twelve scans per engine, zero automated violations | Includes background activity/dialog; incomplete checks require manual review. |
| Frontend lint/build, auth types, static Python and actionlint | Passed | Local source checks; hosted workflows have not executed. |
| Final backend/PDF images | Zero reported OS/Python records across all severities | Current Trivy database, exact identities, no exclusions; future advisories can change results. |
| Updated auth image | Zero reported OS/Node records across all severities | The old 1.6.26 image failed the refreshed scan; client/service now pin 1.7.14, four isolated image runtime checks pass. |
| Backend image source/runtime | 53 file hashes and imports passed | Exact source, UID 10001, no pip/apk/shell, read-only root, network none; no inference. |
| PDF image | English/Greek OCR, visual CDR, malformed rejection and isolation passed | Exact pinned image and synthetic PDF. |
| Active local PDF service | Promoted and passed | Real gateway, scanner health, unauthorized/malformed rejection, CDR/OCR, in-memory harmless EICAR detection; rollback image retained, unrelated container IDs preserved. |
| Queue activation/recovery | Applied and verified | Encrypted pre-migration backup restored into a disposable DB; 46 chunks/four workspaces preserved, zero outstanding jobs at activation. |
| Running API | Health/live/ready 200 | Dispatcher-enabled readiness, restricted role/schema verified; anonymous job list rejected with 401. No real provider submission. |
| Local frontend/auth | Available on 5174 / 3002 | DMC title, auth health and actual proxy anonymous-session response verified; Shopbrain keeps 5173/3001. |
| Existing auth schema compatibility | Passed, zero DDL | Read-only migration planning requires no new tables/columns/indexes and reports no unsafe changes; existing accounts unchanged. |

Current ignored evidence is under `output/engineering-audit/`: backend/SQL/UI
test logs, `backend-image.json`, `pdf-image.json`, `pdf-service.json`,
`pdf-promotion.json`, `dispatcher-preflight.json` and `local-runtime-final.json`.
Full scan reports, image identities and CycloneDX inventories are under
`output/security/`; browser evidence is under `output/engineering-ui/<engine>/`.

The backend Linux image is a tested candidate; the active API uses the project's
Windows environment. The PDF worker image is actually installed. This is not
a clean bill of health for every supporting container or the Windows host.
Existing 157 staged changes were preserved; nothing was committed or pushed.
See [remaining gates](ROADMAP.md) for hosting/TLS/encryption, off-machine recovery,
signed releases and the user-deferred paid model evaluation.

## Historical storage checkpoint - 2026-10-27

The current storage/runtime supersedes the historical Chroma checkpoint below.
No hosted CI, cloud deployment or paid AI evaluation was executed.

| Check | Current result | Boundary |
| --- | --- | --- |
| Backend, clean hash-locked environment | 266 passed | Temporary stores, mock providers, real SQLite, real loopback faults; no paid inference. |
| Real PostgreSQL integration | 22 passed | Fresh disposable DB; forced RLS, role restrictions, ranking, rollback, concurrency, durable jobs, quotas, deadlines and document-job erasure. |
| Repository/security-policy tests | 29 passed | Includes malformed/incomplete image inventories and unfixed vulnerability rejection. |
| Frontend/auth unit tests | 29 / 6 passed | Not a live Better Auth session integration test. |
| Browser UI | 120 assertions per engine | Chromium, Firefox and WebKit; synthetic data, eight tabs and mobile widths. |
| Accessibility | Ten scans per engine, zero automated violations | Incomplete contrast entries still require manual review. |
| Frontend lint/build, auth typecheck, static Python | Passed | Current source, not hosted release evidence. |
| Fresh-environment OSV | 134 packages, zero affected package names | Only approved project package names/versions; not OS vulnerabilities. |
| Legacy vector migration | 46 owned chunks / four workspaces, checksums matched | 18 unowned chunks recovery-only; source retained. |
| Actual isolated restore | Passed | 13 encrypted archive members, three SQLite integrity checks, 46 chunks into a new disposable DB. No live restore/overwrite. |
| Offline embedding smoke | Passed, two finite 384-dimensional vectors | Cached model, no external model call or quality benchmark. |
| n8n update | Applied, encrypted backup verified, health OK | Start-node job ID expression only; retention preserved. No paid workflow triggered. |
| PDF candidate image | CDR/OCR + malformed rejection + isolation passed | Exact image, UID 10001, read-only, network none, no host volumes; synthetic PDF only. ClamAV/gateway not retested in this image check. |
| Backend candidate image | 51 source-file SHA-256 checks and offline import passed | Exact final image, UID 10001, read-only, network none; no runtime pip. |
| Auth candidate image | Four offline runtime checks passed; zero scanned OS/Node findings | Node 22.23.4; production guards, cookie configuration, health and safe DB-unavailable failure; no actual login/mail/DB integration. |
| Container security | **Failed** | Remaining Debian OS findings; no suppression. Candidate images built and scanned locally, not deployed. |

Current mechanics and limits: [storage](SECURE_STORAGE.md),
[durable analysis](DURABLE_ANALYSIS.md), [dependencies/images](DEPENDENCIES.md).
Ignored evidence remains under `output/engineering-audit/`, `output/security/`
and `output/engineering-ui/<engine>/`. Existing staging was preserved; current
unstaged/new source must be reviewed together before committing.

## Historical initial-transfer checkpoint

Date: 2026-10-27. Scope: DMC working tree after the Padel pattern transfer.
This is an executable-check record, not a certification or a model benchmark.

| Check | Result | Boundary |
| --- | --- | --- |
| Backend pytest | 237 passed | Isolated temporary stores, mock provider calls, real SQLite/embedded Chroma and loopback HTTP faults. One existing Starlette/httpx deprecation warning. |
| Repository/security policy tests | 25 passed | Boundary graph, index rules, malformed OSV/SARIF and fail-closed security policy. |
| Frontend unit tests | 28 passed | Branding, cookies/CSRF, complete body budgets, invalid HTTP/SSE, uncertain writes, resource/session races. |
| Auth tests | 6 passed | Identity/email and production flag/cookie/verification safeguards; not live identity-provider/database login. |
| Browser UI | 118 assertions per engine | Chrome/Chromium engine, Firefox, WebKit; desktop plus 320/390/768 widths; all API/auth data synthetic. |
| Accessibility | Ten scans per engine, zero violations | Eight tabs, sign-in and mobile sign-up; axe WCAG 2 A/AA, 2.1 and 2.2 tags. Retained incomplete results require manual review. |
| Frontend lint/build and auth typecheck | Passed | Working-tree source, not a published image. |
| Workflow YAML actionlint | Passed | Both workflows; hosted jobs/CodeQL have not executed. |
| npm audit, frontend and auth | Zero findings after targeted Zod update | Locked Node dependency graphs at scan time. |
| Project Python `pip check` | No broken requirements | Installed backend virtualenv after synchronized OTel updates. |
| Project OSV audit | **Failed**: one affected package name, ChromaDB 1.5.9 | 153 installed packages; four GHSA advisories plus PYSEC aliases. Production version gate remains closed. |
| Clean PDF-worker virtualenv OSV audit | Passed, 15 installed packages | After updating inherited pip to 26.2.2; Windows Python packages only, not the running Linux image or Tesseract/ClamAV/OS packages. |

Ignored local evidence lives under `output/engineering-ui/<engine>/`,
`output/security/` and `output/engineering-audit/`. Browser JSON records the
engine, version, completion, assertion count and accessibility results.
The recorded engines were Chrome 156.0.8078.48, Firefox 157.0 and WebKit 27.2.
Each retained ten incomplete color-contrast rule entries for manual review;
zero violations does not mean the automated tool decided every check. Node
tests/build ran on the available local runtime; the configured Node 22 hosted
jobs still need actual execution.
All browser screenshots are synthetic. Inventory hashes describe source
inspection scope, not test execution of Padel.

The comparisons do not reuse Padel's test totals as DMC results. No Padel
service, user record, container or deployment was changed. No actual customer
document or credential was sent to a scanner. The OSV request scope was
explicitly approved: DMC package names and versions only.

Not executed: hosted CI, signed-container release, production deployment,
full cross-service fault/recovery, real model evaluation, independent
penetration test or exhaustive manual accessibility review. These remain
tracked in the [acceptance gates](ROADMAP.md).

# Local review: claim verification, 2026-11-07

Base revision: `0df72495fb4a98d2d731fe510f0aa807ef74fcff`, with uncommitted
changes in this checkout. Tests below do not certify a future artifact or deployment.
No AI provider, hosted CI, cloud service or real user document was used.

## Reproduced and changed

Synthetic tests reproduced an auditor accepting an invented date and a relative
deadline when the model falsely returned a positive verdict. Both the on-demand
chat auditor and the case-file auditor now mark recognised temporal and role
claims as requiring source review even after a positive model verdict. Historic
verified cases containing recognised sensitive claims are downgraded on read,
without rewriting stored cases. Date/role matching is incomplete and does not
establish that other claims are correct.

## Evidence and limitations

- `pytest -q tests/test_auditor.py tests/test_document_case.py`: 31 passed on
  Windows, Python 3.12.14, existing project virtual environment, isolated pytest
  temp directory. Provider responses in these tests are mocked.
- Selected Ruff fatal checks passed on changed Python files; `git diff --check`
  passed.
- The initial sandboxed full backend and expanded safety attempts stalled and
  were interrupted. Repeated outside the sandbox with a dedicated temporary
  directory, the full `pytest -q tests` run passed 297 tests with one
  Starlette/httpx deprecation warning. PDF worker and request-security suites
  passed 26 tests with the same warning; backup-crypto unit tests passed 8.
  These are local suites using the existing environment, not hosted evidence.
- The reused Python environment contains langgraph 1.2.10, while the reviewed
  commit pins a later release. It is not a fresh lockfile installation and is
  unsuitable as evidence of a clean build or current security posture.
- Docker is reachable outside the sandbox, but real integrated services,
  PostgreSQL, Kubernetes, restore, OCR and browser flows were not tested in
  this change. Existing running containers contain unrelated projects/data.
- No manually curated 30–50-PDF corpus, independent holdout, human annotation,
  real-provider evaluation, offsite recovery, independent audit or production
  configuration has been completed. See `ROADMAP.md` and `RELEASE_RUNBOOK.md`.

To revert these local changes, discard only the reviewed diff in this checkout;
no schema/data migration is involved. Do not infer that an earlier running
service has loaded this code.

## Subsequent offline checks on 2026-11-07

- Added regression cases for Greek and English relative dates and weekdays.
  Four cases initially passed a falsely positive model verdict; they now require
  source review. The heuristic normalizes Greek accents, but is not exhaustive.
- Targeted auditor and case suites: 37 passed before the monetary guard. Full
  backend after that guard: 306 passed, one
  Starlette/httpx warning. Frontend: 33 passed; auth service: 6 passed.
  Repository tool tests: 31 passed. `npm run check` passed lock manifest consistency, repository check, selected
  Ruff checks, frontend lint/build and auth TypeScript. This reused the existing
  Windows virtual environment and installed node modules, not a clean install.
- Added source-review gating for recognized monetary amounts after three
  regression examples reproduced false positive model verdicts. The guard is
  heuristic and does not cover every way to express an amount.
- `backend/evaluation/run_claim_gate.py`: 9 development text cases with a
  mocked, overconfident auditor. Zero selected role/date/amount cases bypassed
  review, but an unsupported termination claim was still marked supported. The harness
  exits nonzero: this is an unresolved actual safety limitation, not a successful
  AI quality evaluation. There were no provider calls or PDF/OCR tests.
- Docker was reachable after sandbox escalation; no integrated stack or restore
  drill was executed. `kind` was not present on PATH. No hosting, CI dispatch,
  independent review, offsite storage, provider evaluation or new costs were
  authorized by these local tests.

## Follow-up: conservative evidence gate

The 9-case mock evaluation exposed a false positive outside the prior keyword
guards. Therefore every positive model verdict now requires human source review,
including old model-verified cases on read. An explicit negative model verdict
remains marked unsupported. No human attestation workflow is implemented: all
positive verdicts stay unverified, and case action packs are withheld rather
than automatically promoted. This is a deliberate product limitation, not proof
that the AI answer or the reviewer is correct.

- The 9-case development-only mock gate passes with zero unsupported claims
  shown as verified; this does not measure real model quality or retrieval.
- 309 backend tests passed locally; the existing Python environment differs
  from the lockfile. The real PostgreSQL/pgvector suite passed 39 tests against
  a uniquely named disposable container; cleanup was confirmed. One
  Starlette/httpx deprecation warning remains in each suite.
- 30 template-generated synthetic PDF development fixtures (24 digital, six
  image-only) were generated and checked for source text/scan detection, with
  zero failures after fixing a fixture-font encoding issue. These are not
  independently annotated; no independent holdout was created and the
  extraction check does not run OCR or retrieval.
- A separate offline synthetic OCR/CDR image smoke test passed with the local
  `dmc/pdf-worker:os-remediation` image. The previous default tag failed its
  runtime-hardening assertions; the integration script now uses the locally
  remediated image by default. Neither test proves ClamAV or deployed security.
- A dedicated loopback Vite server with intercepted synthetic APIs passed the
  browser UI suite in Chromium, Firefox and WebKit, including automated axe
  checks. These are mocked UI tests, not live authentication, manual screen
  reader testing or evidence of deployed accessibility.
- Existing tests use synthetic or mocked data. No real provider, customer PDF,
  external service, paid cloud or hosted CI was used. A coordinated multi-store
  backup/restore drill, Kubernetes suite, real provider evaluation, independent
  review, production configuration and human approval workflow remain open.

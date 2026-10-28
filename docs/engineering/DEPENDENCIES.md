# Dependency and image verification

## Python dependency profiles

Python 3.12 has separate Windows/Linux CPU profiles, a universal test profile and
a Linux PDF-worker profile. Reviewed embedding/backend versions are constrained
in `backend/constraints-tested.txt`. uv 0.13.6 generates wheel-only resolution and
SHA-256 hashes; `backend/dependency-locks.json` binds input/output bytes. Root checks
reject drift. Regeneration requires review, tests and a new advisory audit.

```powershell
backend/.venv/Scripts/python.exe scripts/lock_dependencies.py --check
# Deliberate maintenance with the reviewed uv executable installed:
backend/.venv/Scripts/python.exe scripts/lock_dependencies.py
```

A clean `.venv-build` was populated from wheel/hash locks. Regression tests,
dependency consistency and offline cached embeddings passed. The approved OSV
check examined 134 DMC packages with zero affected package names at that checkpoint.
Only package names/versions were sent; this is not an OS audit.

## OS remediation, 2026-10-28

The previous Debian 13 candidates reported 45 backend and 73 PDF-worker OS
advisory/package records. These historical counts were not proven exploits.
Several stable vendor packages remained affected, including
[util-linux](https://security-tracker.debian.org/tracker/CVE-2026-76642) and
[libxml2](https://security-tracker.debian.org/tracker/CVE-2026-6653). No waiver or
ignore-unfixed option was added. The replacement candidates use the free official
Wolfi base pinned to digest
`sha256:0b179206ab162b12a43bacea1b525a4023e0272005c92d08555c61b1beaedc40`.

Direct OS packages pin Python 3.12.16-r1, libstdc++/libgomp 16.2.0-r2 and,
for PDF processing, Tesseract/English data 5.5.2-r8. Greek OCR data comes from a
pinned official tessdata_fast commit with a required SHA-256 checksum and explicit
non-root-readable permissions. Dependency Python installs retain their hash locks.
Final images remove pip, apk and BusyBox/the shell, retain OS package metadata and
run as UID 10001. Restricted runtime settings and isolated parser subprocesses
remain in place. This is attack-surface reduction, not proof that parsers are safe.

Trivy 0.76.1 uses checksum-pinned official binaries. The final local scans cover
all severities, OS and Python inventories: **zero reported advisory/package records
in both Wolfi candidates**. The fail-closed gate still rejects missing identity,
incomplete inventory, an EOL OS, and UNKNOWN/HIGH/CRITICAL findings. It contains no
exclusions. Exact IDs and scanner metadata are retained in ignored JSON/SBOMs under
`output/security/`; future database updates can change these results.

The worker image passes real synthetic English/Greek OCR, visual CDR that removes
links/active source objects, malformed rejection, non-root/no-shell/no-pip checks,
read-only root and network isolation. These offline checks alone do not test
ClamAV/gateway availability. The separate local runtime record reports which image
is actually installed; a candidate build alone does not update a running service.

The auth candidate uses the pinned official Node 22 Alpine base (runtime 22.23.4),
removes npm and starts through Node/tsx. Its previous exact-image scan passed and
four offline checks covered health, safe unavailable-DB failure, production flags
and secure cookie configuration. They are not a live login/mail/session test.

The refreshed 2026-10-28 scan found six records in the previous Better Auth 1.6.26
image (including critical/high records). Both client and service now pin 1.7.14,
with updated lockfiles, zero npm findings and a clean rebuilt full-severity image
scan. The [official 1.7.7 security release](https://github.com/better-auth/better-auth/releases/tag/v1.7.7)
documents the relevant fixes; 1.7.14 includes them. In addition to the offline
image checks, a real disposable-database integration verifies signed cookies,
wrong-password/tampering rejection and sign-out revocation against the backend.
Read-only migration planning found the existing local auth schema compatible;
no schema/account change was needed. This does not verify real mail delivery.

## Release limits

The tested PDF image was promoted to the local worker. Gateway CDR/OCR,
malformed/unauthorized rejection and real ClamAV detection of the harmless EICAR
test passed. The old image is retained as `dmc/pdf-worker:rollback-20261028`.
The API remains the Windows development process; its Linux candidate was tested
without replacing it. See the current [validation record](VALIDATION.md).

Wolfi is rolling: direct package pins and an immutable base do not freeze every
transitive apk dependency or repository metadata. Builds are not claimed to be
byte-for-byte reproducible. Promote an already tested exact image digest rather
than rebuilding an assumed identical tag. Keep rollback images and generate SBOMs
for the final identity; signing/provenance verification is still a release gate.
Historical Debian reports are retained as evidence, not silently overwritten.

Configured CI scans backend, PDF-worker and auth contexts and tests the actual PDF
image, including Greek OCR. Hosted CI has not executed. No image was published or
signed; no production hosting or provider-storage encryption was verified. See
the [remaining gates](ROADMAP.md) and [current validation](VALIDATION.md).

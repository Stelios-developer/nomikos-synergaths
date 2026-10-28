# Isolated PDF safety service

This is a private ingress service, not a public upload endpoint. It streams
the original PDF to ClamAV using `INSTREAM`, reconstructs every page into a
new image-only PDF, scans the result again, and returns only that result.
Unknown scanner responses, timeouts, malformed PDFs, oversized pages, and
embedded files fail closed. The worker runs as a non-root user with a read-only
root filesystem, no extra Linux capabilities, no privilege escalation, a
private network, and CPU/memory/PID limits. A small localhost-only gateway
provides request-size limits; the worker is not attached to its ingress
network. ClamAV has a separate network for signature updates. Neither service
publishes ClamAV's unauthenticated TCP port.

Each parsing/OCR job runs in a separate subprocess with no service secrets
in its environment. On Linux it has address-space (768 MiB), CPU, file-size,
and descriptor limits, plus a parent-enforced timeout. Only one job runs at
a time; excess jobs receive 429. Temporary output stays in the container's
bounded tmpfs. These are defense-in-depth process/container boundaries, not
a VM-grade sandbox or a guarantee against a native parser exploit.

For a local test, copy `.env.example` to `.env`, replace the placeholder with
a unique random 32+ character secret, and put the same value in `backend/.env`
alongside `PDF_SECURITY_URL=http://127.0.0.1:5186`. From this directory run
`docker compose up -d --build`; wait for `http://127.0.0.1:5186/health` to
return 200 before using uploads. Keep the token server-side. Avoid sending
the secret or any document to a public service. The worker requires roughly
4 GiB for ClamAV plus 1 GiB for the PDF process.

Visual CDR removes selectable text: the backend's isolated Greek/English OCR path must
re-read every page. This can change extraction quality, page processing time,
and file size; validate representative Greek and English legal/tax documents
and reject a release if dates, amounts, or citations deteriorate. A clean
ClamAV verdict is not a guarantee that a file is harmless.

Production needs a private authenticated service-to-service route, maintained
ClamAV signatures, image digest pinning, size limits at the proxy before
multipart parsing, load/timeout tests, and a monitored restart policy. The
Render backend blueprint does not deploy this worker or ClamAV.

## Verified locally — 2026-10-12

- Original and rebuilt PDF malware scans, image-only CDR, and Greek/English
  OCR passed a live one-page smoke test after the subprocess boundary was added.
- ClamAV rejected the in-memory EICAR test string; no EICAR file was stored.
- Regression tests cover PDF JavaScript removal, embedded-file rejection,
  missing authentication, scanner failure, timeout, and invalid OCR output.
- Review `docs/SECURITY_RELEASE_GATE.md` before accepting customer documents.

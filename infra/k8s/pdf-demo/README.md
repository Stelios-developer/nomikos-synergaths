# Synthetic PDF worker and scanner Kubernetes slice

This is a **test-only, partial** deployment: it does not include the backend,
auth, database, n8n, document storage or a provider. Do not use real documents,
credentials or workloads. The Secret is intentionally synthetic and public.

The image tags are local demo references with `imagePullPolicy: Never`; they
are not immutable signed release artifacts. ClamAV uses signatures already in
the local image and does not update them. CPU/memory budgets are provisional,
not production sizing. NetworkPolicies require a CNI that actually enforces
them; rendering or applying these resources does not prove enforcement.

Run only in a new isolated kind cluster after the ownership guard succeeds,
with a unique test namespace and locally loaded images. `kubectl kustomize
infra/k8s/pdf-demo` and `python -m unittest discover -s scripts/tests -p
test_k8s_pdf_manifest.py` perform focused offline checks only. Full AK
acceptance, TLS, fault recovery, integrated storage and offsite backups remain
open until separately tested and recorded.

On 2026-11-21, an isolated kind drill at commit `d4b79e4` passed strict
server-side validation, readiness, synthetic PDF sanitization, the EICAR
scanner check, scanner outage fail-closed behavior and scanner recovery.
The [recorded report](../../../docs/engineering/evidence/k8s-pdf-d4b79e4-2026-11-21.json)
includes runtime image IDs and the fixture hash. Those local image IDs do not
establish that the images were built from that commit. A cleanup wrapper
failed after the drill; the owned test cluster was subsequently removed
manually and the paused Padel cluster restarted. This result covers only the
slice described above, not the complete Kubernetes deployment or recovery.

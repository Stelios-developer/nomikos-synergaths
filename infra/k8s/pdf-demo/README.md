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

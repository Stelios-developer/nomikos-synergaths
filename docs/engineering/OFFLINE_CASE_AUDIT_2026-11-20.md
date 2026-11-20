# Offline case-audit verification — 20 November 2026

The tested source commit was `c4a7654613d439ed3a1a3b32ffb60a188c6c400d`.
The backend source was mounted read-only into the pre-existing local image
`sha256:250c822ee7a11df0dd57307f4a568fa61ba2a477bf086c782112c3207f12cceb`,
with Docker networking disabled. The image reported Python 3.12.16; pytest
8.3.3 and its pure-Python dependencies were mounted from the host. This was
not a fresh installation from the current lockfile or an image built from the
tested source commit.

`python -m pytest -p no:cacheprovider tests -q -rs` reported **321 passed and
1 skipped**. The skip was `tests/test_backup_crypto.py:18`: its Windows
current-user DPAPI boundary is not available in the Linux container. The suite
uses synthetic fixtures, mocks and temporary stores; it did not test live
provider behavior, real users, actual legal documents, a browser or production
deployment. In particular, a positive mocked model verdict is not proof of
source support, and positive claims still require human review.

The case audit now rejects unknown/missing citations, duplicate cited IDs,
empty excerpts and invalid page numbers without calling the model. It sends only
the union of cited excerpts in a batch. Different claims in the same batch can
still see one another's excerpts, so this is not per-claim isolation. An
independent human evaluation and a real deployment security review remain open.

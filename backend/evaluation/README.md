# Offline claim-gate development fixtures

These hand-constructed text cases exercise a narrow failure mode: a mock model
incorrectly claims every answer is supported. They are not PDFs, an independent
holdout, a measure of OCR/retrieval, or a real-provider evaluation. The author
is the project development process, not an independent legal reviewer. No
private documents or remote services are used. Do not tune against a holdout.

Run from `backend` with the project Python environment:

```
python evaluation/run_claim_gate.py
```

The report explicitly counts false supported claims remaining after the gate.
All positive model verdicts now require human review. A passing regression here
does not measure extraction, retrieval, answer quality, or human verification.

`python evaluation/run_case_gate.py` applies the same synthetic development
fixtures to the structured-case auditor, using a mocked positive model verdict.
It separately counts unsupported claims incorrectly marked supported, missed
review flags, and source-supported claims still sent for human review. The last
number shows the conservative gate's tradeoff, not a model accuracy estimate.

`generate_pilot_pdfs.py` creates 30 synthetic development PDFs (including six
image-only examples) in a new temporary folder. Its template-generated labels
are not independent annotations and there is no holdout. Run it with a local
Unicode font and an existing output parent, then use `check_pilot_extraction.py`
on the resulting folder. That checks digital extraction and scan detection; it
does not run OCR, retrieval, a provider, or a prompt-injection evaluation.

New pilot manifests record the SHA-256 of each generated PDF. The extraction
check requires all 30 unique development documents, six scan labels and
complete expected fields; it rejects changed files and unsafe filenames before
extraction. Older `pilot-1` manifests without hashes remain readable, but the
report explicitly marks `pdf_hashes_verified: false`. A checksum only proves a
file matches its manifest; it does not establish independent annotation, source
correctness, OCR quality or a trusted signature.

`validate_pilot_review.py --corpus <pilot-directory> --review <review.json>`
checks the *structure* of a completed human review against the exact manifest
and hashed synthetic PDFs. The JSON has `reviewer`, `manifest_sha256` (SHA-256
of the exact `manifest.json` bytes), and `documents`. Each document has `id`
and `fields` for `owner`, `approver` and `deadline`. Each field must be one of:

- `{"status":"present","value":"...","page":1,"quote":"..."}`;
- `{"status":"absent","reviewed_pages":[1,2]}`;
- `{"status":"uncertain","reason":"..."}`.

The check requires all 30 documents, validates field shape and page bounds,
and prints only hashes and counts. It neither verifies the reviewer is
independent nor confirms quotes, absence, source support or model output. The
pilot remains development-only; it is not a closed holdout. No human review is
provided by this tool. Keep review files in ignored `output/`, not in Git.

To prepare an unlabelled packet for a reviewer, create an existing ignored
`output/` directory and run `python evaluation/prepare_blind_review.py --corpus
<pilot-directory> --destination <new-directory-inside-output>`. It verifies
the pilot hashes and writes document IDs, filenames, hashes, copies of the PDFs
and blank review fields, without copying the template's expected facts. Supply
the packet without the original manifest or retrieval outputs. The
reviewer fills in the fields and uses `validate_pilot_review.py` for structural
validation. The packet cannot verify that the reviewer is independent, that a
quote supports a label, or that the underlying development corpus is a holdout.

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

"""One bounded parser/OCR job. Launched by the API, never as a web service."""
import json
import sys

# Linux-only limits supplement the container limits and the parent's timeout.
if sys.platform == "linux":
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (41 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    cpu_seconds = 60 if sys.argv[1] == "sanitize" else 300
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))

from app import MAX_OUTPUT_BYTES, extract_ocr_pages, reconstruct_pdf

try:
    data = sys.stdin.buffer.read(MAX_OUTPUT_BYTES + 1)
    if len(data) > MAX_OUTPUT_BYTES:
        raise ValueError("Input is too large")
    if sys.argv[1] == "sanitize":
        rebuilt, pages = reconstruct_pdf(data)
        sys.stdout.buffer.write(pages.to_bytes(4, "big") + rebuilt)
    elif sys.argv[1] == "ocr":
        output = json.dumps({"pages": extract_ocr_pages(data)}, ensure_ascii=False).encode("utf-8")
        if len(output) > MAX_OUTPUT_BYTES:
            raise ValueError("OCR output is too large")
        sys.stdout.buffer.write(output)
    else:
        raise ValueError("Unknown task")
except Exception:
    # No document content or parser diagnostics leave the job process.
    sys.exit(2)

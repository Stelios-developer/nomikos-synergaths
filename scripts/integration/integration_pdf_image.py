"""Synthetic CDR/OCR in the exact local image; no network, host mounts or malware.

This does not test the ClamAV service, its signatures or the upload gateway.
"""

import json
from pathlib import Path
import subprocess
import sys

import fitz

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "dmc/pdf-worker:security-20261027-final"
PROGRAM = r"""
import importlib.util,json,os,sys,shutil
import fitz
from app import UnsafePdf,run_private_job
assert os.getuid()==10001
assert importlib.util.find_spec('pip') is None
assert shutil.which('apk') is None and shutil.which('sh') is None
try:
    open('/app/unexpected-write','w')
    raise AssertionError('Root filesystem is writable')
except OSError:
    pass
data=sys.stdin.buffer.read(1024*1024)
rebuilt=run_private_job('sanitize',data)
assert int.from_bytes(rebuilt[:4],'big')==1
with fitz.open(stream=rebuilt[4:],filetype='pdf') as document:
    assert document.page_count==1
    assert document.embfile_count()==0
    assert document[0].get_links()==[]
    assert document[0].get_text().strip()==''
    assert not any('/JavaScript' in document.xref_object(i) for i in range(1,document.xref_length()))
pages=json.loads(run_private_job('ocr',rebuilt[4:]))['pages']
assert 'SYNTHETIC' in pages[0]['text'].upper(), 'OCR did not recover the synthetic fixture'
assert 'ΠΡΟΘΕΣΜΙΑ' in pages[0]['text'].upper(), 'Greek OCR did not recover the fixture'
text = pages[0]['text']
assert '15 July 2026' in text and '16 July 2026' not in text, 'OCR changed the synthetic deadline'
assert 'reconciliation' in text and 'Manager' in text, 'OCR lost the milestone or owner'
# Mixed-script OCR can still confuse visually similar Greek/Latin letters;
# document-level human review remains mandatory.
assert abs(text.index('15 July 2026') - text.index('reconciliation')) < 80, 'OCR separated a synthetic table row'
assert abs(text.index('Late filing') - text.index('Weekly readiness review')) < 80, 'OCR separated risk from mitigation'
try:
    run_private_job('sanitize',b'not a PDF')
except UnsafePdf:
    pass
else:
    raise AssertionError('Malformed PDF was accepted')
print(json.dumps({'gate':'PASSED','uid':os.getuid(),'pages':1,'read_only':True,'network':'none',
                 'pip_present':False,'active_objects_removed':True,'ocr_recovered':True,'greek_ocr_recovered':True,'malformed_rejected':True}))
"""


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else IMAGE
    image = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Id}}", name], text=True
    ).strip()
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((60, 100), "SYNTHETIC DEADLINE TEST", fontsize=24)
        fonts = [
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ]
        font = next((p for p in fonts if p.is_file()), None)
        if font is None:
            raise RuntimeError(
                "Install a Greek-capable Arial/DejaVu font for the synthetic OCR fixture."
            )
        page.insert_font(fontname="fixture-greek", fontfile=str(font))
        page.insert_text(
            (60, 160), "ΠΡΟΘΕΣΜΙΑ ΠΛΗΡΩΜΗΣ", fontname="fixture-greek", fontsize=24
        )
        page.insert_text((60, 220), "15 July 2026   Final reconciliation   Tax Manager", fontsize=16)
        page.insert_text((60, 260), "Late filing   High   Weekly readiness review", fontsize=16)
        page.insert_link(
            {
                "kind": fitz.LINK_URI,
                "from": fitz.Rect(60, 80, 400, 110),
                "uri": "https://example.test/synthetic",
            }
        )
        document.subset_fonts()
        data = document.tobytes(garbage=4, deflate=True)
    command = [
        "docker",
        "run",
        "--rm",
        "--interactive",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "64",
        "--memory",
        "1g",
        "--cpus",
        "2",
        "--tmpfs",
        "/tmp:rw,nosuid,noexec,size=96m",
        "--entrypoint",
        "python",
        image,
        "-c",
        PROGRAM,
    ]
    result = subprocess.run(command, input=data, capture_output=True, timeout=150)
    if result.returncode or len(result.stdout) > 4096:
        raise RuntimeError(
            "Isolated PDF-image check failed: "
            + result.stderr.decode(errors="replace")[-2000:]
        )
    report = json.loads(result.stdout)
    report.update(
        {
            "image": subprocess.check_output(
                ["docker", "image", "inspect", "--format", "{{.Id}}", image], text=True
            ).strip(),
            "scope": "Synthetic CDR/OCR and runtime restrictions only; no ClamAV/gateway or production claim.",
        }
    )
    target = ROOT / "output/engineering-audit/pdf-image.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        "Exact PDF image: synthetic CDR/OCR, malformed rejection and runtime isolation PASSED."
    )


if __name__ == "__main__":
    main()

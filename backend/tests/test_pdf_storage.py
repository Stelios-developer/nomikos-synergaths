import os

import services.pdf_storage as pdf_storage


def test_save_pdf_writes_file_and_returns_path(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_storage, "PDF_STORAGE_DIR", str(tmp_path))
    path = pdf_storage.save_pdf("report.pdf", b"%PDF-1.4 fake bytes")
    assert os.path.exists(path)
    with open(path, "rb") as f:
        assert f.read() == b"%PDF-1.4 fake bytes"


def test_save_pdf_strips_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_storage, "PDF_STORAGE_DIR", str(tmp_path))
    path = pdf_storage.save_pdf("../../etc/evil.pdf", b"x")
    assert os.path.basename(path).endswith(".pdf")
    assert "evil.pdf" not in path
    assert os.path.commonpath([str(tmp_path), path]) == str(tmp_path)


def test_save_pdf_handles_windows_invalid_filename_characters(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_storage, "PDF_STORAGE_DIR", str(tmp_path))

    path = pdf_storage.save_pdf("case:final?.pdf", b"data", session_id="workspace")

    assert os.path.exists(path)
    assert os.path.basename(path).endswith(".pdf")
    assert pdf_storage.pdf_path("case:final?.pdf", session_id="workspace") == path


def test_pdf_path_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_storage, "PDF_STORAGE_DIR", str(tmp_path))
    assert pdf_storage.pdf_path("nope.pdf") is None


def test_pdf_path_returns_path_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_storage, "PDF_STORAGE_DIR", str(tmp_path))
    pdf_storage.save_pdf("report.pdf", b"data")
    assert pdf_storage.pdf_path("report.pdf") is not None


def test_delete_pdf_removes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_storage, "PDF_STORAGE_DIR", str(tmp_path))
    pdf_storage.save_pdf("report.pdf", b"data")
    pdf_storage.delete_pdf("report.pdf")
    assert pdf_storage.pdf_path("report.pdf") is None


def test_delete_pdf_missing_file_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_storage, "PDF_STORAGE_DIR", str(tmp_path))
    pdf_storage.delete_pdf("never-existed.pdf")  # should not raise


def test_same_filename_is_isolated_by_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_storage, "PDF_STORAGE_DIR", str(tmp_path))
    first = pdf_storage.save_pdf("report.pdf", b"first", session_id="workspace-a")
    second = pdf_storage.save_pdf("report.pdf", b"second", session_id="workspace-b")

    assert first != second
    with open(first, "rb") as f:
        assert f.read() == b"first"
    with open(second, "rb") as f:
        assert f.read() == b"second"

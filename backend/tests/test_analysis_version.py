from services import analysis_jobs


def test_release_fingerprint_does_not_drift_with_disk_edits_before_restart(
    tmp_path, monkeypatch
):
    names = [
        "document_case.py",
        "auditor.py",
        "llm.py",
        "case_stages.py",
        "analysis_context.py",
    ]
    for name in names:
        (tmp_path / name).write_text("synthetic original release", encoding="utf8")
    monkeypatch.setattr(analysis_jobs, "__file__", str(tmp_path / "analysis_jobs.py"))
    analysis_jobs._pipeline_sources.cache_clear()
    try:
        original = analysis_jobs.pipeline_version()
        (tmp_path / "llm.py").write_text("synthetic next release", encoding="utf8")
        assert analysis_jobs.pipeline_version() == original
        # A fresh process/module cache observes the next reviewed release.
        analysis_jobs._pipeline_sources.cache_clear()
        assert analysis_jobs.pipeline_version() != original
    finally:
        analysis_jobs._pipeline_sources.cache_clear()

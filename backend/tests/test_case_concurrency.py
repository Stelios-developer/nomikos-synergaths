from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import threading

import pytest

from services import case_store


def create():
    return case_store.create_case({
        "case_id": "fixture", "workspace_id": "owner", "document": {"filename": "test.pdf"},
        "stage": "started", "status": "in_progress",
    })


def test_stale_case_cannot_overwrite_a_newer_stage():
    original = create()
    first, stale = deepcopy(original), deepcopy(original)
    first["stage"] = "dna_complete"
    case_store.save_case(first)
    stale["stage"] = "facts_complete"
    with pytest.raises(case_store.CaseWriteConflict):
        case_store.save_case(stale)
    assert case_store.get_case("fixture", "owner")["stage"] == "dna_complete"


def test_two_concurrent_writers_have_exactly_one_commit():
    original = create()
    barrier = threading.Barrier(2)

    def write(stage):
        case = deepcopy(original)
        case["stage"] = stage
        barrier.wait(timeout=2)
        try:
            case_store.save_case(case)
            return "committed"
        except case_store.CaseWriteConflict:
            return "conflict"

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(write, ["dna_complete", "facts_complete"]))
    assert sorted(results) == ["committed", "conflict"]


def test_deleted_case_cannot_be_resurrected_by_late_model_output():
    case = create()
    case_store.delete_cases_for_document("test.pdf", "owner")
    with pytest.raises(case_store.CaseWriteConflict):
        case_store.save_case(case)
    assert case_store.get_case("fixture", "owner") is None


def test_foreign_workspace_cannot_advance_case():
    case = create()
    case["workspace_id"] = "foreign"
    with pytest.raises(case_store.CaseWriteConflict):
        case_store.save_case(case)
    assert case_store.get_case("fixture", "owner")["stage"] == "started"


def test_timestamp_collision_still_advances_the_cas_token(monkeypatch):
    case = create()
    monkeypatch.setattr(case_store, "_now", lambda: case["updated_at"])
    saved = case_store.save_case(deepcopy(case))
    assert saved["updated_at"] != case["updated_at"]
    with pytest.raises(case_store.CaseWriteConflict):
        case_store.save_case(case)

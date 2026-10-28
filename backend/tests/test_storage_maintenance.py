from pathlib import Path
import pytest

from services import pdf_storage
from services.workspace_lock import WorkspaceUnavailable, storage_maintenance, workspace_access


def test_failed_maintenance_stays_closed_and_can_be_explicitly_resumed():
    with pytest.raises(RuntimeError):
        with storage_maintenance():
            with workspace_access('synthetic'):
                pass
            raise RuntimeError('synthetic interruption')
    with pytest.raises(WorkspaceUnavailable):
        with workspace_access('synthetic'):
            pass
    with pytest.raises(FileExistsError):
        with storage_maintenance():
            pass
    with storage_maintenance(resume=True):
        pass
    with workspace_access('synthetic'):
        pass


def test_resume_does_not_clear_an_unknown_maintenance_marker():
    marker = Path(pdf_storage.PDF_STORAGE_DIR)/'.storage-maintenance'
    marker.write_text('different-operation', encoding='ascii')
    with pytest.raises(WorkspaceUnavailable):
        with storage_maintenance(resume=True):
            pass
    assert marker.read_text(encoding='ascii') == 'different-operation'

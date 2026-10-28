"""Cross-process workspace serialization and interrupted-publication quarantine."""
import functools
import hashlib
import inspect
import os
import threading
from contextlib import contextmanager

from filelock import FileLock, Timeout

from services import pdf_storage

_locks = {}
_registry_lock = threading.Lock()
_local = threading.local()


class WorkspaceUnavailable(RuntimeError):
    pass


def marker_path(workspace_id):
    folder = os.path.join(pdf_storage.PDF_STORAGE_DIR, hashlib.sha256(workspace_id.encode()).hexdigest())
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, ".publication-pending")


@contextmanager
def workspace_access(workspace_id):
    maintenance = os.path.join(pdf_storage.PDF_STORAGE_DIR, '.storage-maintenance')
    if os.path.exists(maintenance) and not getattr(_local, 'maintenance_owner', False):
        raise WorkspaceUnavailable('Document storage is undergoing verified maintenance. Please retry shortly.')
    marker = marker_path(workspace_id)
    path = marker + ".lock"
    with _registry_lock:
        lock = _locks.setdefault(path, FileLock(path, timeout=2))
    try:
        with lock:
            if os.path.exists(marker) and marker not in getattr(_local, "publishing", set()):
                raise WorkspaceUnavailable("Document recovery is required before this workspace can be used.")
            yield
    except Timeout as exc:
        raise WorkspaceUnavailable("This workspace is updating. Please retry shortly.") from exc


@contextmanager
def storage_maintenance(*, resume=False):
    """Offline operator scope; failures retain a durable fail-closed marker."""
    root = pdf_storage.PDF_STORAGE_DIR
    os.makedirs(root, exist_ok=True)
    marker = os.path.join(root, '.storage-maintenance')
    with FileLock(marker + '.lock', timeout=0):
        if resume and os.path.isfile(marker):
            with open(marker, encoding='ascii') as previous_marker:
                if previous_marker.read() != 'verified-storage-migration\n':
                    raise WorkspaceUnavailable('Unknown maintenance marker; operator review is required.')
        else:
            with open(marker, 'x', encoding='ascii') as output:
                output.write('verified-storage-migration\n')
                output.flush()
                os.fsync(output.fileno())
        previous = getattr(_local, 'maintenance_owner', False)
        _local.maintenance_owner = True
        try:
            yield
            os.unlink(marker)
        finally:
            _local.maintenance_owner = previous


@contextmanager
def publication_scope(workspace_id):
    # Caller holds workspace_access. Only this writer thread may see its own
    # pending state; another process or a restarted server remains fail-closed.
    marker = marker_path(workspace_id)
    active = getattr(_local, "publishing", set())
    _local.publishing = active | {marker}
    try:
        yield marker
    finally:
        _local.publishing = active


def scoped_operation(function):
    signature = inspect.signature(function)

    @functools.wraps(function)
    def guarded(*args, **kwargs):
        values = signature.bind(*args, **kwargs)
        values.apply_defaults()
        workspace = values.arguments.get("session_id") or values.arguments.get("workspace_id")
        if workspace is None and isinstance(values.arguments.get("case"), dict):
            workspace = values.arguments["case"]["workspace_id"]
        with workspace_access(workspace):
            return function(*args, **kwargs)
    return guarded

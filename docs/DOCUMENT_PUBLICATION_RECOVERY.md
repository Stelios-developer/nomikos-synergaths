# Document publication and recovery

## Normal replacement

Browser and n8n uploads use the same coordinator. It prepares a staged PDF and
embeddings without altering active evidence. A cross-process workspace lock then
covers quotas, snapshots, indexing, source replacement and case invalidation.
Scoped reads and deletions use the same lock. A busy lock returns HTTP 503 after
two seconds; another workspace remains usable.

Exceptions restore the previous index documents/metadata/embeddings, PDF and
SQLite case rows. Successful replacement removes temporary source copies and
invalidates prior analyses. This provides serialized visibility and exception
rollback, not a distributed ACID transaction.

## Interrupted work or failed cleanup

Before mutation, an fsynced `.publication-pending` marker is written in the
hashed workspace directory under `PDF_STORAGE_DIR`. It records opaque source
basenames, not PDF text, user IDs or the original filename. While the writer
holds the lock, only that writer thread can access its pending state.

A restart with a leftover marker, a rollback failure, or an old-source cleanup
failure quarantines the workspace: document/index/case access returns HTTP 503.
Recovery sources can remain as `.incoming-*.tmp` / `.previous-*.tmp`. They are
sensitive plaintext, not encrypted backups; production storage encryption must
cover them too. Never publish or commit the storage tree. These recovery holds
must be resolved and cleaned by an operator, not silently expired.

## Operator procedure

1. Stop all API processes using this storage and prevent further workflow calls.
2. Take a protected, consistent backup of PDF storage, vector data and case DB.
   Do not copy document content to a public issue or terminal transcript.
3. Inspect the marker and its opaque source basenames. Do not delete the marker
   merely to silence the error. A partial failure may have changed one store
   but not another; the in-memory rollback snapshot does not survive a crash.
4. Restore all three stores from the same consistent backup, applying any
   deletion ledger before serving users. Alternatively, perform an audited
   reconstruction from the selected sanitized source, recreate its chunks and
   embeddings, and invalidate/re-run associated cases. The current coordinator
   deliberately does not attempt an automatic, potentially destructive repair.
5. Verify matching document generation, source/citations, workspace ownership
   and case validity. Resolve the marker only after consistency is established,
   and remove reviewed recovery copies under the approved retention policy.
6. Restart and verify document listing, page citations, analysis and new upload.

Directory metadata is fsynced on POSIX before clearing the marker. Windows has
no portable directory-fsync equivalent in this implementation. Underlying
storage durability, hardware failure and filesystem corruption need consistent
backups and restore drills; this mechanism is not a power-loss guarantee.

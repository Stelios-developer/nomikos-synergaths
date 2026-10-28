# Data retention and recovery policy — release draft

Status: **not approved or fully enforced**. The owner must approve retention
periods and verify them against applicable contracts and legal obligations
before customer data is accepted. Do not promise instant or complete erasure.

| Data | Current location | Current deletion behavior | Production target |
| --- | --- | --- | --- |
| Source PDFs | Backend PDF volume | Document DELETE removes active copy | Remove on user request; no undisclosed replicas |
| Chunks and embeddings | Dedicated PostgreSQL/pgvector database | Workspace-scoped DELETE removes matching chunks | Same lifecycle as source |
| Analysis cases | SQLite case DB | Document DELETE removes matching cases | Same lifecycle as source |
| Analysis jobs, stages and events | Dedicated PostgreSQL database, forced workspace RLS | Document DELETE removes jobs and cascades stage/event rows; events are append-only for ordinary runtime operations | Set metadata retention separately; never retain document text in events |
| Account and sessions | Better Auth PostgreSQL | Document DELETE does not remove them | Separate verified account-erasure workflow |
| Operational telemetry/evaluation | SQLite databases/logs | May retain historic rows | 30-day maximum after explicit owner approval; do not log content |
| n8n executions | n8n SQLite volume | Completed payload retention disabled; in-flight state is temporarily persisted then physically pruned; tested row counts zero | Continue crash/cancellation and count audits; do not promise zero transient writes |
| LLM provider processing | External configured provider | Not controlled by document DELETE | Contractual region/retention/training controls and deletion process |
| Backups and snapshots | Local n8n archives in ignored output/security-backups; production locations not selected | Document DELETE cannot erase them | Encrypted, access-controlled, 30-day rolling expiry after owner approval |

## Required production backup controls

The background activity history reads an exact attempt and verifies the current
source generation. Replacing/deleting a source makes old results unavailable;
closing an attempt does not erase its history or backups. Cancellation fences
new stages/commits but cannot erase a request already accepted remotely. Do not
confuse closure, document deletion and account erasure.

The local queue migration was preceded by an AES-GCM/DPAPI encrypted PostgreSQL
dump, actual restoration into a disposable database and exact content hashing.
All 46 active vector chunks were preserved. That dump is sensitive and remains
in ignored `output/security-backups/`, with its separately protected key.
This is local migration recovery, not approved backup expiry or off-machine DR.

1. Inventory every volume, database, provider snapshot, replica, and backup
   destination; record the owner, region, encryption setting, key owner, and
   exact expiry behavior. Do not treat transport TLS as storage encryption.
2. Use provider-verified encryption at rest for PDFs, PostgreSQL vectors, SQLite,
   PostgreSQL, n8n, and backups. Keep encryption keys in a managed secret/KMS
   system with restricted access and rotation. Do not store keys in the repo
   or the same backup archive. Record a provider screenshot/API result and
   key-management evidence in a private release dossier, not in Git.
3. Back up all interdependent stores from a consistent point in time. Encrypt
   before offsite transfer, restrict restore roles, and alert on failures.
   Define an RPO/RTO and perform a restore drill at least monthly; compare
   document counts and case/citation integrity after restore.
4. Keep a deletion ledger of document IDs and deletion times outside the
   restored data. Replay the ledger after every restore before serving users,
   so a backup cannot silently resurrect a deleted document. Backups expire
   after the approved window; physical media/snapshot expiry must be verified.
5. Handle historic n8n executions, old evaluation rows, and provider logs as
   separate erasure tasks. Audit counts and backup copies first; never run an
   unreviewed bulk deletion against the live database.

## Local verification (2026-10-12)

- There is no production deployment; no cloud encryption or backup controls
  can be verified from this checkout.
- Windows BitLocker status could not be read without administrator access.
  Therefore local at-rest encryption is **unverified**, not confirmed.
- The active n8n container has execution-save settings disabled for future
  successful, failed, progress, and manual executions. All six workflows were
  checked; both Documents Made Clear workflows now explicitly disable saved payloads and
  unrelated workflows retain their original settings. The former
  seven execution/payload rows had already been removed by automatic pruning:
  the live SQLite database now has zero rows in both tables. No manual purge
  was needed.
- A consistent, encrypted local n8n volume backup was taken while n8n was
  stopped, then decrypted and byte-compared in memory. It includes the SQLite
  database. The archive and its separate DPAPI-protected key live under the
  Git-ignored `output/security-backups/` directory. The key is recoverable
  only by the same Windows user profile on this machine; this is **not** a
  offsite/disaster-recovery backup or proof of storage encryption.
- The actual backup's two files must be retained together and protected as
  sensitive; the archive also contains n8n configuration. Do not commit,
  publish, or email them. A full isolated-volume restore drill passed with six
  workflows and zero execution/payload rows, including SQLite integrity and
  foreign-key checks. The temporary plaintext test volume was removed.
- n8n was updated to 2.42.7. Its hard-delete recovery buffer is zero hours,
  and both pruning intervals are one minute. After a real 401 webhook test,
  read-only counts returned zero. In-flight persistence, abnormal termination,
  logs, event buffers, binary data, and backups remain separate concerns.
- No approved retention period or automatic backup expiry is assumed. The
  proposed 30-day policy requires an explicit owner decision; encrypted
  recovery archives have not been silently deleted.

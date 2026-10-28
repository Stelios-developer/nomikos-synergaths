import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useState,
  useSyncExternalStore,
} from 'react'
import {
  deleteDocument,
  listDocuments,
  type DocumentInfo,
} from '../../api/client'
import { Resource } from '../../api/resource'

export interface DocumentListHandle {
  refresh: () => void
}

interface DocumentListProps {
  selectedFilename: string | null
  onSelect: (filename: string | null) => void
  searchQuery?: string
}

function documentKind(method: string) {
  return method === 'ocr' ? 'SCANNED' : 'PDF'
}

const DocumentList = forwardRef<DocumentListHandle, DocumentListProps>(
  function DocumentList({ selectedFilename, onSelect, searchQuery = '' }, ref) {
    const resource = useMemo(() => new Resource<DocumentInfo[]>((signal) => listDocuments(signal)), [])
    const snapshot = useSyncExternalStore(resource.subscribe, resource.getSnapshot)
    const docs = snapshot.data ?? []
    const loading = snapshot.status === 'loading' || snapshot.status === 'idle'
    const [pendingDelete, setPendingDelete] = useState<string | null>(null)
    const [deleting, setDeleting] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)

    const refresh = useCallback(() => {
      setError(null)
      void resource.load()
    }, [resource])

    useEffect(() => {
      refresh()
      return () => resource.clear()
    }, [refresh, resource])
    useImperativeHandle(ref, () => ({ refresh }), [refresh])

    const confirmDelete = async (filename: string) => {
      setDeleting(filename)
      setError(null)
      try {
        await deleteDocument(filename)
        if (selectedFilename === filename) onSelect(null)
        setPendingDelete(null)
        refresh()
      } catch (requestError) {
        setError(
          requestError instanceof Error
            ? requestError.message
            : 'Δεν ήταν δυνατή η διαγραφή του εγγράφου.',
        )
      } finally {
        setDeleting(null)
      }
    }

    if (loading && snapshot.data === null)
      return (
        <div className="document-list-state">
          <span className="library-spinner" aria-hidden="true" />
          Φόρτωση βιβλιοθήκης…
        </div>
      )

    const visibleDocs = docs.filter((doc) =>
      doc.filename
        .toLocaleLowerCase()
        .includes(searchQuery.trim().toLocaleLowerCase()),
    )

    return (
      <div className="document-library">
        {snapshot.data !== null && (
          <div className="document-library-tools">
            <small>{loading ? 'Refreshing…' : `Last refreshed ${new Date(snapshot.updatedAt!).toLocaleTimeString()}`}</small>
            <button type="button" onClick={refresh} disabled={loading}>Refresh library</button>
          </div>
        )}
        {(error || snapshot.error) && (
          <p className="document-list-error" role="alert">
            {error ?? snapshot.error?.message}
            {snapshot.data !== null && ' Showing the last successful result; refresh before acting.'}
            <button type="button" onClick={refresh} disabled={loading}>Retry library</button>
          </p>
        )}

        {snapshot.status === 'error' && snapshot.data === null ? (
          <div className="document-list-empty">Library unavailable. Your documents have not been confirmed as empty.</div>
        ) : visibleDocs.length === 0 ? (
          <div className="document-list-empty">
            <span>
              {docs.length ? 'No matching documents' : 'A fresh start.'}
            </span>
            <p>
              {docs.length
                ? 'Try another file name.'
                : 'Upload your first PDF to start building an evidence-backed case.'}
            </p>
          </div>
        ) : (
          <ul className="document-library-list">
            {visibleDocs.map((doc) => {
              const isSelected = selectedFilename === doc.filename
              const isConfirmingDelete = pendingDelete === doc.filename
              return (
                <li
                  key={doc.filename}
                  className={`document-library-item ${isSelected ? 'is-selected' : ''}`}
                >
                  <div className="document-item-row">
                    <button
                      type="button"
                      className="document-select-button"
                      disabled={snapshot.status !== 'success'}
                      onClick={() => onSelect(doc.filename)}
                    >
                      <span className="document-file-mark">
                        {documentKind(doc.method)}
                      </span>
                      <span className="document-item-copy">
                        <strong title={doc.filename}>{doc.filename}</strong>
                        <small>
                          {doc.chunk_count} source fragments ·{' '}
                          {doc.method === 'ocr'
                            ? 'OCR extraction'
                            : 'digital extraction'}
                        </small>
                      </span>
                    </button>
                    <button
                      type="button"
                      className="document-delete-button"
                      disabled={snapshot.status !== 'success'}
                      onClick={() =>
                        setPendingDelete(
                          isConfirmingDelete ? null : doc.filename,
                        )
                      }
                      aria-label={`Delete ${doc.filename}`}
                      title="Delete document"
                    >
                      ×
                    </button>
                  </div>

                  {isConfirmingDelete && (
                    <div className="document-delete-confirm" role="status">
                      <span>Remove this document?</span>
                      <div>
                        <button
                          type="button"
                          onClick={() => setPendingDelete(null)}
                          disabled={deleting === doc.filename || snapshot.status !== 'success'}
                        >
                          Keep
                        </button>
                        <button
                          type="button"
                          onClick={() => void confirmDelete(doc.filename)}
                          disabled={deleting === doc.filename || snapshot.status !== 'success'}
                        >
                          {deleting === doc.filename ? 'Removing…' : 'Remove'}
                        </button>
                      </div>
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    )
  },
)

export default DocumentList

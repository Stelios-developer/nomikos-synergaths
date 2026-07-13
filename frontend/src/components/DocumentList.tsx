import { useEffect, useState, useImperativeHandle, forwardRef } from 'react'
import { listDocuments, deleteDocument, type DocumentInfo } from '../api/client'

export interface DocumentListHandle {
  refresh: () => void
}

interface DocumentListProps {
  selectedFilename: string | null
  onSelect: (filename: string | null) => void
}

const DocumentList = forwardRef<DocumentListHandle, DocumentListProps>(
  function DocumentList({ selectedFilename, onSelect }, ref) {
    const [docs, setDocs] = useState<DocumentInfo[]>([])
    const [loading, setLoading] = useState(true)

    const refresh = () => {
      setLoading(true)
      listDocuments()
        .then(setDocs)
        .finally(() => setLoading(false))
    }

    useEffect(refresh, [])
    useImperativeHandle(ref, () => ({ refresh }))

    const handleDelete = async (filename: string, e: React.MouseEvent) => {
      e.stopPropagation()
      await deleteDocument(filename)
      if (selectedFilename === filename) onSelect(null)
      refresh()
    }

    if (loading) return <p className="text-xs text-gray-500">Loading documents…</p>
    if (docs.length === 0) return <p className="text-xs text-gray-500">No documents uploaded yet.</p>

    return (
      <ul className="space-y-1">
        <li>
          <button
            onClick={() => onSelect(null)}
            className={`w-full rounded px-2 py-1.5 text-left text-xs
              ${selectedFilename === null ? 'bg-gold/10 text-gold' : 'text-gray-400 hover:bg-panel-border'}`}
          >
            All documents
          </button>
        </li>
        {docs.map((doc) => (
          <li key={doc.filename}>
            <button
              onClick={() => onSelect(doc.filename)}
              className={`group flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-xs
                ${selectedFilename === doc.filename ? 'bg-gold/10 text-gold' : 'text-gray-300 hover:bg-panel-border'}`}
            >
              <span className="truncate">{doc.filename}</span>
              <span className="flex items-center gap-2">
                <span className="text-[10px] text-gray-500">{doc.chunk_count}</span>
                <span
                  role="button"
                  onClick={(e) => handleDelete(doc.filename, e)}
                  className="opacity-0 group-hover:opacity-100 text-gray-500 hover:text-red-400"
                >
                  ✕
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    )
  }
)

export default DocumentList

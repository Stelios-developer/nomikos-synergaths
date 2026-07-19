import { useEffect, useState } from 'react'
import { getPageImageUrl, type Citation } from '../api/client'

interface PdfPageModalProps {
  citation: Citation | null
  onClose: () => void
}

// Shows the real PDF page a citation came from, with the exact excerpt
// highlighted server-side (see backend/services/page_render.py) — makes
// citations verifiable at a glance instead of trusting the extracted text.
export default function PdfPageModal({ citation, onClose }: PdfPageModalProps) {
  const [imgUrl, setImgUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!citation) return

    let cancelled = false
    let objectUrl: string | null = null
    setImgUrl(null)
    setError(null)
    setLoading(true)

    getPageImageUrl(citation.filename, citation.page, citation.text)
      .then((url) => {
        if (cancelled) {
          URL.revokeObjectURL(url)
          return
        }
        objectUrl = url
        setImgUrl(url)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load page.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [citation])

  useEffect(() => {
    if (!citation) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [citation, onClose])

  if (!citation) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6"
      onClick={onClose}
    >
      <div
        className="animate-modal-in flex max-h-[90vh] max-w-2xl flex-col overflow-hidden rounded-lg border border-panel-border bg-panel"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-panel-border px-4 py-3">
          <div>
            <p className="truncate text-sm font-medium text-gold">{citation.filename}</p>
            <p className="text-[11px] text-gray-500">page {citation.page} — source excerpt highlighted</p>
          </div>
          <button
            onClick={onClose}
            className="ml-3 shrink-0 rounded px-2 py-1 text-gray-400 transition-colors hover:text-gray-100"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="overflow-auto p-4">
          {loading && <p className="text-sm text-gray-500">Rendering page…</p>}
          {error && (
            <p className="max-w-sm text-sm text-gray-500">
              Couldn't load the original page ({error}). It may have been uploaded before this
              feature was added, or the document was removed.
            </p>
          )}
          {imgUrl && !loading && (
            <img
              src={imgUrl}
              alt={`Page ${citation.page} of ${citation.filename}`}
              className="animate-scale-in rounded border border-panel-border"
            />
          )}
        </div>
      </div>
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
import { getPageImageUrl, type Citation } from '../../api/client'
import Dialog from '../ui/Dialog'

interface PdfPageModalProps {
  citation: Citation | null
  onClose: () => void
}

export default function PdfPageModal({ citation, onClose }: PdfPageModalProps) {
  const [imgUrl, setImgUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const closeButtonRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!citation) return

    let cancelled = false
    let objectUrl: string | null = null
    setImgUrl(null)
    setError(null)
    setLoading(true)
    closeButtonRef.current?.focus()

    getPageImageUrl(citation.filename, citation.page, citation.text)
      .then((url) => {
        if (cancelled) {
          URL.revokeObjectURL(url)
          return
        }
        objectUrl = url
        setImgUrl(url)
      })
      .catch((requestError) => {
        if (!cancelled)
          setError(
            requestError instanceof Error
              ? requestError.message
              : 'The original page could not be loaded.',
          )
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
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [citation, onClose])

  if (!citation) return null

  return (
    <Dialog
      open={Boolean(citation)}
      titleId="source-modal-title"
      onClose={onClose}
      className="source-preview-dialog"
    >
      <header className="source-modal-header">
        <div>
          <span className="eyebrow">SOURCE PROOF</span>
          <h2 id="source-modal-title" title={citation.filename}>
            {citation.filename}
          </h2>
          <p>
            Page {citation.page} · the cited excerpt is highlighted on the
            original PDF.
          </p>
        </div>
        <button
          ref={closeButtonRef}
          type="button"
          onClick={onClose}
          aria-label="Close source preview"
          title="Close preview"
        >
          ×
        </button>
      </header>

      <div className="source-modal-viewer">
        {loading && (
          <div className="source-modal-loading" role="status">
            <span className="source-modal-loader" aria-hidden="true" />
            Rendering the source page…
          </div>
        )}

        {error && (
          <div className="source-modal-error" role="alert">
            <strong>We could not load this original page.</strong>
            <p>{error}</p>
          </div>
        )}

        {imgUrl && !loading && (
          <img
            src={imgUrl}
            alt={`Page ${citation.page} of ${citation.filename}; cited excerpt highlighted`}
          />
        )}
      </div>
    </Dialog>
  )
}

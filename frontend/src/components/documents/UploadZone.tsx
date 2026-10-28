import { useCallback, useRef, useState } from 'react'
import { uploadPdf, type UploadResult } from '../../api/client'
import Icon from '../ui/Icon'

interface UploadZoneProps {
  onUploaded: (result: UploadResult) => void
  onUploadStateChange?: (isUploading: boolean) => void
}

export default function UploadZone({
  onUploaded,
  onUploadStateChange,
}: UploadZoneProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<UploadResult | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const uploadingRef = useRef(false)

  const handleFile = useCallback(
    async (file: File) => {
      if (uploadingRef.current) return
      setError(null)
      setLastResult(null)

      if (!file.name.toLowerCase().endsWith('.pdf')) {
        setError('Επίλεξε ένα αρχείο PDF.')
        return
      }

      uploadingRef.current = true
      setIsUploading(true)
      onUploadStateChange?.(true)
      try {
        const result = await uploadPdf(file)
        setLastResult(result)
        onUploaded(result)
      } catch (uploadError) {
        setError(
          uploadError instanceof Error
            ? uploadError.message
            : 'Η μεταφόρτωση δεν ολοκληρώθηκε.',
        )
      } finally {
        uploadingRef.current = false
        setIsUploading(false)
        onUploadStateChange?.(false)
      }
    },
    [onUploaded, onUploadStateChange],
  )

  const openFilePicker = () => {
    if (!uploadingRef.current) inputRef.current?.click()
  }

  return (
    <section
      className={`upload-dropzone ${isDragging ? 'is-dragging' : ''} ${isUploading ? 'is-uploading' : ''}`}
      onDragOver={(event) => {
        event.preventDefault()
        setIsDragging(true)
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(event) => {
        event.preventDefault()
        setIsDragging(false)
        const file = event.dataTransfer.files?.[0]
        if (file) void handleFile(file)
      }}
      onClick={openFilePicker}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          openFilePicker()
        }
      }}
      role="button"
      tabIndex={0}
      aria-label="Upload a PDF document"
      aria-busy={isUploading}
    >
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) void handleFile(file)
          event.target.value = ''
        }}
      />

      <span className="upload-orb" aria-hidden="true">
        <Icon name="upload" />
      </span>
      <div className="upload-copy">
        <span className="upload-kicker">PDF → INSIGHT</span>
        {isUploading ? (
          <>
            <strong>Indexing your document</strong>
            <p>Extracting text and preparing its evidence trail…</p>
          </>
        ) : (
          <>
            <strong>Drop a PDF to begin</strong>
            <p>Drag it here, or click to choose a document.</p>
          </>
        )}
      </div>

      <span className="upload-action">
        {isUploading ? 'Processing…' : 'Choose a PDF'} <Icon name="arrow" />
      </span>

      <div className="upload-feedback" aria-live="polite">
        {error && <p className="upload-error">{error}</p>}
        {lastResult && !error && (
          <p className="upload-success">
            Ready: {lastResult.filename} · {lastResult.chunk_count} source
            fragments · {lastResult.method === 'ocr' ? 'OCR' : 'digital text'}
          </p>
        )}
      </div>
    </section>
  )
}

import { useCallback, useRef, useState } from 'react'
import { uploadPdf, type UploadResult } from '../api/client'

interface UploadZoneProps {
  onUploaded: (result: UploadResult) => void
}

export default function UploadZone({ onUploaded }: UploadZoneProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<UploadResult | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleFile = useCallback(async (file: File) => {
    setError(null)
    setLastResult(null)

    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setError('Only .pdf files are accepted.')
      return
    }

    setIsUploading(true)
    try {
      const result = await uploadPdf(file)
      setLastResult(result)
      onUploaded(result)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed.')
    } finally {
      setIsUploading(false)
    }
  }, [onUploaded])

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setIsDragging(false)
        const file = e.dataTransfer.files?.[0]
        if (file) handleFile(file)
      }}
      onClick={() => inputRef.current?.click()}
      className={`cursor-pointer rounded-lg border-2 border-dashed p-8 text-center transition-colors
        ${isDragging ? 'border-gold bg-gold/5' : 'border-panel-border bg-panel'}
        hover:border-gold/60`}
    >
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) handleFile(file)
          e.target.value = ''
        }}
      />

      {isUploading ? (
        <div className="text-sm text-gold animate-pulse">Uploading & processing…</div>
      ) : (
        <>
          <p className="text-sm text-gray-300">
            Drag & drop a PDF here, or <span className="text-gold underline">click to browse</span>
          </p>
          <p className="mt-1 text-xs text-gray-500">Digital or scanned PDFs</p>
        </>
      )}

      {error && (
        <p className="mt-3 text-xs text-red-400">{error}</p>
      )}

      {lastResult && !error && (
        <p className="mt-3 text-xs text-green-400">
          {lastResult.filename} — {lastResult.chunk_count} chunks ({lastResult.method === 'ocr' ? 'OCR' : 'digital'})
        </p>
      )}
    </div>
  )
}

import type { Citation } from '../api/client'

interface CitationsPanelProps {
  citations: Citation[]
  hoveredIndex: number | null
}

export default function CitationsPanel({ citations, hoveredIndex }: CitationsPanelProps) {
  if (citations.length === 0) {
    return <p className="text-xs text-gray-500">Citations for the latest answer will appear here.</p>
  }

  return (
    <div className="space-y-3">
      {citations.map((c, i) => (
        <div
          key={i}
          className={`rounded-lg border p-3 text-xs transition-colors
            ${hoveredIndex === i ? 'border-gold bg-gold/5' : 'border-panel-border bg-panel'}`}
        >
          <div className="mb-1 flex items-center justify-between">
            <span className="font-medium text-gold">[{i + 1}]</span>
            <span className="text-[10px] text-gray-500">page {c.page}</span>
          </div>
          <p className="mb-1 truncate text-gray-400">{c.filename}</p>
          <p className="text-gray-300 line-clamp-4">{c.text}</p>
        </div>
      ))}
    </div>
  )
}

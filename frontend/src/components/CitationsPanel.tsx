import type { Citation } from '../api/client'

interface CitationsPanelProps {
  citations: Citation[]
  hoveredIndex: number | null
  onViewSource: (citation: Citation) => void
}

export default function CitationsPanel({ citations, hoveredIndex, onViewSource }: CitationsPanelProps) {
  if (citations.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 py-10 text-center">
        <span className="text-3xl opacity-30">🔖</span>
        <p className="text-xs text-gray-500">Citations for the latest answer will appear here.</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {citations.map((c, i) => (
        <div
          key={i}
          onClick={() => onViewSource(c)}
          style={{ animationDelay: `${i * 40}ms` }}
          className={`card-hover animate-fade-in-up cursor-pointer rounded-lg border p-3 text-xs transition-colors
            ${hoveredIndex === i ? 'border-gold bg-gold/5' : 'border-panel-border bg-panel hover:border-gold/40'}`}
        >
          <div className="mb-1.5 flex items-center justify-between">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-gold/15 text-[10px] font-semibold text-gold">
              {i + 1}
            </span>
            <span className="text-[10px] text-gray-500">page {c.page}</span>
          </div>
          <p className="mb-1 truncate text-gray-400">{c.filename}</p>
          <p className="text-gray-300 line-clamp-4">{c.text}</p>
          <p className="mt-1 text-[10px] text-gold/70">View source page →</p>
        </div>
      ))}
    </div>
  )
}

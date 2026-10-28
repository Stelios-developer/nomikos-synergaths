import type { Citation } from '../../api/client'

interface CitationsPanelProps {
  citations: Citation[]
  hoveredIndex: number | null
  onViewSource: (citation: Citation) => void
}

export default function CitationsPanel({ citations, hoveredIndex, onViewSource }: CitationsPanelProps) {
  if (citations.length === 0) {
    return (
      <div className="citation-empty">
        <span className="citation-empty-mark" aria-hidden="true"><i /></span>
        <strong>Your evidence trail will appear here.</strong>
        <p>Ask a question to inspect the exact PDF page behind each answer.</p>
      </div>
    )
  }

  return (
    <div className="citation-panel-list">
      <div className="citation-panel-heading">
        <span>{citations.length} linked sources</span>
        <small>Open any source</small>
      </div>
      {citations.map((citation, index) => (
        <button
          key={`${citation.filename}-${citation.page}-${index}`}
          type="button"
          onClick={() => onViewSource(citation)}
          className={`citation-source-card ${hoveredIndex === index ? 'is-hovered' : ''}`}
          style={{ animationDelay: `${index * 45}ms` }}
        >
          <span className="citation-source-index">{String(index + 1).padStart(2, '0')}</span>
          <span className="citation-source-head">
            <strong title={citation.filename}>{citation.filename}</strong>
            <small>PAGE {citation.page}</small>
          </span>
          <span className="citation-source-excerpt">{citation.text}</span>
          <span className="citation-source-open">View original page <i aria-hidden="true">↗</i></span>
        </button>
      ))}
    </div>
  )
}

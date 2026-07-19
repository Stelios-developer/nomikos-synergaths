import type { ReactNode } from 'react'
import type { Citation, SentenceVerdict } from '../api/client'

export interface CitationHandlers {
  citations?: Citation[]
  onHoverCitation?: (i: number | null) => void
  onViewCitation?: (citation: Citation) => void
}

// Splits one line of text on citation markers ([1], [2], ...) and **bold**
// spans, rendering the former as hoverable/clickable <sup> badges (same
// interaction as the original Document Assistant chat: hover highlights
// the matching source card, click opens the original PDF page) and the
// latter as <strong>. This is the single place both concerns compose,
// which is why block-level rendering below always routes inline text
// through here rather than dumping raw strings.
function renderInline(text: string, handlers: CitationHandlers, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = []
  const citationParts = text.split(/(\[\d+\])/g)

  citationParts.forEach((part, i) => {
    const citationMatch = part.match(/^\[(\d+)\]$/)
    if (citationMatch) {
      const citationIndex = parseInt(citationMatch[1], 10) - 1
      const citation = handlers.citations?.[citationIndex]
      nodes.push(
        <sup
          key={`${keyPrefix}-c${i}`}
          onMouseEnter={() => handlers.onHoverCitation?.(citationIndex)}
          onMouseLeave={() => handlers.onHoverCitation?.(null)}
          onClick={() => citation && handlers.onViewCitation?.(citation)}
          className={`mx-0.5 rounded bg-gold/20 px-1 font-medium text-gold ${
            citation ? 'cursor-pointer hover:bg-gold/30' : ''
          }`}
        >
          {part}
        </sup>,
      )
      return
    }

    const boldParts = part.split(/(\*\*[^*]+\*\*)/g)
    boldParts.forEach((seg, j) => {
      const boldMatch = seg.match(/^\*\*([^*]+)\*\*$/)
      if (boldMatch) {
        nodes.push(
          <strong key={`${keyPrefix}-b${i}-${j}`} className="font-semibold text-gray-50">
            {boldMatch[1]}
          </strong>,
        )
        return
      }
      if (seg) nodes.push(<span key={`${keyPrefix}-t${i}-${j}`}>{seg}</span>)
    })
  })

  return nodes
}

// Renders LLM-generated markdown-lite (headers, **bold**, -/* bullets,
// 1. numbered lists, > blockquotes, --- rules, paragraphs) as real
// elements instead of dumping the literal characters as plain text — every
// agent in this app (Advisory Panel, Debate Agents, Research Agent,
// Supervisor, Document Assistant) prompts the model in prose but the
// model naturally reaches for this formatting, and it was previously
// showing up as literal "**" / "#" in the UI.
export function renderRichText(text: string, handlers: CitationHandlers = {}): ReactNode {
  const lines = text.split('\n')
  const blocks: ReactNode[] = []
  let paragraphLines: string[] = []
  let listItems: string[] = []
  let listType: 'ul' | 'ol' | null = null
  let blockIndex = 0

  const flushParagraph = () => {
    if (paragraphLines.length) {
      const joined = paragraphLines.join(' ').trim()
      if (joined) {
        blocks.push(
          <p key={`p-${blockIndex++}`} className="leading-relaxed">
            {renderInline(joined, handlers, `p${blockIndex}`)}
          </p>,
        )
      }
      paragraphLines = []
    }
  }

  const flushList = () => {
    if (listItems.length && listType) {
      const Tag = listType
      blocks.push(
        <Tag
          key={`l-${blockIndex++}`}
          className={`space-y-1 pl-5 ${listType === 'ul' ? 'list-disc' : 'list-decimal'}`}
        >
          {listItems.map((item, i) => (
            <li key={i}>{renderInline(item, handlers, `li${blockIndex}-${i}`)}</li>
          ))}
        </Tag>,
      )
      listItems = []
      listType = null
    }
  }

  for (const rawLine of lines) {
    const trimmed = rawLine.trim()

    if (!trimmed) {
      flushParagraph()
      flushList()
      continue
    }

    const h3 = trimmed.match(/^###\s+(.*)/)
    const h2 = trimmed.match(/^##\s+(.*)/)
    const h1 = trimmed.match(/^#\s+(.*)/)
    const bullet = trimmed.match(/^[-*]\s+(.*)/)
    const numbered = trimmed.match(/^\d+\.\s+(.*)/)
    const quote = trimmed.match(/^>\s*(.*)/)
    const isRule = /^-{3,}$/.test(trimmed)

    if (isRule) {
      flushParagraph()
      flushList()
      blocks.push(<hr key={`hr-${blockIndex++}`} className="border-panel-border" />)
    } else if (h3 || h2 || h1) {
      flushParagraph()
      flushList()
      const heading = (h3 || h2 || h1)!
      const size = h3 ? 'text-xs' : h2 ? 'text-sm' : 'text-[15px]'
      blocks.push(
        <p key={`h-${blockIndex++}`} className={`${size} font-semibold text-gray-100`}>
          {renderInline(heading[1], handlers, `h${blockIndex}`)}
        </p>,
      )
    } else if (bullet) {
      flushParagraph()
      if (listType !== 'ul') flushList()
      listType = 'ul'
      listItems.push(bullet[1])
    } else if (numbered) {
      flushParagraph()
      if (listType !== 'ol') flushList()
      listType = 'ol'
      listItems.push(numbered[1])
    } else if (quote) {
      flushParagraph()
      flushList()
      blocks.push(
        <blockquote key={`q-${blockIndex++}`} className="border-l-2 border-gold/40 pl-3 italic text-gray-400">
          {renderInline(quote[1], handlers, `q${blockIndex}`)}
        </blockquote>,
      )
    } else {
      paragraphLines.push(trimmed)
    }
  }
  flushParagraph()
  flushList()

  return <div className="space-y-2">{blocks}</div>
}

// Hallucination Auditor variant: same inline rendering (bold + citation
// markers), but wraps each already-graded sentence in supported/
// unsupported styling instead of parsing block structure — the answer is
// already complete at this point, so per-sentence trust signal matters
// more than re-deriving headers/lists.
export function renderAuditedRichText(sentences: SentenceVerdict[], handlers: CitationHandlers = {}): ReactNode {
  return (
    <p className="leading-relaxed">
      {sentences.map((s, i) => (
        <span
          key={i}
          title={s.reason}
          className={
            s.supported ? '' : 'rounded bg-red-500/10 underline decoration-red-400 decoration-2 underline-offset-2'
          }
        >
          {renderInline(s.text + ' ', handlers, `audit${i}`)}
        </span>
      ))}
    </p>
  )
}

import { useState } from 'react'
import { askQuestionStream, auditAnswer, type Citation, type HistoryTurn, type SentenceVerdict } from '../api/client'
import { renderRichText, renderAuditedRichText } from '../utils/richText'

interface Message {
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  auditResult?: SentenceVerdict[]
  auditing?: boolean
}

interface ChatInterfaceProps {
  documentFilter: string | null
  onCitations: (citations: Citation[]) => void
  onHoverCitation: (index: number | null) => void
  onViewCitation: (citation: Citation) => void
}

const SAMPLE_QUESTIONS = [
  'Ποια είναι η προθεσμία υποβολής της δήλωσης;',
  'Τι ποσοστό έκπτωσης ισχύει για δαπάνες Ε&Α;',
  'Ποιο είναι το ανώτατο όριο εξόδων ταξιδιού;',
  'Ποιος είναι υπεύθυνος επικοινωνίας για φορολογικά θέματα;',
]

export default function ChatInterface({ documentFilter, onCitations, onHoverCitation, onViewCitation }: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [isRetrieving, setIsRetrieving] = useState(false)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)

  const send = async (question: string) => {
    if (!question || isStreaming) return

    // Prior completed turns, captured before we push the new (still-empty)
    // exchange below — this is what lets follow-ups like "and the second
    // point?" resolve against what was actually said, not against the
    // in-flight placeholder we're about to add.
    const history: HistoryTurn[] = messages
      .filter((m) => m.content.trim().length > 0)
      .map((m) => ({ role: m.role, content: m.content }))

    setMessages((prev) => [...prev, { role: 'user', content: question }, { role: 'assistant', content: '' }])
    setInput('')
    setIsRetrieving(true)
    setStatusMessage(null)

    const updateLastAssistant = (updater: (msg: Message) => Message) => {
      setMessages((prev) => {
        const next = [...prev]
        next[next.length - 1] = updater(next[next.length - 1])
        return next
      })
    }

    try {
      let firstToken = true
      const { citations } = await askQuestionStream(
        question,
        documentFilter ?? undefined,
        history,
        (token) => {
          if (firstToken) {
            setIsRetrieving(false)
            setIsStreaming(true)
            setStatusMessage(null)
            firstToken = false
          }
          updateLastAssistant((msg) => ({ ...msg, content: msg.content + token }))
        },
        // Surfaces the agent's evaluate/rephrase retry loop (see
        // services/agent.py :: agentic_retrieve_stream) — normally
        // invisible backend behavior, now shown as a transient status line
        // so a "no good chunks yet, trying a different phrasing" retry is
        // visible instead of just a longer wait before the answer appears.
        (message) => setStatusMessage(message),
      )
      updateLastAssistant((msg) => ({ ...msg, citations }))
      onCitations(citations)
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Something went wrong.'
      updateLastAssistant((msg) => ({ ...msg, content: `⚠ ${message}` }))
    } finally {
      setIsRetrieving(false)
      setIsStreaming(false)
      setStatusMessage(null)
    }
  }

  const handleSend = () => send(input.trim())

  // On-demand hallucination audit (services/auditor.py): grades every
  // sentence of an already-completed answer as supported/unsupported by
  // its own citations. Deliberately NOT run automatically on every
  // message — it's an extra LLM call, so it's opt-in per message via the
  // "Έλεγχος πηγών" button below each answer.
  const auditMessage = async (index: number) => {
    const target = messages[index]
    if (!target || target.role !== 'assistant' || !target.citations?.length) return

    setMessages((prev) => {
      const next = [...prev]
      next[index] = { ...next[index], auditing: true }
      return next
    })

    try {
      const sentences = await auditAnswer(target.content, target.citations)
      setMessages((prev) => {
        const next = [...prev]
        next[index] = { ...next[index], auditResult: sentences, auditing: false }
        return next
      })
    } catch {
      setMessages((prev) => {
        const next = [...prev]
        next[index] = { ...next[index], auditing: false }
        return next
      })
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto pb-4">
        {messages.length === 0 && (
          <div className="flex flex-col items-center gap-4 py-10 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gold/10 text-2xl">💬</div>
            <p className="text-sm text-gray-500">
              Ask a question about your uploaded documents.
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              {SAMPLE_QUESTIONS.map((q) => (
                <button
                  key={q}
                  onClick={() => send(q)}
                  className="rounded-full border border-panel-border bg-panel px-3 py-1.5 text-xs text-gray-300
                    transition-all hover:-translate-y-0.5 hover:border-gold/50 hover:text-gold hover:shadow-md hover:shadow-gold/5"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) => {
          const isLast = i === messages.length - 1
          const finishedStreaming = m.role === 'assistant' && m.content && (!isLast || (!isStreaming && !isRetrieving))
          return (
            <div key={i} className={`animate-fade-in-up ${m.role === 'user' ? 'text-right' : 'text-left'}`}>
              <div
                className={`inline-block max-w-[80%] rounded-lg px-3 py-2 text-sm shadow-sm
                  ${m.role === 'user' ? 'bg-gold/15 text-gray-100' : 'border border-panel-border bg-panel text-gray-200'}`}
              >
                {m.role === 'assistant'
                  ? m.auditResult
                    ? renderAuditedRichText(m.auditResult, {
                        citations: m.citations,
                        onHoverCitation,
                        onViewCitation,
                      })
                    : renderRichText(m.content, { citations: m.citations, onHoverCitation, onViewCitation })
                  : m.content}
                {m.role === 'assistant' && isLast && isStreaming && (
                  <span className="ml-0.5 inline-block h-3.5 w-[2px] animate-blink bg-gold align-middle" />
                )}
                {m.role === 'assistant' && isLast && isRetrieving && (
                  <span className="ml-1 animate-pulse text-gray-500">● ● ●</span>
                )}
              </div>
              {m.role === 'assistant' && isLast && statusMessage && (
                <p className="mt-1 text-[11px] italic text-gray-500">{statusMessage}</p>
              )}
              {m.role === 'assistant' && finishedStreaming && (m.citations?.length ?? 0) > 0 && (
                <div className="mt-1">
                  {m.auditing ? (
                    <span className="text-[11px] italic text-gray-500">Ελέγχονται οι πηγές…</span>
                  ) : m.auditResult ? (
                    <span className="text-[11px] text-gray-500">
                      🔎 {m.auditResult.filter((s) => s.supported).length}/{m.auditResult.length} προτάσεις
                      τεκμηριωμένες
                    </span>
                  ) : (
                    <button
                      onClick={() => auditMessage(i)}
                      className="text-[11px] text-gray-500 underline decoration-dotted transition-colors hover:text-gold"
                    >
                      🔎 Έλεγχος πηγών
                    </button>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div className="flex gap-2 border-t border-panel-border pt-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder={documentFilter ? `Ask about ${documentFilter}…` : 'Ask about your documents…'}
          className="flex-1 rounded-md border border-panel-border bg-panel px-3 py-2 text-sm text-gray-100
            placeholder:text-gray-500 transition-colors focus:border-gold focus:outline-none"
        />
        <button
          onClick={handleSend}
          disabled={isStreaming || isRetrieving || !input.trim()}
          className="rounded-md bg-gold px-4 py-2 text-sm font-medium text-black transition-all
            hover:brightness-110 active:scale-95 disabled:opacity-40 disabled:hover:brightness-100"
        >
          Send
        </button>
      </div>
    </div>
  )
}

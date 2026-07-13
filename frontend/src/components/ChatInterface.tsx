import { useState } from 'react'
import { askQuestionStream, type Citation } from '../api/client'

interface Message {
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
}

interface ChatInterfaceProps {
  documentFilter: string | null
  onCitations: (citations: Citation[]) => void
  onHoverCitation: (index: number | null) => void
}

// Splits "... [1] ... [2] ..." into text + clickable citation markers.
function renderWithCitations(text: string, onHover: (i: number | null) => void) {
  const parts = text.split(/(\[\d+\])/g)
  return parts.map((part, i) => {
    const match = part.match(/^\[(\d+)\]$/)
    if (!match) return <span key={i}>{part}</span>
    const citationIndex = parseInt(match[1], 10) - 1
    return (
      <sup
        key={i}
        onMouseEnter={() => onHover(citationIndex)}
        onMouseLeave={() => onHover(null)}
        className="mx-0.5 cursor-pointer rounded bg-gold/20 px-1 text-gold"
      >
        {part}
      </sup>
    )
  })
}

export default function ChatInterface({ documentFilter, onCitations, onHoverCitation }: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [isRetrieving, setIsRetrieving] = useState(false)

  const handleSend = async () => {
    const question = input.trim()
    if (!question || isStreaming) return

    setMessages((prev) => [...prev, { role: 'user', content: question }, { role: 'assistant', content: '' }])
    setInput('')
    setIsRetrieving(true)

    const updateLastAssistant = (updater: (msg: Message) => Message) => {
      setMessages((prev) => {
        const next = [...prev]
        next[next.length - 1] = updater(next[next.length - 1])
        return next
      })
    }

    try {
      let firstToken = true
      const { citations } = await askQuestionStream(question, documentFilter ?? undefined, (token) => {
        if (firstToken) {
          setIsRetrieving(false)
          setIsStreaming(true)
          firstToken = false
        }
        updateLastAssistant((msg) => ({ ...msg, content: msg.content + token }))
      })
      updateLastAssistant((msg) => ({ ...msg, citations }))
      onCitations(citations)
    } catch (e) {
      const message = e instanceof Error ? e.message : 'Something went wrong.'
      updateLastAssistant((msg) => ({ ...msg, content: `⚠ ${message}` }))
    } finally {
      setIsRetrieving(false)
      setIsStreaming(false)
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto pb-4">
        {messages.length === 0 && (
          <p className="text-sm text-gray-500">
            Ask a question about your uploaded documents.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'text-right' : 'text-left'}>
            <div
              className={`inline-block max-w-[80%] rounded-lg px-3 py-2 text-sm
                ${m.role === 'user' ? 'bg-gold/15 text-gray-100' : 'bg-panel border border-panel-border text-gray-200'}`}
            >
              {m.role === 'assistant' ? renderWithCitations(m.content, onHoverCitation) : m.content}
              {m.role === 'assistant' && i === messages.length - 1 && isRetrieving && (
                <span className="ml-1 animate-pulse text-gray-500">● ● ●</span>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="flex gap-2 border-t border-panel-border pt-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder={documentFilter ? `Ask about ${documentFilter}…` : 'Ask about your documents…'}
          className="flex-1 rounded-md border border-panel-border bg-panel px-3 py-2 text-sm text-gray-100
            placeholder:text-gray-500 focus:border-gold focus:outline-none"
        />
        <button
          onClick={handleSend}
          disabled={isStreaming || isRetrieving || !input.trim()}
          className="rounded-md bg-gold px-4 py-2 text-sm font-medium text-black disabled:opacity-40"
        >
          Send
        </button>
      </div>
    </div>
  )
}

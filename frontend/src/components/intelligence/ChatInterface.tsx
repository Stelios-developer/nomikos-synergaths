import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react'
import {
  askQuestionStream,
  auditAnswer,
  type Citation,
  type HistoryTurn,
  type SentenceVerdict,
} from '../../api/client'
import { renderRichText } from '../../utils/richText'
import { BRAND_NAME } from '../../brand'

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

const QUICK_PROMPTS = [
  {
    label: 'Προθεσμίες',
    detail: 'Βρες όλες τις ημερομηνίες',
    prompt:
      'Ποιες είναι όλες οι προθεσμίες και ποιος είναι ο υπεύθυνος για καθεμία;',
  },
  {
    label: 'Κίνδυνοι',
    detail: 'Εξήγησε τι χρειάζεται προσοχή',
    prompt: 'Ποιοι είναι οι βασικοί κίνδυνοι και ποιες ενέργειες προτείνονται;',
  },
  {
    label: 'Υποχρεώσεις',
    detail: 'Σύνοψη των απαιτήσεων',
    prompt: 'Ποιες υποχρεώσεις και προϋποθέσεις περιγράφονται στα έγγραφα;',
  },
]

const DEMO_PROMPTS = [
  { label: 'Deadlines', detail: 'Recorded AI answer', prompt: 'What are the main deadlines, and who is responsible for each?' },
  { label: 'Risks & approvals', detail: 'Recorded AI answer', prompt: 'What risks and approval requirements are stated in the agreement?' },
]

export default function ChatInterface({
  documentFilter,
  onCitations,
  onHoverCitation,
  onViewCitation,
}: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [isRetrieving, setIsRetrieving] = useState(false)
  const [isAuditing, setIsAuditing] = useState(false)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const streamRef = useRef<HTMLDivElement>(null)
  const requestEpoch = useRef(0)
  const pending = useRef<AbortController | null>(null)
  const cancelPending = useCallback(() => {
    requestEpoch.current++
    pending.current?.abort()
  }, [])

  useEffect(() => {
    cancelPending()
    setMessages([])
    setInput('')
    setIsRetrieving(false)
    setIsStreaming(false)
    setIsAuditing(false)
    setStatusMessage(null)
    onCitations([])
    return cancelPending
  }, [documentFilter, onCitations, cancelPending])

  useEffect(() => {
    const stream = streamRef.current
    if (stream && messages.length > 0)
      stream.scrollTo({
        top: stream.scrollHeight,
        behavior:
          isStreaming ||
          window.matchMedia('(prefers-reduced-motion: reduce)').matches
            ? 'auto'
            : 'smooth',
      })
  }, [messages, isStreaming, isRetrieving, isAuditing])

  const send = async (question: string) => {
    if (!question || isStreaming || isRetrieving || isAuditing) return
    const epoch = ++requestEpoch.current
    const controller = new AbortController()
    pending.current?.abort()
    pending.current = controller

    const history: HistoryTurn[] = messages
      .filter((message) => message.content.trim().length > 0)
      .map((message) => ({ role: message.role, content: message.content }))

    setMessages((previous) => [
      ...previous,
      { role: 'user', content: question },
      { role: 'assistant', content: '' },
    ])
    setInput('')
    setIsRetrieving(true)
    setStatusMessage(null)

    const updateLastAssistant = (updater: (message: Message) => Message) => {
      if (epoch !== requestEpoch.current) return
      setMessages((previous) => {
        const next = [...previous]
        const lastIndex = next.length - 1
        if (next[lastIndex]) next[lastIndex] = updater(next[lastIndex])
        return next
      })
    }

    try {
      let firstToken = true
      let completedAnswer = ''
      const { citations } = await askQuestionStream(
        question,
        documentFilter ?? undefined,
        history,
        (token) => {
          if (epoch !== requestEpoch.current) return
          if (firstToken) {
            setIsRetrieving(false)
            setIsStreaming(true)
            setStatusMessage(null)
            firstToken = false
          }
          completedAnswer += token
          updateLastAssistant((message) => ({
            ...message,
            content: message.content + token,
          }))
        },
        (message) => { if (epoch === requestEpoch.current) setStatusMessage(message) },
        controller.signal,
      )
      if (epoch !== requestEpoch.current) return
      updateLastAssistant((message) => ({ ...message, citations }))
      onCitations(citations)

      if (citations.length > 0 && completedAnswer.trim()) {
        setIsStreaming(false)
        setIsAuditing(true)
        setStatusMessage('Verifying the completed answer against its sources…')
        updateLastAssistant((message) => ({ ...message, auditing: true }))
        try {
          const sentences = await auditAnswer(completedAnswer, citations, controller.signal)
          updateLastAssistant((message) => ({
            ...message,
            auditResult: sentences,
            auditing: false,
          }))
        } catch {
          updateLastAssistant((message) => ({ ...message, auditing: false }))
        } finally {
          if (epoch === requestEpoch.current) {
            setIsAuditing(false)
            setStatusMessage(null)
          }
        }
      }
    } catch (requestError) {
      if (epoch !== requestEpoch.current || controller.signal.aborted) return
      const errorMessage =
        requestError instanceof Error
          ? requestError.message
          : 'Κάτι δεν ολοκληρώθηκε σωστά.'
      updateLastAssistant((message) => ({
        ...message,
        content: `Δεν ήταν δυνατή η απάντηση: ${errorMessage}`,
      }))
    } finally {
      if (epoch === requestEpoch.current) {
        pending.current = null
        setIsRetrieving(false)
        setIsStreaming(false)
        setIsAuditing(false)
        setStatusMessage(null)
      }
    }
  }

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      void send(input.trim())
    }
  }

  const conversationScope = documentFilter ?? 'Όλη η βιβλιοθήκη'

  return (
    <div className="chat-workspace">
      <div className="chat-context-bar">
        <div>
          <span className="chat-context-label">ASKING ABOUT</span>
          <strong title={conversationScope}>{conversationScope}</strong>
        </div>
        <span className="chat-grounded-badge">
          <span />
          Evidence-first
        </span>
      </div>

      <div className="chat-stream" ref={streamRef} aria-live="polite">
        {messages.length === 0 && (
          <div className="chat-empty-state">
            <div className="chat-empty-signal" aria-hidden="true">
              <span />
            </div>
            <span className="eyebrow">START AN INVESTIGATION</span>
            <h3>
              {documentFilter
                ? 'What do you want to know about this document?'
                : 'Ask across your document library.'}
            </h3>
            <p>
              Answers are grounded in retrieved source excerpts. Open any
              citation to inspect the original page.
            </p>
            <div className="quick-prompt-grid">
              {(import.meta.env.VITE_DEMO_MODE === 'true' ? DEMO_PROMPTS : QUICK_PROMPTS).map((prompt) => (
                <button
                  key={prompt.label}
                  type="button"
                  disabled={isStreaming || isRetrieving || isAuditing}
                  onClick={() => void send(prompt.prompt)}
                >
                  <span>{prompt.label}</span>
                  <small>{prompt.detail}</small>
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message, index) => {
          const isLast = index === messages.length - 1
          const finished =
            message.role === 'assistant' &&
            message.content &&
            (!isLast || (!isStreaming && !isRetrieving))
          const supportedCount = message.auditResult?.filter(
            (sentence) => sentence.supported,
          ).length
          const verificationUnavailable = message.auditResult?.some(
            (sentence) => sentence.verification_unavailable,
          )

          return (
            <article
              key={`${message.role}-${index}`}
              className={`message-row ${message.role === 'user' ? 'is-user' : 'is-assistant'}`}
            >
              <div className="message-meta">
                <span>{message.role === 'user' ? 'YOU' : BRAND_NAME}</span>
                {message.role === 'assistant' && <i aria-hidden="true" />}
              </div>
              <div className="message-card">
                {message.role === 'assistant'
                  ? renderRichText(message.content, {
                        citations: message.citations,
                        onHoverCitation,
                        onViewCitation,
                      })
                  : message.content}
                {message.role === 'assistant' && isLast && isStreaming && (
                  <span
                    className="message-cursor"
                    aria-label="Answer is streaming"
                  />
                )}
                {message.role === 'assistant' && isLast && isRetrieving && (
                  <span className="message-thinking">Retrieving evidence…</span>
                )}
              </div>

              {message.role === 'assistant' && isLast && statusMessage && (
                <p className="message-status">{statusMessage}</p>
              )}

              {message.role === 'assistant' &&
                finished &&
                (message.citations?.length ?? 0) > 0 && (
                  <div className="message-evidence-row">
                    <span>
                      {message.citations?.length} linked source
                      {message.citations?.length === 1 ? '' : 's'}
                    </span>
                    {message.auditing ? (
                      <span className="message-audit-pending">
                        Verifying claims…
                      </span>
                    ) : verificationUnavailable ? (
                      <span className="message-audit-pending">
                        {message.auditResult?.filter((sentence) => !sentence.supported).length} claims need source review · AI checks can be wrong
                      </span>
                    ) : message.auditResult ? (
                      <span
                        className="message-audit-result"
                      >
                        AI evidence check: {supportedCount}/
                        {message.auditResult.length} appear supported · review the source
                      </span>
                    ) : (
                      <span className="message-audit-pending">
                        Evidence check unavailable
                      </span>
                    )}
                  </div>
                )}
            </article>
          )
        })}
      </div>

      <div className="chat-composer-wrap">
        <label className="sr-only" htmlFor="document-question">
          Ask a question about your documents
        </label>
        <div className="chat-composer">
          <textarea
            id="document-question"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleComposerKeyDown}
            placeholder={
              documentFilter
                ? `Ρώτησε για το ${documentFilter}`
                : 'Ρώτησε για τα έγγραφά σου'
            }
            rows={1}
            disabled={isStreaming || isRetrieving || isAuditing}
          />
          <button
            type="button"
            onClick={() => void send(input.trim())}
            disabled={
              isStreaming || isRetrieving || isAuditing || !input.trim()
            }
          >
            <span>
              {isAuditing
                ? 'Checking'
                : isStreaming || isRetrieving
                  ? 'Thinking'
                  : 'Ask'}
            </span>
            <i aria-hidden="true">↗</i>
          </button>
        </div>
        <p>
          Enter to send · Shift + Enter for a new line · Sources remain attached
          to every answer
        </p>
      </div>
    </div>
  )
}

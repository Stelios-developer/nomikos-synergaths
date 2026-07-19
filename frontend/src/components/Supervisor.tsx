import { useState } from 'react'
import { runSupervisor, type Citation, type AgentResult } from '../api/client'
import { renderRichText } from '../utils/richText'
import PdfPageModal from './PdfPageModal'
import AgentKeyUnlock from './AgentKeyUnlock'

interface ActionTraceStep {
  attempt: number
  code: string
  status: 'pending' | 'rejected' | 'running' | 'error' | 'ok'
  reviewFeedback?: string
  errorMessage?: string
}

interface RagStep {
  kind: 'rag'
  query: string
  text: string
  citations: Citation[]
}

interface ActionStep {
  kind: 'action'
  goal: string
  plan: string[]
  trace: ActionTraceStep[]
  result: AgentResult | null
}

type SupervisorStep = RagStep | ActionStep

const SAMPLE_GOALS = [
  'Βρες τον συντελεστή έκπτωσης Ε&Α στο PDF και υπολόγισε πόση έκπτωση αντιστοιχεί σε δαπάνες 50.000€.',
  'Ποια είναι η προθεσμία υποβολής δήλωσης;',
  'Compute compound interest on €10,000 at 5% for 10 years and plot the growth curve.',
]

interface Props {
  agentEnabled: boolean
  onUnlocked: () => void
}

// Orchestrates the two previously-independent subsystems (Document
// Assistant + Action Agent) instead of duplicating either: a supervisor
// agent decides, via native tool-calling, whether a request needs
// document retrieval, code execution, or both chained together. Every
// event here is forwarded from services/supervisor.py, which itself just
// calls into the existing RAG pipeline and Action Agent — no new
// retrieval or execution logic lives behind this tab.
//
// Unlike the standalone Action Agent, run_code here is OPTIONAL rather
// than a hard gate: when agentEnabled is false, the backend simply never
// offers run_code to the LLM (services/supervisor.py::_tools_for), so this
// tab stays fully interactive and degrades to a documents-only assistant —
// it just shows a small dismissable-by-unlocking notice instead of
// replacing the whole UI.
export default function Supervisor({ agentEnabled, onUnlocked }: Props) {
  const [question, setQuestion] = useState('')
  const [steps, setSteps] = useState<SupervisorStep[]>([])
  const [running, setRunning] = useState(false)
  const [finalSummary, setFinalSummary] = useState<string | null>(null)
  const [finalError, setFinalError] = useState<string | null>(null)
  const [viewingCitation, setViewingCitation] = useState<Citation | null>(null)

  const run = async (q: string) => {
    if (!q || running) return
    setRunning(true)
    setQuestion(q)
    setSteps([])
    setFinalSummary(null)
    setFinalError(null)

    const updateLastAction = (updater: (step: ActionStep) => ActionStep) => {
      setSteps((prev) => {
        const next = [...prev]
        const last = next[next.length - 1]
        if (last?.kind === 'action') next[next.length - 1] = updater(last)
        return next
      })
    }

    try {
      const result = await runSupervisor(q, undefined, {
        onRoute: (tool, input) => {
          setSteps((prev) => [
            ...prev,
            tool === 'search_documents'
              ? ({ kind: 'rag', query: input, text: '', citations: [] } as RagStep)
              : ({ kind: 'action', goal: input, plan: [], trace: [], result: null } as ActionStep),
          ])
        },
        onRagToken: (content) => {
          setSteps((prev) => {
            const next = [...prev]
            const last = next[next.length - 1]
            if (last?.kind === 'rag') next[next.length - 1] = { ...last, text: last.text + content }
            return next
          })
        },
        onRagDone: (citations) => {
          setSteps((prev) => {
            const next = [...prev]
            const last = next[next.length - 1]
            if (last?.kind === 'rag') next[next.length - 1] = { ...last, citations }
            return next
          })
        },
        onActionPlan: (plan) => updateLastAction((s) => ({ ...s, plan })),
        onActionCode: (attempt, code) =>
          updateLastAction((s) => ({
            ...s,
            trace: [
              ...s.trace.map((t) => (t.status === 'running' ? { ...t, status: 'ok' as const } : t)),
              { attempt, code, status: 'pending' as const },
            ],
          })),
        onActionReview: (attempt, approved, feedback) =>
          updateLastAction((s) => ({
            ...s,
            trace: s.trace.map((t) =>
              t.attempt === attempt
                ? { ...t, status: approved ? ('running' as const) : ('rejected' as const), reviewFeedback: feedback }
                : t,
            ),
          })),
        onActionError: (attempt, message) =>
          updateLastAction((s) => ({
            ...s,
            trace: s.trace.map((t) => (t.attempt === attempt ? { ...t, status: 'error' as const, errorMessage: message } : t)),
          })),
        onActionDone: (result) =>
          updateLastAction((s) => ({
            ...s,
            trace: s.trace.map((t) => (t.status === 'running' ? { ...t, status: 'ok' as const } : t)),
            result,
          })),
      })

      if (result.error) setFinalError(result.summary)
      else setFinalSummary(result.summary)
    } catch (e) {
      setFinalError(e instanceof Error ? e.message : 'Κάτι πήγε στραβά.')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col gap-4 p-6">
      <div>
        <h2 className="mb-1 font-display text-base font-semibold text-gold">Supervisor</h2>
        <p className="text-xs text-gray-500">
          Ένας agent-δρομολογητής αποφασίζει μόνος του αν το αίτημά σου χρειάζεται αναζήτηση στα{' '}
          <span className="text-gray-300">έγγραφα</span>, εκτέλεση <span className="text-gray-300">κώδικα</span>,
          ή και τα δύο σε σειρά — ενώνοντας τον Document Assistant και τον Action Agent σε ένα ενιαίο pipeline.
        </p>
      </div>

      {!agentEnabled && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-panel-border bg-panel/60 px-3 py-2 text-[11px] text-gray-400">
          <span>🔒 Η εκτέλεση κώδικα είναι κλειδωμένη — ο Supervisor θα απαντά μόνο από τα έγγραφα.</span>
          <AgentKeyUnlock onUnlocked={onUnlocked} compact />
        </div>
      )}

      {steps.length === 0 && !running && (
        <div className="flex flex-col items-center gap-4 py-10 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gold/10 text-2xl">🧭</div>
          <div className="flex flex-wrap justify-center gap-2">
            {SAMPLE_GOALS.map((g) => (
              <button
                key={g}
                onClick={() => run(g)}
                className="rounded-full border border-panel-border bg-panel px-3 py-1.5 text-xs text-gray-300
                  transition-all hover:-translate-y-0.5 hover:border-gold/50 hover:text-gold hover:shadow-md hover:shadow-gold/5"
              >
                {g}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex gap-2">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && run(question.trim())}
          placeholder="π.χ. Βρες το X στο PDF και υπολόγισε το Y…"
          className="flex-1 rounded-md border border-panel-border bg-panel px-3 py-2 text-sm text-gray-100
            placeholder:text-gray-500 transition-colors focus:border-gold focus:outline-none"
        />
        <button
          onClick={() => run(question.trim())}
          disabled={running || !question.trim()}
          className="rounded-md bg-gold px-4 py-2 text-sm font-medium text-black transition-all
            hover:brightness-110 active:scale-95 disabled:opacity-40 disabled:hover:brightness-100"
        >
          {running ? 'Εκτελείται…' : 'Run'}
        </button>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto">
        {steps.map((step, i) =>
          step.kind === 'rag' ? (
            <div key={i} className="animate-fade-in-up rounded-lg border border-panel-border bg-panel p-3 text-xs">
              <p className="mb-2 font-medium text-gold">🔍 search_documents: "{step.query}"</p>
              <div className="text-gray-200">
                {renderRichText(step.text, { citations: step.citations, onViewCitation: setViewingCitation })}
              </div>
              {step.citations.length > 0 && (
                <div className="mt-2 space-y-1 border-t border-panel-border pt-2">
                  {step.citations.map((c, ci) => (
                    <p
                      key={ci}
                      onClick={() => setViewingCitation(c)}
                      className="cursor-pointer text-[10px] text-gray-500 transition-colors hover:text-gold"
                    >
                      [{ci + 1}] {c.filename}, σελ. {c.page}
                    </p>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div key={i} className="animate-fade-in-up rounded-lg border border-panel-border bg-panel p-3 text-xs">
              <p className="mb-2 font-medium text-gold">⚡ run_code: "{step.goal}"</p>
              {step.plan.length > 0 && (
                <ol className="mb-2 list-inside list-decimal space-y-1 text-gray-400">
                  {step.plan.map((s, si) => (
                    <li key={si}>{s}</li>
                  ))}
                </ol>
              )}
              <div className="space-y-2">
                {step.trace.map((t) => (
                  <div key={t.attempt} className="rounded border border-panel-border bg-black/20 p-2">
                    <div className="mb-1 flex items-center gap-2">
                      <span className="text-gray-400">Προσπάθεια {t.attempt}</span>
                      {t.status === 'pending' && <span className="animate-pulse text-gray-500">ελέγχεται…</span>}
                      {t.status === 'rejected' && <span className="text-orange-400">✗ απορρίφθηκε</span>}
                      {t.status === 'running' && <span className="animate-pulse text-gray-500">εκτελείται…</span>}
                      {t.status === 'error' && <span className="text-red-400">⚠ σφάλμα</span>}
                      {t.status === 'ok' && <span className="text-green-400">✓ επιτυχία</span>}
                    </div>
                    <pre className="overflow-x-auto whitespace-pre-wrap text-[10px] text-gray-300">{t.code}</pre>
                    {t.reviewFeedback && <p className="mt-1 text-[10px] text-orange-400">{t.reviewFeedback}</p>}
                    {t.errorMessage && <p className="mt-1 text-[10px] text-red-400">{t.errorMessage}</p>}
                  </div>
                ))}
              </div>
              {step.result?.imageBase64 && (
                <img
                  src={`data:image/png;base64,${step.result.imageBase64}`}
                  alt="Action Agent chart"
                  className="mt-2 rounded border border-panel-border"
                />
              )}
            </div>
          ),
        )}

        {finalSummary && (
          <div className="animate-fade-in-up rounded-lg border border-gold/40 bg-gold/5 p-3 text-xs">
            <p className="mb-1 font-medium text-gold">Τελική απάντηση</p>
            <div className="text-gray-200">{renderRichText(finalSummary)}</div>
          </div>
        )}
        {finalError && (
          <p className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-xs text-red-400">{finalError}</p>
        )}
      </div>

      <PdfPageModal citation={viewingCitation} onClose={() => setViewingCitation(null)} />
    </div>
  )
}

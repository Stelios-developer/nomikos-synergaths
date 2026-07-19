import { useState } from 'react'
import { runActionAgent } from '../api/client'
import { renderRichText } from '../utils/richText'
import AgentKeyUnlock from './AgentKeyUnlock'

interface TraceStep {
  attempt: number
  code: string
  status: 'pending' | 'rejected' | 'running' | 'error' | 'ok'
  reviewFeedback?: string
  errorMessage?: string
}

const SAMPLE_GOALS = [
  'Compute compound interest on €10,000 at 5% for 10 years and plot the growth curve.',
  'Simulate rolling a die 10,000 times and plot the frequency distribution.',
  'Generate a 5-year straight-line depreciation schedule for a €50,000 asset and print it as a table.',
]

interface Props {
  agentEnabled: boolean
  onUnlocked: () => void
}

// Deliberately unrelated to the document RAG pipeline (no chunks, no
// citations, no ChromaDB): a multi-agent, tool-calling, self-correcting
// loop. A Planner breaks the goal into visible steps, a Coder decides via
// native tool-calling whether to run code or finish, a Reviewer vets every
// snippet before it ever reaches the sandbox (and can reject it without
// spending an execution), and the sandbox itself (Docker if available,
// subprocess fallback otherwise) reports real runtime errors back into
// the loop for self-correction.
//
// Code execution is a hard, all-or-nothing gate in this public deployment
// (backend/routers/agent_action.py::require_agent_api_key, fail-closed) —
// unlike the Supervisor, which degrades gracefully to documents-only, this
// tab has nothing else to fall back to, so it renders a fully locked state
// (with an unlock control) instead of the interactive UI when agentEnabled
// is false. `agentEnabled` starts from GET /config (App.tsx) and flips to
// true immediately once AgentKeyUnlock confirms a working key — no reload
// needed.
export default function ActionAgent({ agentEnabled, onUnlocked }: Props) {
  const [goal, setGoal] = useState('')
  const [plan, setPlan] = useState<string[]>([])
  const [trace, setTrace] = useState<TraceStep[]>([])
  const [running, setRunning] = useState(false)
  const [finalSummary, setFinalSummary] = useState<string | null>(null)
  const [finalStdout, setFinalStdout] = useState<string | null>(null)
  const [finalImage, setFinalImage] = useState<string | null>(null)
  const [finalError, setFinalError] = useState<string | null>(null)
  const [sandboxBackend, setSandboxBackend] = useState<string | null>(null)

  if (!agentEnabled) {
    return (
      <div className="mx-auto flex h-full max-w-3xl flex-col items-center justify-center gap-4 p-6 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gold/10 text-2xl">🔒</div>
        <div>
          <h2 className="mb-1 font-display text-base font-semibold text-gold">Action Agent</h2>
          <p className="mx-auto max-w-md text-xs text-gray-500">
            Η εκτέλεση κώδικα είναι κλειδωμένη σε αυτό το δημόσιο deployment — μόνο όποιος έχει το κλειδί του
            agent μπορεί να τη χρησιμοποιήσει. Οι υπόλοιπες λειτουργίες (Document Assistant, Supervisor,
            Advisory Panel, Debate, Research) παραμένουν πλήρως διαθέσιμες σε όλους.
          </p>
        </div>
        <AgentKeyUnlock onUnlocked={onUnlocked} />
      </div>
    )
  }

  const run = async (g: string) => {
    if (!g || running) return
    setRunning(true)
    setGoal(g)
    setPlan([])
    setTrace([])
    setFinalSummary(null)
    setFinalStdout(null)
    setFinalImage(null)
    setFinalError(null)
    setSandboxBackend(null)

    try {
      const result = await runActionAgent(g, {
        onPlan: (steps) => setPlan(steps),
        onCode: (attempt, code) => {
          setTrace((prev) => [
            ...prev.map((s) => (s.status === 'running' ? { ...s, status: 'ok' as const } : s)),
            { attempt, code, status: 'pending' },
          ])
        },
        onReview: (attempt, approved, feedback) => {
          setTrace((prev) =>
            prev.map((s) =>
              s.attempt === attempt
                ? { ...s, status: approved ? 'running' : 'rejected', reviewFeedback: feedback }
                : s,
            ),
          )
        },
        onError: (attempt, message) => {
          setTrace((prev) =>
            prev.map((s) => (s.attempt === attempt ? { ...s, status: 'error', errorMessage: message } : s)),
          )
        },
      })

      setSandboxBackend(result.sandboxBackend ?? null)

      if (result.success) {
        setTrace((prev) => prev.map((s) => (s.status === 'running' ? { ...s, status: 'ok' as const } : s)))
        setFinalSummary(result.summary ?? null)
        setFinalStdout(result.stdout || null)
        setFinalImage(result.imageBase64)
      } else {
        setFinalError(result.error ?? 'Ο agent δεν κατάφερε να ολοκληρώσει τον στόχο.')
      }
    } catch (e) {
      setFinalError(e instanceof Error ? e.message : 'Κάτι πήγε στραβά.')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col gap-4 p-6">
      <div>
        <h2 className="mb-1 font-display text-base font-semibold text-gold">Action Agent</h2>
        <p className="text-xs text-gray-500">
          Δώσε έναν στόχο. Ένας <span className="text-gray-300">Planner</span> τον σπάει σε βήματα, ένας{' '}
          <span className="text-gray-300">Coder</span> γράφει και τρέχει Python (μέσω πραγματικού tool-calling),
          ένας <span className="text-gray-300">Reviewer</span> ελέγχει κάθε κώδικα πριν εκτελεστεί — καμία σχέση
          με τα έγγραφα, καθαρή αυτόνομη δράση.
        </p>
      </div>

      {trace.length === 0 && !running && (
        <div className="flex flex-col items-center gap-4 py-10 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gold/10 text-2xl">⚡</div>
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
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && run(goal.trim())}
          placeholder="π.χ. Compute compound interest on €10,000 at 5% for 10 years…"
          className="flex-1 rounded-md border border-panel-border bg-panel px-3 py-2 text-sm text-gray-100
            placeholder:text-gray-500 transition-colors focus:border-gold focus:outline-none"
        />
        <button
          onClick={() => run(goal.trim())}
          disabled={running || !goal.trim()}
          className="rounded-md bg-gold px-4 py-2 text-sm font-medium text-black transition-all
            hover:brightness-110 active:scale-95 disabled:opacity-40 disabled:hover:brightness-100"
        >
          {running ? 'Εκτελείται…' : 'Run'}
        </button>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto">
        {plan.length > 0 && (
          <div className="animate-fade-in-up rounded-lg border border-panel-border bg-panel p-3 text-xs">
            <p className="mb-2 font-medium text-gold">Σχέδιο (Planner)</p>
            <ol className="list-inside list-decimal space-y-1 text-gray-300">
              {plan.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ol>
          </div>
        )}

        {trace.map((step) => (
          <div
            key={step.attempt}
            className="card-hover animate-fade-in-up rounded-lg border border-panel-border bg-panel p-3 text-xs"
          >
            <div className="mb-2 flex items-center gap-2">
              <span className="font-medium text-gold">Προσπάθεια {step.attempt}</span>
              {step.status === 'pending' && <span className="animate-pulse text-gray-500">ο reviewer ελέγχει…</span>}
              {step.status === 'rejected' && <span className="text-orange-400">✗ ο reviewer απέρριψε</span>}
              {step.status === 'running' && <span className="animate-pulse text-gray-500">εκτελείται…</span>}
              {step.status === 'error' && <span className="text-red-400">⚠ σφάλμα εκτέλεσης — διορθώνει…</span>}
              {step.status === 'ok' && <span className="text-green-400">✓ επιτυχία</span>}
            </div>
            <pre className="overflow-x-auto whitespace-pre-wrap rounded bg-black/30 p-2 text-[11px] text-gray-300">
              {step.code}
            </pre>
            {step.status === 'rejected' && step.reviewFeedback && (
              <p className="mt-2 text-[11px] text-orange-400">Λόγος: {step.reviewFeedback}</p>
            )}
            {step.status === 'error' && step.errorMessage && (
              <p className="mt-2 text-[11px] text-red-400">{step.errorMessage}</p>
            )}
          </div>
        ))}

        {finalSummary && (
          <div className="animate-fade-in-up rounded-lg border border-gold/40 bg-gold/5 p-3 text-xs">
            <div className="mb-2 flex items-center justify-between">
              <p className="font-medium text-gold">Αποτέλεσμα</p>
              {sandboxBackend && (
                <span className="rounded-full border border-panel-border px-2 py-0.5 text-[10px] text-gray-400">
                  {sandboxBackend === 'docker' ? '🐳 Docker sandbox' : '⚙️ Subprocess sandbox'}
                </span>
              )}
            </div>
            <div className="mb-2 text-gray-200">{renderRichText(finalSummary)}</div>
            {finalStdout && (
              <pre className="whitespace-pre-wrap text-[11px] text-gray-400">{finalStdout}</pre>
            )}
          </div>
        )}
        {finalImage && (
          <img
            src={`data:image/png;base64,${finalImage}`}
            alt="Agent output chart"
            className="animate-fade-in-up rounded border border-panel-border"
          />
        )}
        {finalError && (
          <p className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-xs text-red-400">
            {finalError}
          </p>
        )}
      </div>
    </div>
  )
}

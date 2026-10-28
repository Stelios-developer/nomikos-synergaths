import { useState } from 'react'
import { runAdvisoryPanel, type Citation, type AdvisorAnswer } from '../../api/client'
import { renderRichText } from '../../utils/richText'
import PdfPageModal from '../documents/PdfPageModal'

interface AdvisoryPanelProps {
  documentFilter: string | null
}

const SAMPLE_QUESTIONS = [
  'Πρέπει να διεκδικήσουμε πλήρως την έκπτωση Ε&Α 24% για όλες τις δαπάνες μας;',
  'Ποιοι είναι οι κίνδυνοι γύρω από το πλαφόν ταξιδιωτικών εξόδων των 12.000€;',
  'What approach should we take for equipment depreciation under this policy?',
]

const ADVISOR_STYLES: Record<string, string> = {
  aggressive: 'border-orange-500/40 bg-orange-500/5',
  conservative: 'border-sky-500/40 bg-sky-500/5',
  risk: 'border-yellow-500/40 bg-yellow-500/5',
}

const ADVISOR_AVATAR_BG: Record<string, string> = {
  aggressive: 'bg-orange-500/15 ring-orange-500/30',
  conservative: 'bg-sky-500/15 ring-sky-500/30',
  risk: 'bg-yellow-500/15 ring-yellow-500/30',
}

function SkeletonCard() {
  return (
    <div className="rounded-lg border border-panel-border bg-panel p-3 text-xs">
      <div className="skeleton-shimmer mb-3 h-3 w-2/3 rounded" />
      <div className="space-y-2">
        <div className="skeleton-shimmer h-2 w-full rounded" />
        <div className="skeleton-shimmer h-2 w-11/12 rounded" />
        <div className="skeleton-shimmer h-2 w-4/5 rounded" />
      </div>
    </div>
  )
}

// Three advisor personas (Aggressive Tax Optimizer, Conservative
// Compliance Officer, Risk Assessor) run CONCURRENTLY on the backend
// (services/advisory_panel.py, via ThreadPoolExecutor) over the exact
// same retrieved chunks, then a Moderator synthesizes their agreement
// and disagreement. Advisor cards below appear in COMPLETION order as
// they stream in — not a fixed sequence — which is the visual proof
// that this is a real parallel panel, not a disguised pipeline.
export default function AdvisoryPanel({ documentFilter }: AdvisoryPanelProps) {
  const [question, setQuestion] = useState('')
  const [running, setRunning] = useState(false)
  const [citations, setCitations] = useState<Citation[]>([])
  const [advisors, setAdvisors] = useState<AdvisorAnswer[]>([])
  const [moderatorSummary, setModeratorSummary] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [viewingCitation, setViewingCitation] = useState<Citation | null>(null)

  const run = async (q: string) => {
    if (!q || running) return
    setRunning(true)
    setQuestion(q)
    setCitations([])
    setAdvisors([])
    setModeratorSummary(null)
    setError(null)

    try {
      const result = await runAdvisoryPanel(q, documentFilter ?? undefined, {
        onCitations: setCitations,
        onAdvisor: (advisor) => setAdvisors((prev) => [...prev, advisor]),
      })
      setModeratorSummary(result.moderatorSummary)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Κάτι πήγε στραβά.')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="mx-auto flex h-full max-w-4xl flex-col gap-4 overflow-y-auto p-6">
      <div>
        <h2 className="mb-1 font-display text-base font-semibold text-gold">Advisory Panel</h2>
        <p className="text-xs text-gray-500">
          Τρεις σύμβουλοι με διαφορετική οπτική —{' '}
          <span className="text-orange-400">επιθετική βελτιστοποίηση</span>,{' '}
          <span className="text-sky-400">συντηρητική συμμόρφωση</span>, και{' '}
          <span className="text-yellow-400">ανάλυση κινδύνου</span> — απαντούν{' '}
          <span className="text-gray-300">παράλληλα</span> στα ίδια αποσπάσματα εγγράφων, και ένας Moderator
          συνθέτει την τελική σύσταση.
        </p>
      </div>

      {advisors.length === 0 && !running && (
        <div className="flex flex-col items-center gap-4 py-10 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gold/10 text-2xl">⚖️</div>
          <div className="flex flex-wrap justify-center gap-2">
            {SAMPLE_QUESTIONS.map((q) => (
              <button
                key={q}
                onClick={() => run(q)}
                className="rounded-full border border-panel-border bg-panel px-3 py-1.5 text-xs text-gray-300
                  transition-all hover:-translate-y-0.5 hover:border-gold/50 hover:text-gold hover:shadow-md hover:shadow-gold/5"
              >
                {q}
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
          placeholder="π.χ. Πρέπει να διεκδικήσουμε την πλήρη έκπτωση;"
          className="flex-1 rounded-md border border-panel-border bg-panel px-3 py-2 text-sm text-gray-100
            placeholder:text-gray-500 transition-colors focus:border-gold focus:outline-none"
        />
        <button
          onClick={() => run(question.trim())}
          disabled={running || !question.trim()}
          className="rounded-md bg-gold px-4 py-2 text-sm font-medium text-black transition-all
            hover:brightness-110 active:scale-95 disabled:opacity-40 disabled:hover:brightness-100"
        >
          {running ? 'Συσκέπτονται…' : 'Run'}
        </button>
      </div>

      {citations.length > 0 && (
        <div className="animate-fade-in-up rounded-lg border border-panel-border bg-panel p-3 text-xs">
          <p className="mb-2 font-medium text-gray-400">Αποσπάσματα εγγράφων (κοινά και για τους τρεις)</p>
          <div className="space-y-1">
            {citations.map((c, i) => (
              <p
                key={i}
                onClick={() => setViewingCitation(c)}
                className="cursor-pointer text-[10px] text-gray-500 transition-colors hover:text-gold"
              >
                [{i + 1}] {c.filename}, σελ. {c.page}
              </p>
            ))}
          </div>
        </div>
      )}

      {running && citations.length === 0 && (
        <p className="animate-pulse text-xs text-gray-500">Αναζήτηση στα έγγραφα…</p>
      )}

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {advisors.map((a) => (
          <div
            key={a.id}
            className={`card-hover animate-fade-in-up rounded-lg border p-3 text-xs ${ADVISOR_STYLES[a.id] ?? 'border-panel-border bg-panel'}`}
          >
            <div className="mb-2 flex items-center gap-2">
              <span
                className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm ring-1 ${ADVISOR_AVATAR_BG[a.id] ?? 'bg-black/30 ring-white/10'}`}
              >
                {a.emoji}
              </span>
              <p className="font-medium text-gray-200">{a.label}</p>
            </div>
            <div className="text-gray-300">
              {renderRichText(a.answer, { citations, onViewCitation: setViewingCitation })}
            </div>
          </div>
        ))}
        {running &&
          citations.length > 0 &&
          Array.from({ length: 3 - advisors.length }).map((_, i) => <SkeletonCard key={`pending-${i}`} />)}
      </div>

      {moderatorSummary && (
        <div className="animate-fade-in-up rounded-lg border border-gold/40 bg-gold/5 p-3 text-xs">
          <div className="mb-2 flex items-center gap-2">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gold/15 text-sm ring-1 ring-gold/30">
              ⚖️
            </span>
            <p className="font-medium text-gold">Σύνθεση Moderator</p>
          </div>
          <div className="text-gray-200">
            {renderRichText(moderatorSummary, { citations, onViewCitation: setViewingCitation })}
          </div>
        </div>
      )}

      {error && <p className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-xs text-red-400">{error}</p>}

      <PdfPageModal citation={viewingCitation} onClose={() => setViewingCitation(null)} />
    </div>
  )
}

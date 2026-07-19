import { useState } from 'react'
import { runDebateAgents, type Citation, type DebateArgument } from '../api/client'
import { renderRichText } from '../utils/richText'
import PdfPageModal from './PdfPageModal'

const SAMPLE_QUESTIONS = [
  'Πρέπει να διεκδικήσουμε την πλήρη έκπτωση Ε&Α 24% για δαπάνες οριακά εντός ορισμού;',
  'Είναι ασφαλές να αντιμετωπίσουμε όλα τα ταξιδιωτικά έξοδα κάτω από το πλαφόν των 12.000€ ως εκπεστέα;',
  'Should equipment bought near year-end be depreciated starting this year or next?',
]

const SIDE_STYLES: Record<string, string> = {
  for: 'border-emerald-500/40 bg-emerald-500/5',
  against: 'border-rose-500/40 bg-rose-500/5',
}

const SIDE_AVATAR_BG: Record<string, string> = {
  for: 'bg-emerald-500/15 ring-emerald-500/30',
  against: 'bg-rose-500/15 ring-rose-500/30',
}

function SkeletonCard() {
  return (
    <div className="rounded-lg border border-panel-border bg-panel p-3 text-xs">
      <div className="skeleton-shimmer mb-3 h-3 w-1/2 rounded" />
      <div className="space-y-2">
        <div className="skeleton-shimmer h-2 w-full rounded" />
        <div className="skeleton-shimmer h-2 w-11/12 rounded" />
        <div className="skeleton-shimmer h-2 w-3/4 rounded" />
      </div>
    </div>
  )
}

// Two personas argue OPPOSING, document-grounded positions across
// multiple rounds of DIRECT rebuttal (services/debate.py) — a different,
// more adversarial shape than the Advisory Panel's independent parallel
// opinions. Within each round both sides run CONCURRENTLY (neither has
// an information edge over the other at that round), but round 2
// explicitly quotes and responds to round 1's opponent argument. A Judge
// rules once the rounds are done.
export default function DebateAgents() {
  const [question, setQuestion] = useState('')
  const [running, setRunning] = useState(false)
  const [citations, setCitations] = useState<Citation[]>([])
  const [arguments_, setArguments] = useState<DebateArgument[]>([])
  const [verdict, setVerdict] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [viewingCitation, setViewingCitation] = useState<Citation | null>(null)

  const run = async (q: string) => {
    if (!q || running) return
    setRunning(true)
    setQuestion(q)
    setCitations([])
    setArguments([])
    setVerdict(null)
    setError(null)

    try {
      const result = await runDebateAgents(q, undefined, {
        onCitations: setCitations,
        onArgument: (arg) => setArguments((prev) => [...prev, arg]),
      })
      setVerdict(result.verdict)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Κάτι πήγε στραβά.')
    } finally {
      setRunning(false)
    }
  }

  const rounds = Array.from(new Set(arguments_.map((a) => a.round))).sort((a, b) => a - b)

  return (
    <div className="mx-auto flex h-full max-w-4xl flex-col gap-4 overflow-y-auto p-6">
      <div>
        <h2 className="mb-1 font-display text-base font-semibold text-gold">Debate Agents</h2>
        <p className="text-xs text-gray-500">
          Δύο agents υποστηρίζουν <span className="text-emerald-400">αντίθετες θέσεις</span> πάνω στην ίδια
          ερώτηση, σε διαδοχικούς γύρους όπου ο καθένας απαντά ΑΠΕΥΘΕΙΑΣ στο επιχείρημα του αντιπάλου —
          όχι ανεξάρτητες γνώμες όπως το Advisory Panel, αλλά μια πραγματική αντιπαράθεση. Ένας Judge
          κρίνει στο τέλος ποια πλευρά τεκμηριώνεται καλύτερα.
        </p>
      </div>

      {arguments_.length === 0 && !running && (
        <div className="flex flex-col items-center gap-4 py-10 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gold/10 text-2xl">🥊</div>
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
          {running ? 'Αντιπαρατίθενται…' : 'Run'}
        </button>
      </div>

      {citations.length > 0 && (
        <div className="animate-fade-in-up rounded-lg border border-panel-border bg-panel p-3 text-xs">
          <p className="mb-2 font-medium text-gray-400">Αποσπάσματα εγγράφων (κοινά και για τις δύο πλευρές)</p>
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

      <div className="space-y-3">
        {rounds.map((round) => {
          const roundArgs = arguments_.filter((a) => a.round === round)
          return (
            <div key={round} className="space-y-2">
              <p className="text-[10px] uppercase tracking-wide text-gray-500">Γύρος {round}</p>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                {roundArgs.map((a) => (
                  <div
                    key={a.side}
                    className={`card-hover animate-fade-in-up rounded-lg border p-3 text-xs ${SIDE_STYLES[a.side] ?? 'border-panel-border bg-panel'}`}
                  >
                    <div className="mb-2 flex items-center gap-2">
                      <span
                        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-sm ring-1 ${SIDE_AVATAR_BG[a.side] ?? 'bg-black/30 ring-white/10'}`}
                      >
                        {a.emoji}
                      </span>
                      <p className="font-medium text-gray-200">{a.label}</p>
                    </div>
                    <div className="text-gray-300">
                      {renderRichText(a.text, { citations, onViewCitation: setViewingCitation })}
                    </div>
                  </div>
                ))}
                {running &&
                  citations.length > 0 &&
                  roundArgs.length < 2 &&
                  round === rounds[rounds.length - 1] &&
                  Array.from({ length: 2 - roundArgs.length }).map((_, i) => <SkeletonCard key={`pending-${i}`} />)}
              </div>
            </div>
          )
        })}
      </div>

      {verdict && (
        <div className="animate-fade-in-up rounded-lg border border-gold/40 bg-gold/5 p-3 text-xs">
          <div className="mb-2 flex items-center gap-2">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gold/15 text-sm ring-1 ring-gold/30">
              ⚖️
            </span>
            <p className="font-medium text-gold">Κρίση του Judge</p>
          </div>
          <div className="text-gray-200">
            {renderRichText(verdict, { citations, onViewCitation: setViewingCitation })}
          </div>
        </div>
      )}

      {error && <p className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-xs text-red-400">{error}</p>}

      <PdfPageModal citation={viewingCitation} onClose={() => setViewingCitation(null)} />
    </div>
  )
}

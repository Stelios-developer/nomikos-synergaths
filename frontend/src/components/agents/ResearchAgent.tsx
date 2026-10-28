import { useState } from 'react'
import { runResearchAgent, type Citation, type SubRetrieval } from '../../api/client'
import { renderRichText } from '../../utils/richText'
import PdfPageModal from '../documents/PdfPageModal'

interface ResearchAgentProps {
  documentFilter: string | null
}

const SAMPLE_QUESTIONS = [
  'Ποιος είναι ο συντελεστής έκπτωσης Ε&Α, και πώς συγκρίνεται με τον συντελεστή απόσβεσης εξοπλισμού;',
  'Ποιο είναι το πλαφόν ταξιδιωτικών εξόδων, και ποια είναι η προθεσμία υποβολής δήλωσης;',
  'What is the R&D deduction rate, and what documentation does it require?',
]

function SkeletonLine() {
  return (
    <div className="rounded-lg border border-panel-border bg-panel p-3 text-xs">
      <div className="skeleton-shimmer h-2.5 w-2/3 rounded" />
    </div>
  )
}

// Compound questions get decomposed into standalone sub-questions FIRST
// (services/multihop.py), each gets its own retrieval + Corrective RAG
// grading — run CONCURRENTLY, same pattern as the Panel/Debate agents —
// then the merged, deduped evidence feeds one final synthesized answer.
// This is a RAG-quality upgrade, not a new persona: the single agentic
// pipeline (Document Assistant tab) issues exactly one retrieval per
// question, which dilutes signal for compound questions; this tab exists
// to make that improvement visible and testable on its own.
export default function ResearchAgent({ documentFilter }: ResearchAgentProps) {
  const [question, setQuestion] = useState('')
  const [running, setRunning] = useState(false)
  const [subquestions, setSubquestions] = useState<string[]>([])
  const [subretrievals, setSubretrievals] = useState<SubRetrieval[]>([])
  const [answer, setAnswer] = useState('')
  const [citations, setCitations] = useState<Citation[]>([])
  const [error, setError] = useState<string | null>(null)
  const [viewingCitation, setViewingCitation] = useState<Citation | null>(null)

  const run = async (q: string) => {
    if (!q || running) return
    setRunning(true)
    setQuestion(q)
    setSubquestions([])
    setSubretrievals([])
    setAnswer('')
    setCitations([])
    setError(null)

    try {
      const result = await runResearchAgent(q, documentFilter ?? undefined, [], {
        onSubquestions: setSubquestions,
        onSubretrieval: (sub) => setSubretrievals((prev) => [...prev, sub]),
        onToken: (content) => setAnswer((prev) => prev + content),
      })
      setCitations(result.citations)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Κάτι πήγε στραβά.')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col gap-4 overflow-y-auto p-6">
      <div>
        <h2 className="mb-1 font-display text-base font-semibold text-gold">Research Agent</h2>
        <p className="text-xs text-gray-500">
          Σπάει σύνθετες ερωτήσεις σε <span className="text-gray-300">αυτοτελή υπο-ερωτήματα</span>,
          κάνει ξεχωριστή αναζήτηση (με Corrective RAG grading) για το καθένα{' '}
          <span className="text-gray-300">παράλληλα</span>, και συνθέτει μία τελική απάντηση από όλα τα
          ευρήματα — αντί για μία θολή αναζήτηση πάνω σε ολόκληρη τη σύνθετη ερώτηση.
        </p>
      </div>

      {subquestions.length === 0 && !running && (
        <div className="flex flex-col items-center gap-4 py-10 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gold/10 text-2xl">🔬</div>
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
          placeholder="π.χ. Ποιος είναι ο συντελεστής Χ, και πώς συγκρίνεται με τον Υ;"
          className="flex-1 rounded-md border border-panel-border bg-panel px-3 py-2 text-sm text-gray-100
            placeholder:text-gray-500 transition-colors focus:border-gold focus:outline-none"
        />
        <button
          onClick={() => run(question.trim())}
          disabled={running || !question.trim()}
          className="rounded-md bg-gold px-4 py-2 text-sm font-medium text-black transition-all
            hover:brightness-110 active:scale-95 disabled:opacity-40 disabled:hover:brightness-100"
        >
          {running ? 'Ερευνά…' : 'Run'}
        </button>
      </div>

      {subquestions.length > 0 && (
        <div className="animate-fade-in-up rounded-lg border border-panel-border bg-panel p-3 text-xs">
          <p className="mb-2 font-medium text-gray-400">
            {subquestions.length > 1 ? 'Υπο-ερωτήματα (αναζήτηση παράλληλα)' : 'Ερώτηση'}
          </p>
          <ol className="list-inside list-decimal space-y-1 text-gray-300">
            {subquestions.map((sq, i) => (
              <li key={i}>{sq}</li>
            ))}
          </ol>
        </div>
      )}

      {subretrievals.length > 0 && (
        <div className="space-y-2">
          {subretrievals.map((sub, i) => (
            <div key={i} className="animate-fade-in-up rounded-lg border border-panel-border bg-panel p-3 text-xs">
              <p className="mb-1 font-medium text-gray-300">🔍 {sub.subQuestion}</p>
              {sub.citations.length > 0 ? (
                <div className="space-y-0.5">
                  {sub.citations.map((c, ci) => (
                    <p
                      key={ci}
                      onClick={() => setViewingCitation(c)}
                      className="cursor-pointer text-[10px] text-gray-500 transition-colors hover:text-gold"
                    >
                      [{ci + 1}] {c.filename}, σελ. {c.page}
                    </p>
                  ))}
                </div>
              ) : (
                <p className="text-[10px] text-gray-500">Δεν βρέθηκαν σχετικά αποσπάσματα.</p>
              )}
            </div>
          ))}
          {running &&
            subquestions.length > 0 &&
            subretrievals.length < subquestions.length &&
            Array.from({ length: subquestions.length - subretrievals.length }).map((_, i) => (
              <SkeletonLine key={`pending-${i}`} />
            ))}
        </div>
      )}

      {answer && (
        <div className="animate-fade-in-up rounded-lg border border-gold/40 bg-gold/5 p-3 text-xs">
          <p className="mb-1 font-medium text-gold">Συνθετική απάντηση</p>
          <div className="text-gray-200">
            {renderRichText(answer, { citations, onViewCitation: setViewingCitation })}
          </div>
          {citations.length > 0 && (
            <div className="mt-2 space-y-0.5 border-t border-panel-border pt-2">
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
          )}
        </div>
      )}

      {error && <p className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-xs text-red-400">{error}</p>}

      <PdfPageModal citation={viewingCitation} onClose={() => setViewingCitation(null)} />
    </div>
  )
}

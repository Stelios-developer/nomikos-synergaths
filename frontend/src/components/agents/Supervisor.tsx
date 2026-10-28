import { useState } from 'react'
import { runSupervisor, type Citation } from '../../api/client'
import { renderRichText } from '../../utils/richText'
import PdfPageModal from '../documents/PdfPageModal'

interface RagStep { query: string; text: string; citations: Citation[] }

interface SupervisorProps {
  documentFilter: string | null
}

const SAMPLE_QUESTIONS = [
  'Ποιες είναι οι προθεσμίες που αναφέρονται στα έγγραφα;',
  'Ποιοι είναι οι βασικοί κίνδυνοι και οι απαιτούμενες ενέργειες;',
]

export default function Supervisor({ documentFilter }: SupervisorProps) {
  const [question, setQuestion] = useState('')
  const [steps, setSteps] = useState<RagStep[]>([])
  const [running, setRunning] = useState(false)
  const [finalSummary, setFinalSummary] = useState<string | null>(null)
  const [finalError, setFinalError] = useState<string | null>(null)
  const [viewingCitation, setViewingCitation] = useState<Citation | null>(null)

  const run = async (request: string) => {
    if (!request || running) return
    setRunning(true); setQuestion(request); setSteps([]); setFinalSummary(null); setFinalError(null)
    try {
      const result = await runSupervisor(request, documentFilter ?? undefined, {
        onRoute: (_tool, input) => setSteps((previous) => [...previous, { query: input, text: '', citations: [] }]),
        onRagToken: (content) => setSteps((previous) => {
          const next = [...previous]; const last = next.length - 1
          if (next[last]) next[last] = { ...next[last], text: next[last].text + content }
          return next
        }),
        onRagDone: (citations) => setSteps((previous) => {
          const next = [...previous]; const last = next.length - 1
          if (next[last]) next[last] = { ...next[last], citations }
          return next
        }),
      })
      if (result.error) setFinalError(result.summary); else setFinalSummary(result.summary)
    } catch (error) {
      setFinalError(error instanceof Error ? error.message : 'Something went wrong.')
    } finally { setRunning(false) }
  }

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col gap-4 p-6">
      <div><h2 className="mb-1 font-display text-base font-semibold text-gold">Supervisor</h2><p className="text-xs text-gray-500">Ο orchestrator που δρομολογεί τις ερωτήσεις σου στην κοινή γνώση των εγγράφων.</p></div>
      {steps.length === 0 && !running && <div className="flex flex-col items-center gap-4 py-10 text-center"><div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gold/10 text-2xl">🧭</div><div className="flex flex-wrap justify-center gap-2">{SAMPLE_QUESTIONS.map((sample) => <button key={sample} onClick={() => run(sample)} className="rounded-full border border-panel-border bg-panel px-3 py-1.5 text-xs text-gray-300 transition-all hover:border-gold/50 hover:text-gold">{sample}</button>)}</div></div>}
      <div className="flex gap-2"><input value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={(event) => event.key === 'Enter' && run(question.trim())} placeholder="Ρώτησε κάτι για τα έγγραφά σου…" className="flex-1 rounded-md border border-panel-border bg-panel px-3 py-2 text-sm text-gray-100 placeholder:text-gray-500 focus:border-gold focus:outline-none" /><button onClick={() => run(question.trim())} disabled={running || !question.trim()} className="rounded-md bg-gold px-4 py-2 text-sm font-medium text-black disabled:opacity-40">{running ? 'Αναλύεται…' : 'Run'}</button></div>
      <div className="flex-1 space-y-3 overflow-y-auto">
        {steps.map((step, index) => <div key={index} className="animate-fade-in-up rounded-lg border border-panel-border bg-panel p-3 text-xs"><p className="mb-2 font-medium text-gold">🔍 Αναζήτηση: “{step.query}”</p><div className="text-gray-200">{renderRichText(step.text, { citations: step.citations, onViewCitation: setViewingCitation })}</div>{step.citations.length > 0 && <div className="mt-2 space-y-1 border-t border-panel-border pt-2">{step.citations.map((citation, citationIndex) => <button key={citationIndex} onClick={() => setViewingCitation(citation)} className="block text-left text-[10px] text-gray-500 hover:text-gold">[{citationIndex + 1}] {citation.filename}, σελ. {citation.page}</button>)}</div>}</div>)}
        {finalSummary && <div className="animate-fade-in-up rounded-lg border border-gold/40 bg-gold/5 p-3 text-xs"><p className="mb-1 font-medium text-gold">Τελική απάντηση</p><div className="text-gray-200">{renderRichText(finalSummary)}</div></div>}
        {finalError && <p className="rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-xs text-red-400">{finalError}</p>}
      </div>
      <PdfPageModal citation={viewingCitation} onClose={() => setViewingCitation(null)} />
    </div>
  )
}

import type { DocumentIntelligenceStage } from '../../api/client'

export type JourneyPhase = 'intake' | 'uploading' | 'opening' | 'analysing' | 'brief' | 'review_required' | 'error'

interface GuidedFlowProgressProps {
  phase: JourneyPhase
  activeStage: DocumentIntelligenceStage | null
  filename: string | null
}

const FLOW_STEPS = [
  { id: 'intake', label: 'Source intake', detail: 'Securely index your PDF' },
  { id: 'dna', label: 'Document DNA', detail: 'Classify structure and quality' },
  { id: 'facts', label: 'Facts & deadlines', detail: 'Extract what matters' },
  { id: 'risks', label: 'Risk map', detail: 'Prioritise exposure' },
  { id: 'brief', label: 'Decision brief', detail: 'Build the action pack' },
  { id: 'audit', label: 'Evidence gate', detail: 'Verify every claim' },
]

const STAGE_INDEX: Record<DocumentIntelligenceStage, number> = {
  started: 0,
  dna_complete: 1,
  facts_complete: 2,
  risks_complete: 3,
  brief_complete: 4,
  audit_complete: 5,
}

function activeIndex(phase: JourneyPhase, stage: DocumentIntelligenceStage | null) {
  if (phase === 'intake' || phase === 'uploading') return 0
  if (phase === 'brief' || phase === 'review_required') return FLOW_STEPS.length
  if (phase === 'error') return stage ? STAGE_INDEX[stage] + 1 : 0
  return stage ? STAGE_INDEX[stage] + 1 : 0
}

function statusCopy(phase: JourneyPhase, stage: DocumentIntelligenceStage | null, filename: string | null) {
  if (phase === 'intake') return 'Add one PDF to begin a complete evidence-first journey.'
  if (phase === 'uploading') return 'Securely uploading and indexing your PDF…'
  if (phase === 'opening') return `Opening the case for ${filename ?? 'your document'}…`
  if (phase === 'analysing') {
    const labels: Partial<Record<DocumentIntelligenceStage, string>> = {
      started: 'The source is indexed. Building the document map…',
      dna_complete: 'Document DNA is ready. Extracting facts and deadlines…',
      facts_complete: 'Facts are grounded. Prioritising the real risks…',
      risks_complete: 'Risk map is ready. Building your decision brief…',
      brief_complete: 'Action pack drafted. Verifying every claim against the source…',
      audit_complete: 'Evidence gate is finishing the final check…',
    }
    return labels[stage ?? 'started'] ?? 'Building a grounded intelligence case…'
  }
  if (phase === 'review_required') return 'Analysis is complete. A human review is required before action.'
  if (phase === 'error') return 'The analysis paused. The document remains available for a safe retry.'
  return 'Your decision brief is ready. Ask the evidence or inspect the action pack.'
}

export default function GuidedFlowProgress({ phase, activeStage, filename }: GuidedFlowProgressProps) {
  const current = activeIndex(phase, activeStage)
  const isProcessing = phase === 'uploading' || phase === 'opening' || phase === 'analysing'

  return (
    <section className={`guided-flow-canvas is-${phase} ${isProcessing ? 'is-processing' : ''}`} aria-busy={isProcessing} aria-label="Automated document analysis journey">
      <div className="guided-flow-head">
        <div>
          <span className="eyebrow">AUTOMATED INTELLIGENCE FLOW</span>
          <h2>{isProcessing ? 'Your case is building itself.' : phase === 'intake' ? 'One document. A clear next move.' : 'Your evidence is now a decision path.'}</h2>
        </div>
        <span className="guided-flow-live"><i aria-hidden="true" />{isProcessing ? 'LIVE FLOW' : 'EVIDENCE-FIRST'}</span>
      </div>

      <ol className="guided-flow-steps">
        {FLOW_STEPS.map((step, index) => {
          const isComplete = phase === 'brief' || phase === 'review_required' || index < current
          const isActive = !isComplete && index === current
          return (
            <li key={step.id} className={`guided-flow-step ${isComplete ? 'is-complete' : ''} ${isActive ? 'is-active' : ''}`} aria-current={isActive ? 'step' : undefined}>
              <span className="guided-flow-node" aria-hidden="true"><i>{isComplete ? '✓' : String(index + 1).padStart(2, '0')}</i></span>
              <span className="guided-flow-step-copy">
                <strong>{step.label}</strong>
                <small>{step.detail}</small>
              </span>
            </li>
          )
        })}
      </ol>

      <p className="guided-flow-status" role="status" aria-live="polite">
        <span aria-hidden="true" />
        {statusCopy(phase, activeStage, filename)}
      </p>
    </section>
  )
}

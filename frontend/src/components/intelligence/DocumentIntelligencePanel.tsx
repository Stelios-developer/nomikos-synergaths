import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import CaseOverview, { DeadlineCalendar } from './CaseOverview'
import Icon from '../ui/Icon'
import { BRAND_NAME } from '../../brand'
import { ApiError } from '../../api/http'
import {
  getDocumentIntelligence,
  getAnalysisJobResult,
  runDocumentIntelligenceStream,
  type CaseCitation,
  type Citation,
  type DocumentActionPack,
  type DocumentAudit,
  type DocumentIntelligenceCase,
  type DocumentIntelligenceStage,
} from '../../api/client'

import type { CaseWorkspaceView, IntelligenceWorkflowState } from './types'
export type { CaseWorkspaceView, IntelligenceWorkflowState } from './types'

interface DocumentIntelligencePanelProps {
  analysisJobId?: string | null
  filename: string | null
  onViewCitation: (citation: Citation) => void
  onNavigate?: (view: CaseWorkspaceView) => void
  view?: CaseWorkspaceView
  autoStart?: boolean
  onWorkflowChange?: (state: IntelligenceWorkflowState) => void
  onCaseReady?: (documentCase: DocumentIntelligenceCase) => void
}

type Severity = 'critical' | 'high' | 'medium' | 'low'

function AuditRing({
  audit,
  onNavigate,
}: {
  audit: DocumentAudit
  onNavigate?: (view: CaseWorkspaceView) => void
}) {
  const supported = audit.summary?.supported ?? 0
  const review = audit.summary?.unsupported ?? 0
  const unverified = audit.summary?.unverifiable ?? 0
  const total = supported + review + unverified
  const first = total ? (supported / total) * 100 : 0
  const second = total ? ((supported + review) / total) * 100 : 0
  return (
    <button
      className="audit-ring-button"
      onClick={() => onNavigate?.('evidence')}
      aria-label={
        total
          ? `Inspect evidence: ${supported} supported, ${review} review, ${unverified} unverified claims`
          : 'Inspect evidence: no claim counts available'
      }
    >
      <span
        className="audit-ring"
        style={{
          background: total
            ? `conic-gradient(#89ddb3 0% ${first}%, #efc27b ${first}% ${second}%, #9bb8ff ${second}% 100%)`
            : '#45454f',
        }}
      >
        <span>
          <strong>{total || '—'}</strong>
          <small>claims checked</small>
        </span>
      </span>
      <span className="audit-ring-legend">
        <span>
          <i />
          Supported
        </span>
        <span>
          <i />
          Review
        </span>
        <span>
          <i />
          Unverified
        </span>
      </span>
    </button>
  )
}

function normaliseSeverity(value: string | undefined): Severity {
  return value === 'critical' || value === 'high' || value === 'low'
    ? value
    : 'medium'
}

function pretty(value: string | undefined, fallback = '—') {
  return value ? value.replaceAll('_', ' ') : fallback
}

function statusLabel(status: string | undefined) {
  switch (status) {
    case 'ready_for_human_review':
      return 'Έτοιμο για ανθρώπινη έγκριση'
    case 'needs_human_review':
      return 'Review pending'
    case 'verified':
      return 'Επαληθευμένο'
    case 'in_progress':
      return 'Σε ανάλυση'
    default:
      return 'Δεν έχει αναλυθεί ακόμη'
  }
}

function statusTone(status: string | undefined) {
  if (status === 'ready_for_human_review' || status === 'verified')
    return 'is-verified'
  if (status === 'needs_human_review') return 'is-review'
  return 'is-neutral'
}

function SourceLinks({
  citationIds,
  citations,
  onViewCitation,
}: {
  citationIds?: string[]
  citations: Map<string, CaseCitation>
  onViewCitation: (citation: Citation) => void
}) {
  const sources = (citationIds ?? [])
    .map((id) => citations.get(id))
    .filter((source): source is CaseCitation => Boolean(source))

  if (sources.length === 0) return null

  return (
    <div className="case-source-links">
      {sources.map((source) => (
        <button
          key={source.id}
          type="button"
          onClick={() =>
            onViewCitation({
              filename: source.filename,
              page: source.page,
              text: source.excerpt,
            })
          }
          title={source.excerpt}
        >
          <span>{source.id}</span> p. {source.page}
        </button>
      ))}
    </div>
  )
}

function Section({
  title,
  children,
  count,
  className = '',
}: {
  title: string
  children: ReactNode
  count?: number
  className?: string
}) {
  return (
    <section className={`case-section ${className}`}>
      <header>
        <h3>{title}</h3>
        {typeof count === 'number' && <span>{count}</span>}
      </header>
      {children}
    </section>
  )
}

function EmptyCase({
  filename,
  onRetry,
  uncertain = false,
}: {
  filename: string
  onRetry: () => void
  uncertain?: boolean
}) {
  return (
    <div className="case-empty-state">
      <div className="case-empty-emblem" aria-hidden="true">
        <span />
      </div>
      <span className="eyebrow">ANALYSIS NEEDS ATTENTION</span>
      <h2>Your case could not finish automatically.</h2>
      <strong className="case-empty-filename">{filename}</strong>
      <p>
        The original PDF remains safely indexed. You can retry the
        evidence-first flow without leaving this page.
      </p>
      <button type="button" onClick={onRetry}>
        {uncertain ? 'Check saved progress' : 'Retry analysis'}
      </button>
    </div>
  )
}

function ProcessingCase({
  filename,
  stage,
}: {
  filename: string
  stage: DocumentIntelligenceStage | null
}) {
  const labels: Partial<Record<DocumentIntelligenceStage, string>> = {
    started: 'Preparing the evidence map',
    dna_complete: 'Extracting facts and deadlines',
    facts_complete: 'Prioritising the risk map',
    risks_complete: 'Drafting the decision brief',
    brief_complete: 'Verifying every claim against its source',
    audit_complete: 'Finalising the action pack',
  }

  return (
    <div className="case-processing-state" role="status" aria-live="polite">
      <div className="case-processing-orbit" aria-hidden="true">
        <span />
        <i />
        <b />
      </div>
      <span className="eyebrow">AUTOMATED ANALYSIS IN PROGRESS</span>
      <h2>{labels[stage ?? 'started'] ?? 'Building your intelligence case'}</h2>
      <strong className="case-empty-filename">{filename}</strong>
      <p>
        {BRAND_NAME} is running the real document workflow. Each stage lights up above
        only when the server has completed it.
      </p>
    </div>
  )
}

function ActionPack({
  pack,
  citations,
  onViewCitation,
  title = 'Decision brief & action pack',
  className = 'case-section--action-pack',
}: {
  pack: DocumentActionPack
  citations: Map<string, CaseCitation>
  onViewCitation: (citation: Citation) => void
  title?: string
  className?: string
}) {
  const isDecisions = className === 'case-section--decision-center'
  const actions = isDecisions ? [] : (pack.action_items ?? [])
  const decisions = isDecisions ? (pack.decisions_required ?? []) : []

  return (
    <Section
      title={title}
      count={isDecisions ? decisions.length : actions.length}
      className={className}
    >
      <div
        className={`case-verification-banner ${statusTone(pack.verification_status)}`}
      >
        <span>{statusLabel(pack.verification_status)}</span>
        {pack.human_review_required && (
          <small>Η τελική έγκριση παραμένει ανθρώπινη.</small>
        )}
      </div>

      {pack.executive_summary && (
        <p className="case-executive-summary">{pack.executive_summary}</p>
      )}
      {pack.next_step && (
        <p className="case-next-step">Next: {pack.next_step}</p>
      )}
      {decisions.length === 0 && isDecisions && (
        <p className="case-empty-copy">
          No explicit decisions were extracted. This does not mean that no
          decision is needed — inspect the source before acting.
        </p>
      )}
      {actions.length === 0 && !isDecisions && (
        <p className="case-empty-copy">
          No proposed actions were extracted. Review the obligations and
          evidence for any missing next steps.
        </p>
      )}

      {decisions.length > 0 && (
        <div className="case-subsection">
          <p className="case-subsection-title">Decisions needed</p>
          <div className="case-decision-list">
            {decisions.map((decision) => (
              <article key={decision.id}>
                <span>{decision.id}</span>
                <div>
                  <p>{decision.decision}</p>
                  <SourceLinks
                    citationIds={decision.citation_ids}
                    citations={citations}
                    onViewCitation={onViewCitation}
                  />
                </div>
              </article>
            ))}
          </div>
        </div>
      )}

      {actions.length > 0 && (
        <div className="case-subsection">
          <p className="case-subsection-title">Proposed actions</p>
          <div className="case-action-list">
            {actions.map((action) => (
              <article key={action.id}>
                <div className="case-action-head">
                  <p>{action.title}</p>
                  <span
                    className={`case-risk-badge ${normaliseSeverity(action.priority)}`}
                  >
                    {pretty(action.priority)}
                  </span>
                </div>
                <div className="case-action-meta">
                  <span>{action.suggested_owner || 'Unassigned owner'}</span>
                  {action.due_date && <span>Due {action.due_date}</span>}
                  {action.approval_required && <span>Approval required</span>}
                </div>
                <SourceLinks
                  citationIds={action.citation_ids}
                  citations={citations}
                  onViewCitation={onViewCitation}
                />
              </article>
            ))}
          </div>
        </div>
      )}

      {(pack.open_questions?.length ?? 0) > 0 && (
        <div className="case-subsection">
          <p className="case-subsection-title">Open questions</p>
          <ul className="case-question-list">
            {pack.open_questions?.map((question, index) => (
              <li key={`${question}-${index}`}>{question}</li>
            ))}
          </ul>
        </div>
      )}
    </Section>
  )
}

export default function DocumentIntelligencePanel({
  filename,
  analysisJobId,
  onViewCitation,
  onNavigate,
  view = 'overview',
  autoStart = false,
  onWorkflowChange,
  onCaseReady,
}: DocumentIntelligencePanelProps) {
  const [documentCase, setDocumentCase] =
    useState<DocumentIntelligenceCase | null>(null)
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [uncertainOutcome, setUncertainOutcome] = useState(false)
  const [hasLoaded, setHasLoaded] = useState(false)
  const [streamStage, setStreamStage] =
    useState<DocumentIntelligenceStage | null>(null)
  const operationId = useRef(0)
  const pendingRequest = useRef<AbortController | null>(null)
  const autoStartedFor = useRef<string | null>(null)

  useEffect(
    () => () => {
      operationId.current += 1
      const pending = pendingRequest
      pending.current?.abort()
    },
    [],
  )

  const loadCase = useCallback(async () => {
    const operation = ++operationId.current
    pendingRequest.current?.abort()
    const controller = new AbortController()
    pendingRequest.current = controller
    setRunning(false)
    if (!filename) {
      setDocumentCase(null)
      setError(null)
      setLoading(false)
      setHasLoaded(true)
      return
    }

    setLoading(true)
    setError(null)
    setUncertainOutcome(false)
    setHasLoaded(false)
    setDocumentCase(null)
    setStreamStage(null)
    try {
      const result = await (analysisJobId ? getAnalysisJobResult(analysisJobId, controller.signal) : getDocumentIntelligence(filename, controller.signal))
      if (operation === operationId.current) setDocumentCase(result)
    } catch (requestError) {
      if (operation === operationId.current) {
        setDocumentCase(null)
        setError(
          requestError instanceof Error
            ? requestError.message
            : 'Δεν ήταν δυνατή η φόρτωση του intelligence case.',
        )
      }
    } finally {
      if (operation === operationId.current) {
        setLoading(false)
        setHasLoaded(true)
      }
    }
  }, [filename, analysisJobId])

  useEffect(() => {
    autoStartedFor.current = null
    void loadCase()
  }, [filename, loadCase])

  const runCase = useCallback(async () => {
    if (!filename || running) return
    const operation = ++operationId.current
    pendingRequest.current?.abort()
    const controller = new AbortController()
    pendingRequest.current = controller
    setRunning(true)
    setError(null)
    setStreamStage(null)
    try {
      const result = await runDocumentIntelligenceStream(filename, (event) => {
        if (operation !== operationId.current || event.type !== 'stage') return
        setStreamStage(event.stage)
      }, controller.signal)
      if (operation === operationId.current) {
        setDocumentCase(result)
        onCaseReady?.(result)
      }
    } catch (requestError) {
      if (operation === operationId.current) {
        setUncertainOutcome(requestError instanceof ApiError && requestError.uncertain)
        setError(
          requestError instanceof Error
            ? requestError.message
            : 'Δεν ήταν δυνατή η ανάλυση του εγγράφου.',
        )
      }
    } finally {
      if (operation === operationId.current) setRunning(false)
    }
  }, [filename, onCaseReady, running])

  useEffect(() => {
    if (
      !autoStart ||
      !filename ||
      !hasLoaded ||
      documentCase ||
      running ||
      error ||
      autoStartedFor.current === filename
    )
      return
    autoStartedFor.current = filename
    void runCase()
  }, [autoStart, documentCase, error, filename, hasLoaded, runCase, running])

  useEffect(() => {
    if (!filename) return
    if (error) {
      onWorkflowChange?.({ phase: 'error', stage: streamStage })
      return
    }
    if (running) {
      onWorkflowChange?.({ phase: 'analysing', stage: streamStage })
      return
    }
    if (loading || !hasLoaded) {
      onWorkflowChange?.({ phase: 'opening', stage: streamStage })
      return
    }
    if (documentCase) {
      if (documentCase.stage !== 'finalized') {
        onWorkflowChange?.({ phase: 'analysing', stage: streamStage })
        return
      }
      const needsReview =
        documentCase.status === 'needs_human_review' ||
        documentCase.audit?.passed === false
      onWorkflowChange?.({
        phase: needsReview ? 'review_required' : 'brief',
        stage: streamStage ?? 'audit_complete',
      })
    }
  }, [
    documentCase,
    error,
    filename,
    hasLoaded,
    loading,
    onWorkflowChange,
    running,
    streamStage,
  ])

  const citationMap = useMemo(
    () =>
      new Map(
        (documentCase?.citations ?? []).map((citation) => [
          citation.id,
          citation,
        ]),
      ),
    [documentCase],
  )

  if (!filename) return null

  const profile = documentCase?.document_profile
  const quality = profile?.quality
  const facts = documentCase?.facts ?? []
  const obligations = documentCase?.obligations ?? []
  const deadlines = documentCase?.deadlines ?? []
  const risks = documentCase?.risks ?? []
  const audit = documentCase?.audit
  const actionPack = documentCase?.final_action_pack
  const timelineEntries = [
    ...deadlines.map((deadline) => ({
      id: deadline.id,
      date: deadline.date,
      title: deadline.event,
      owner: deadline.owner,
      status: deadline.status,
      detail: 'Source deadline',
      citationIds: deadline.citation_ids,
    })),
    ...obligations.map((obligation) => ({
      id: obligation.id,
      date: obligation.due_date,
      title: obligation.action,
      owner: obligation.owner,
      status: undefined,
      detail: obligation.trigger
        ? `Triggered by ${obligation.trigger}`
        : 'Required action',
      citationIds: obligation.citation_ids,
    })),
  ].sort((left, right) =>
    (left.date ?? '9999-12-31').localeCompare(right.date ?? '9999-12-31'),
  )

  return (
    <div className={`document-intelligence-panel case-view-${view}`}>
      <header className="intelligence-case-header">
        <p>
          {documentCase
            ? `${documentCase.document.page_count ?? '—'} pages · ${documentCase.document.chunk_count ?? 0} indexed fragments`
            : autoStart ? 'Building an evidence-backed case' : 'Saved analysis progress'}
        </p>
        <div className="intelligence-case-actions">
          <span
            className={`case-run-state ${running || loading ? 'is-running' : documentCase?.stage === 'finalized' ? 'is-complete' : ''}`}
          >
            <i aria-hidden="true" />
            {running || loading
              ? 'Analysis in progress'
              : documentCase?.stage === 'finalized'
                ? 'Analysis finished'
                : autoStart ? 'Preparing analysis' : 'Saved progress'}
          </span>
        </div>
      </header>

      {error && (
        <p className="intelligence-error" role="alert">
          {error}
        </p>
      )}
      {documentCase && documentCase.stage !== 'finalized' && !running && (
        <p role="status">Partial saved progress. This is not a completed analysis. Check Background activity in Manage files for its current status.</p>
      )}

      {(loading || running) && !documentCase ? (
        <ProcessingCase filename={filename} stage={streamStage} />
      ) : error && !documentCase ? (
        <EmptyCase filename={filename} uncertain={uncertainOutcome} onRetry={() => void (uncertainOutcome ? loadCase() : runCase())} />
      ) : !documentCase && !autoStart && hasLoaded ? (
        <section className="surface-card activity-empty" role="status">
          <h2>No saved result yet</h2>
          <p>The analysis may be queued or running. Open Background activity in Manage files to check its status.</p>
        </section>
      ) : !documentCase ? (
        <div
          className="intelligence-loading-grid"
          aria-label="Preparing document intelligence case"
        >
          {[1, 2, 3, 4].map((index) => (
            <div key={index} className="skeleton-shimmer" />
          ))}
        </div>
      ) : documentCase.stage !== 'finalized' ? (
        <section className="surface-card activity-empty">
          <h2>Saved progress</h2>
          <p>The saved stages are preserved. This analysis has not reached its final evidence check.</p>
          <button type="button" onClick={() => void loadCase()}>Refresh saved progress</button>
        </section>
      ) : (
        <div className="document-intelligence-scroll">
          {view === 'overview' && (
            <CaseOverview
              documentCase={documentCase}
              onNavigate={onNavigate}
              onViewCitation={onViewCitation}
            />
          )}
          {view === 'timeline' && (
            <DeadlineCalendar
              documentCase={documentCase}
              onNavigate={onNavigate}
              onViewCitation={onViewCitation}
            />
          )}

          <div className="intelligence-section-grid">
            <Section title="Document profile" className="case-section--profile">
              <div className="case-dna-grid">
                <div>
                  <span>Type</span>
                  <strong>{pretty(profile?.document_type)}</strong>
                </div>
                <div>
                  <span>Language</span>
                  <strong>{pretty(profile?.language)}</strong>
                </div>
                <div>
                  <span>Pages</span>
                  <strong>
                    {documentCase.document.page_count ??
                      quality?.page_count ??
                      '—'}
                  </strong>
                </div>
                <div>
                  <span>Extraction</span>
                  <strong>
                    {pretty(
                      quality?.extraction_quality ??
                        documentCase.document.method,
                    )}
                  </strong>
                </div>
              </div>
              {profile?.summary && (
                <p className="case-profile-summary">{profile.summary}</p>
              )}
              <details className="profile-details">
                <summary>Document details</summary>
                {(profile?.parties?.length ?? 0) > 0 && (
                  <p className="case-inline-detail">
                    <span>Parties</span>
                    {profile?.parties?.join(', ')}
                  </p>
                )}
                {(profile?.topics?.length ?? 0) > 0 && (
                  <p className="case-inline-detail">
                    <span>Topics</span>
                    {profile?.topics?.join(' · ')}
                  </p>
                )}
              </details>
              {(quality?.reasons?.length ?? 0) > 0 && (
                <ul className="case-quality-warnings">
                  {quality?.reasons?.map((reason, index) => (
                    <li key={`${reason}-${index}`}>{reason}</li>
                  ))}
                </ul>
              )}
              <SourceLinks
                citationIds={profile?.citation_ids}
                citations={citationMap}
                onViewCitation={onViewCitation}
              />
            </Section>

            {actionPack && (
              <ActionPack
                pack={actionPack}
                citations={citationMap}
                onViewCitation={onViewCitation}
              />
            )}
            {!actionPack && (
              <Section
                title="Proposed actions"
                className="case-section--action-pack"
              >
                <p className="case-empty-copy">
                  An action pack is not available for this analysis. Inspect the
                  source obligations and evidence before choosing a next step.
                </p>
              </Section>
            )}

            {actionPack && (
              <ActionPack
                title="Decision center"
                className="case-section--decision-center"
                pack={actionPack}
                citations={citationMap}
                onViewCitation={onViewCitation}
              />
            )}
            {!actionPack && (
              <Section
                title="Decision center"
                className="case-section--decision-center"
              >
                <p className="case-empty-copy">
                  No decision brief is available for this analysis. Review the
                  source facts and risks first.
                </p>
              </Section>
            )}

            <Section
              title="Facts"
              count={facts.length}
              className="case-section--facts"
            >
              {facts.length === 0 ? (
                <p className="case-empty-copy">
                  No source-grounded facts were extracted.
                </p>
              ) : (
                <div className="case-fact-list">
                  {facts.map((fact) => (
                    <article key={fact.id}>
                      <span>{fact.id}</span>
                      <div>
                        <p>{fact.statement}</p>
                        <small>
                          {pretty(fact.category)} · {pretty(fact.confidence)}{' '}
                          confidence
                        </small>
                        <SourceLinks
                          citationIds={fact.citation_ids}
                          citations={citationMap}
                          onViewCitation={onViewCitation}
                        />
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </Section>

            <Section
              title="Obligations & deadlines"
              count={obligations.length + deadlines.length}
              className="case-section--obligations"
            >
              {obligations.length === 0 && deadlines.length === 0 ? (
                <p className="case-empty-copy">
                  No explicit obligations or deadlines were found.
                </p>
              ) : (
                <>
                  {obligations.length > 0 && (
                    <div className="case-obligation-list">
                      {obligations.map((obligation) => (
                        <article key={obligation.id}>
                          <div className="case-action-head">
                            <p>{obligation.action}</p>
                            <span
                              className={`case-risk-badge ${normaliseSeverity(obligation.severity)}`}
                            >
                              {pretty(obligation.severity)}
                            </span>
                          </div>
                          <div className="case-action-meta">
                            <span>
                              {obligation.owner || 'Unassigned owner'}
                            </span>
                            {obligation.due_date && (
                              <span>Due {obligation.due_date}</span>
                            )}
                          </div>
                          {obligation.trigger && (
                            <p className="case-supporting-copy">
                              Trigger: {obligation.trigger}
                            </p>
                          )}
                          {obligation.consequence_if_missed && (
                            <p className="case-supporting-copy">
                              If missed: {obligation.consequence_if_missed}
                            </p>
                          )}
                          <SourceLinks
                            citationIds={obligation.citation_ids}
                            citations={citationMap}
                            onViewCitation={onViewCitation}
                          />
                        </article>
                      ))}
                    </div>
                  )}
                  {deadlines.length > 0 && (
                    <div className="case-deadline-list">
                      {deadlines.map((deadline) => (
                        <article key={deadline.id}>
                          <span>{deadline.date}</span>
                          <div>
                            <p>{deadline.event}</p>
                            {deadline.owner && <small>{deadline.owner}</small>}
                            <SourceLinks
                              citationIds={deadline.citation_ids}
                              citations={citationMap}
                              onViewCitation={onViewCitation}
                            />
                          </div>
                        </article>
                      ))}
                    </div>
                  )}
                </>
              )}
            </Section>

            <Section
              title="Timeline"
              count={timelineEntries.length}
              className="case-section--timeline"
            >
              {timelineEntries.length === 0 ? (
                <p className="case-empty-copy">
                  No dated actions were extracted from this document.
                </p>
              ) : (
                <ol className="case-timeline-list">
                  {timelineEntries.map((entry) => (
                    <li key={entry.id}>
                      <div className="case-timeline-date">
                        <strong>{entry.date || 'No date'}</strong>
                        <span>
                          {entry.date ? 'Source date' : 'To schedule'}
                        </span>
                        {entry.status && (
                          <span className="timeline-status">
                            {pretty(entry.status)}
                          </span>
                        )}
                      </div>
                      <div className="case-timeline-content">
                        <p>{entry.title}</p>
                        <small>
                          {entry.owner || 'Owner not assigned'} · {entry.detail}
                        </small>
                        <SourceLinks
                          citationIds={entry.citationIds}
                          citations={citationMap}
                          onViewCitation={onViewCitation}
                        />
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </Section>

            <Section
              title="Prioritised risks"
              count={risks.length}
              className="case-section--risks"
            >
              {risks.length === 0 ? (
                <p className="case-empty-copy">
                  No source-grounded risks were prioritised.
                </p>
              ) : (
                <div className="case-risk-list">
                  {risks.map((risk) => (
                    <article key={risk.id}>
                      <div className="case-action-head">
                        <p>{risk.title}</p>
                        <span
                          className={`case-risk-badge ${normaliseSeverity(risk.level)}`}
                        >
                          {pretty(risk.level)}
                        </span>
                      </div>
                      <p className="case-risk-rationale">{risk.rationale}</p>
                      {risk.mitigation && (
                        <p className="case-supporting-copy">
                          Mitigation: {risk.mitigation}
                        </p>
                      )}
                      <SourceLinks
                        citationIds={risk.citation_ids}
                        citations={citationMap}
                        onViewCitation={onViewCitation}
                      />
                    </article>
                  ))}
                </div>
              )}
            </Section>

            <Section title="Evidence quality" className="case-section--audit">
              {!audit ? (
                <p className="case-empty-copy">
                  The mandatory evidence audit has not completed yet.
                </p>
              ) : (
                <>
                  {view === 'evidence' && (
                    <div
                      className={`case-audit-callout ${audit.passed ? 'is-verified' : 'is-review'}`}
                    >
                      <strong>
                        {audit.passed
                          ? 'Evidence checks passed'
                          : 'Inspect the flagged claims'}
                      </strong>
                      {audit.reason && <p>{audit.reason}</p>}
                    </div>
                  )}
                  {view === 'overview' && (
                    <AuditRing audit={audit} onNavigate={onNavigate} />
                  )}
                  <div className="case-audit-stats">
                    <div>
                      <strong>{audit.summary?.supported ?? '—'}</strong>
                      <span>supported</span>
                    </div>
                    <div>
                      <strong>{audit.summary?.unsupported ?? '—'}</strong>
                      <span>review</span>
                    </div>
                    <div>
                      <strong>{audit.summary?.unverifiable ?? '—'}</strong>
                      <span>unverified</span>
                    </div>
                  </div>
                  {view === 'evidence' && (
                    <div className="case-audit-claims">
                      {(audit.sentences ?? []).map((sentence, index) => (
                        <article key={index}>
                          <span
                            className={`case-risk-badge ${sentence.verification_unavailable ? 'medium' : sentence.supported ? 'low' : 'high'}`}
                          >
                            <Icon
                              name={sentence.supported ? 'actions' : 'evidence'}
                            />
                            {sentence.verification_unavailable
                              ? 'Not verified'
                              : sentence.supported
                                ? 'Supported'
                                : 'Needs checking'}
                          </span>
                          <p>{sentence.text}</p>
                          {sentence.reason && <small>{sentence.reason}</small>}
                          <SourceLinks
                            citationIds={sentence.citation_ids}
                            citations={citationMap}
                            onViewCitation={onViewCitation}
                          />
                        </article>
                      ))}
                    </div>
                  )}
                </>
              )}
            </Section>

            {view === 'evidence' && (
              <Section
                title="Original sources"
                count={documentCase.citations.length}
                className="case-section--sources"
              >
                {documentCase.citations.length === 0 && (
                  <p className="case-empty-copy">
                    No original source links are available for this analysis.
                  </p>
                )}
                <div className="source-register">
                  {documentCase.citations.map((source) => (
                    <button
                      key={source.id}
                      onClick={() =>
                        onViewCitation({
                          filename: source.filename,
                          page: source.page,
                          text: source.excerpt,
                        })
                      }
                    >
                      <span className="source-register-title">
                        <span>
                          {source.id} · Page {source.page}
                        </span>
                        <Icon name="arrow" />
                      </span>
                      <p>{source.excerpt}</p>
                      <small>Open the original page</small>
                    </button>
                  ))}
                </div>
              </Section>
            )}
            {view === 'overview' && (
              <Section title="Your next moves" className="case-section--next">
                <div className="next-moves-list">
                  <button onClick={() => onNavigate?.('risks')}>
                    <Icon name="risks" />
                    <span>
                      Risk signal
                      <small>
                        {pretty(documentCase.overall_risk, 'Not rated')}
                      </small>
                    </span>
                    <Icon name="arrow" />
                  </button>
                  <button onClick={() => onNavigate?.('decisions')}>
                    <Icon name="decisions" />
                    <span>
                      Decisions to consider
                      <small>
                        {actionPack?.decisions_required?.length ?? 0} extracted
                      </small>
                    </span>
                    <Icon name="arrow" />
                  </button>
                  <button onClick={() => onNavigate?.('actions')}>
                    <Icon name="actions" />
                    <span>
                      Proposed actions
                      <small>
                        {actionPack?.action_items?.length ?? 0} extracted
                      </small>
                    </span>
                    <Icon name="arrow" />
                  </button>
                </div>
                {actionPack?.next_step && (
                  <p className="next-move-note">{actionPack.next_step}</p>
                )}
                <button
                  className="overview-review-link"
                  onClick={() => onNavigate?.('evidence')}
                >
                  Inspect the evidence <Icon name="arrow" />
                </button>
              </Section>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

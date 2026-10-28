import { ApiError, requestJson, responseError, streamEvents, withResponse } from './http'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

export interface UploadResult { filename: string; chunk_count: number; method: 'pymupdf' | 'ocr' }
export interface DocumentInfo { filename: string; chunk_count: number; method: string; upload_date: string }
export interface Citation { filename: string; page: number; text: string }
export interface AnalysisJob {
  job_id: string
  filename: string
  state: 'accepted' | 'dispatching' | 'uncertain' | 'cancel_requested' | 'cancelled' | 'failed' | 'complete'
  attempts: number
  deadline: string
  updated_at: string
  created_at: string
  reason: string
  can_cancel: boolean
  can_close: boolean
  result_available: boolean
}

export function listAnalysisJobs(signal?: AbortSignal): Promise<AnalysisJob[]> {
  return requestJson<AnalysisJob[]>(`${BASE_URL}/analysis/jobs`, {}, { signal })
}

export function resolveAnalysisJob(jobId: string, action: 'cancel' | 'close', signal?: AbortSignal): Promise<AnalysisJob> {
  return requestJson<AnalysisJob>(`${BASE_URL}/analysis/jobs/${encodeURIComponent(jobId)}/resolve`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action }),
  }, { signal })
}

export async function getAnalysisJobResult(jobId: string, signal?: AbortSignal): Promise<DocumentIntelligenceCase | null> {
  try { return await requestJson<DocumentIntelligenceCase>(`${BASE_URL}/analysis/jobs/${encodeURIComponent(jobId)}/result`, {}, { signal }) }
  catch (error) { if (error instanceof ApiError && error.status === 404) return null; throw error }
}
export interface EvalScores { faithfulness: number; relevance: number }
export interface HistoryTurn { role: 'user' | 'assistant'; content: string }
export interface SentenceVerdict { text: string; supported: boolean; reason: string; verification_unavailable?: boolean }

// A stored, evidence-first case file created by the document-intelligence
// workflow. Every finding refers to one or more IDs in `citations`, which
// lets the UI open the original PDF page rather than asking the user to trust
// an AI-generated claim.
export interface CaseCitation {
  id: string
  filename: string
  page: number
  chunk_index: number
  excerpt: string
}

export interface DocumentProfile {
  document_type?: string
  language?: string
  parties?: string[]
  dates?: string[]
  topics?: string[]
  confidentiality?: string
  summary?: string
  confidence?: 'high' | 'medium' | 'low' | string
  citation_ids?: string[]
  quality?: {
    extraction_quality?: 'good' | 'needs_review' | 'blocked' | string
    extraction_method?: string
    page_count?: number
    chunk_count?: number
    review_required?: boolean
    reasons?: string[]
  }
}

export interface DocumentFact {
  id: string
  statement: string
  category?: string
  confidence?: 'high' | 'medium' | 'low' | string
  citation_ids: string[]
}

export interface DocumentObligation {
  id: string
  owner?: string
  action: string
  trigger?: string
  due_date?: string | null
  consequence_if_missed?: string
  severity?: 'critical' | 'high' | 'medium' | 'low' | string
  confidence?: 'high' | 'medium' | 'low' | string
  citation_ids: string[]
}

export interface DocumentDeadline {
  id: string
  event: string
  date: string
  owner?: string
  status?: string
  citation_ids: string[]
}

export interface DocumentRisk {
  id: string
  title: string
  level?: 'critical' | 'high' | 'medium' | 'low' | string
  likelihood?: 'high' | 'medium' | 'low' | string
  impact?: string
  rationale: string
  mitigation?: string
  related_obligation_ids?: string[]
  citation_ids: string[]
  human_review_required?: boolean
}

export interface ActionPackItem {
  id: string
  title: string
  priority?: 'critical' | 'high' | 'medium' | 'low' | string
  suggested_owner?: string
  due_date?: string | null
  approval_required?: boolean
  source_obligation_id?: string
  citation_ids: string[]
}

export interface DecisionRequired {
  id: string
  decision: string
  citation_ids: string[]
}

export interface DocumentAudit {
  verification_available?: boolean
  passed?: boolean
  reason?: string
  summary?: {
    supported?: number
    unsupported?: number
    unverifiable?: number
  }
  sentences?: Array<{
    text: string
    category?: string
    citation_ids?: string[]
    supported: boolean
    reason?: string
    verification_unavailable?: boolean
  }>
}

export interface DocumentActionPack {
  verification_status?: 'verified' | 'needs_human_review' | string
  executive_summary?: string
  decisions_required?: DecisionRequired[]
  action_items?: ActionPackItem[]
  deadline_calendar?: DocumentDeadline[]
  risk_register?: DocumentRisk[]
  open_questions?: string[]
  human_review_required?: boolean
  next_step?: string
}

export interface DocumentIntelligenceCase {
  case_id: string
  status: string
  stage: string
  created_at?: string
  updated_at?: string
  document: {
    filename: string
    method?: string
    page_count?: number
    chunk_count?: number
    text_characters?: number
    source_file_available?: boolean
    ocr_detected?: boolean
  }
  citations: CaseCitation[]
  document_profile?: DocumentProfile
  facts?: DocumentFact[]
  obligations?: DocumentObligation[]
  deadlines?: DocumentDeadline[]
  overall_risk?: 'critical' | 'high' | 'medium' | 'low' | string
  risks?: DocumentRisk[]
  audit?: DocumentAudit
  final_action_pack?: DocumentActionPack
  warnings?: Array<{ stage?: string; message: string }>
}

export type DocumentIntelligenceStage =
  | 'started'
  | 'dna_complete'
  | 'facts_complete'
  | 'risks_complete'
  | 'brief_complete'
  | 'audit_complete'

export type DocumentIntelligenceStreamEvent =
  | { type: 'stage'; stage: DocumentIntelligenceStage }
  | { type: 'done'; case: DocumentIntelligenceCase }
  | { type: 'error'; message: string }

export async function uploadPdf(file: File): Promise<UploadResult> {
  const formData = new FormData()
  formData.append('file', file)
  return requestJson<UploadResult>(`${BASE_URL}/upload`, { method: 'POST', body: formData }, { timeoutMs: 180_000 })
}

export async function listDocuments(signal?: AbortSignal): Promise<DocumentInfo[]> {
  return requestJson<DocumentInfo[]>(`${BASE_URL}/documents`, {}, { signal })
}

export async function deleteDocument(filename: string): Promise<void> {
  await requestJson(`${BASE_URL}/documents/${encodeURIComponent(filename)}`, { method: 'DELETE' })
}

/** Returns the latest completed case for one browser-scoped document. */
export async function getDocumentIntelligence(filename: string, signal?: AbortSignal): Promise<DocumentIntelligenceCase | null> {
  try {
    return await requestJson<DocumentIntelligenceCase>(`${BASE_URL}/documents/${encodeURIComponent(filename)}/intelligence`, {}, { signal })
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

/** Runs the complete staged intelligence workflow and returns its final case. */
export async function runDocumentIntelligence(filename: string): Promise<DocumentIntelligenceCase> {
  return requestJson<DocumentIntelligenceCase>(`${BASE_URL}/documents/${encodeURIComponent(filename)}/intelligence/run`, {
    method: 'POST',
  }, { timeoutMs: 960_000 })
}

/** Streams each real server-side stage of the document intelligence workflow. */
export async function runDocumentIntelligenceStream(
  filename: string,
  onEvent: (event: DocumentIntelligenceStreamEvent) => void,
  signal?: AbortSignal,
): Promise<DocumentIntelligenceCase> {
  let completedCase: DocumentIntelligenceCase | null = null
  await streamEvents(`${BASE_URL}/documents/${encodeURIComponent(filename)}/intelligence/stream`, {
    method: 'POST',
  }, (event) => {
    const parsed = event as DocumentIntelligenceStreamEvent
    if (parsed.type === 'error') throw new Error(parsed.message)
    if (parsed.type === 'done') completedCase = parsed.case
    onEvent(parsed)
  }, { signal })

  if (!completedCase) throw new Error('The analysis ended without a completed case.')
  return completedCase
}

type QueryStreamEvent =
  | { type: 'token'; content: string }
  | { type: 'status'; message: string; query: string }
  | { type: 'done'; citations: Citation[]; eval: EvalScores | null }
  | { type: 'error'; message: string }

export async function askQuestionStream(question: string, documentFilter: string | undefined, history: HistoryTurn[], onToken: (content: string) => void, onStatus?: (message: string) => void, signal?: AbortSignal): Promise<{ citations: Citation[]; evalScores: EvalScores | null }> {
  let citations: Citation[] = []
  let evalScores: EvalScores | null = null
  await streamEvents(`${BASE_URL}/query`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question, document_filter: documentFilter, history: history.slice(-10) }) }, (event) => {
    const parsed = event as QueryStreamEvent
    if (parsed.type === 'token') onToken(parsed.content)
    else if (parsed.type === 'status') onStatus?.(parsed.message)
    else if (parsed.type === 'done') { citations = parsed.citations; evalScores = parsed.eval }
    else if (parsed.type === 'error') throw new Error(parsed.message)
  }, { signal })
  return { citations, evalScores }
}

export async function fetchEvaluation() {
  return requestJson(`${BASE_URL}/evaluation`)
}

export interface SupervisorResult { summary: string; error?: boolean }
type SupervisorStreamEvent =
  | { type: 'route'; tool: 'search_documents'; input: string }
  | { type: 'rag_token'; content: string }
  | { type: 'rag_done'; citations: Citation[] }
  | { type: 'done'; summary: string; error?: boolean }

export interface SupervisorCallbacks {
  onRoute: (tool: 'search_documents', input: string) => void
  onRagToken: (content: string) => void
  onRagDone: (citations: Citation[]) => void
}

export async function runSupervisor(question: string, documentFilter: string | undefined, callbacks: SupervisorCallbacks): Promise<SupervisorResult> {
  let result: SupervisorResult = { summary: '' }
  await streamEvents(`${BASE_URL}/supervisor/run`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question, document_filter: documentFilter }) }, (event) => {
    const parsed = event as SupervisorStreamEvent
    if (parsed.type === 'route') callbacks.onRoute(parsed.tool, parsed.input)
    else if (parsed.type === 'rag_token') callbacks.onRagToken(parsed.content)
    else if (parsed.type === 'rag_done') callbacks.onRagDone(parsed.citations)
    else if (parsed.type === 'done') result = { summary: parsed.summary, error: parsed.error }
  })
  return result
}

export async function getPageImageUrl(filename: string, page: number, snippet: string): Promise<string> {
  const params = new URLSearchParams({ page: String(page), snippet })
  const image = await withResponse(`${BASE_URL}/documents/${encodeURIComponent(filename)}/page?${params}`, {}, async (res) => {
    if (!res.ok) throw await responseError(res)
    return res.blob()
  })
  return URL.createObjectURL(image)
}

export interface AdvisorAnswer { id: string; label: string; emoji: string; answer: string }
export interface PanelResult { moderatorSummary: string }
type PanelStreamEvent =
  | { type: 'citations'; citations: Citation[] }
  | { type: 'advisor'; id: string; label: string; emoji: string; answer: string }
  | { type: 'done'; moderator_summary: string }
export interface PanelCallbacks { onCitations: (citations: Citation[]) => void; onAdvisor: (advisor: AdvisorAnswer) => void }

export async function runAdvisoryPanel(question: string, documentFilter: string | undefined, callbacks: PanelCallbacks): Promise<PanelResult> {
  let result: PanelResult = { moderatorSummary: '' }
  await streamEvents(`${BASE_URL}/panel/run`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question, document_filter: documentFilter }) }, (event) => {
    const parsed = event as PanelStreamEvent
    if (parsed.type === 'citations') callbacks.onCitations(parsed.citations)
    else if (parsed.type === 'advisor') callbacks.onAdvisor({ id: parsed.id, label: parsed.label, emoji: parsed.emoji, answer: parsed.answer })
    else if (parsed.type === 'done') result = { moderatorSummary: parsed.moderator_summary }
  })
  return result
}

export interface SubRetrieval { subQuestion: string; citations: Citation[] }
export interface ResearchResult { citations: Citation[] }
type ResearchStreamEvent =
  | { type: 'subquestions'; subquestions: string[] }
  | { type: 'subretrieval'; sub_question: string; citations: Citation[] }
  | { type: 'token'; content: string }
  | { type: 'done'; citations: Citation[] }
export interface ResearchCallbacks { onSubquestions: (subquestions: string[]) => void; onSubretrieval: (sub: SubRetrieval) => void; onToken: (content: string) => void }

export async function runResearchAgent(question: string, documentFilter: string | undefined, history: HistoryTurn[], callbacks: ResearchCallbacks): Promise<ResearchResult> {
  let result: ResearchResult = { citations: [] }
  await streamEvents(`${BASE_URL}/research/run`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question, document_filter: documentFilter, history: history.slice(-10) }) }, (event) => {
    const parsed = event as ResearchStreamEvent
    if (parsed.type === 'subquestions') callbacks.onSubquestions(parsed.subquestions)
    else if (parsed.type === 'subretrieval') callbacks.onSubretrieval({ subQuestion: parsed.sub_question, citations: parsed.citations })
    else if (parsed.type === 'token') callbacks.onToken(parsed.content)
    else if (parsed.type === 'done') result = { citations: parsed.citations }
  })
  return result
}

export async function auditAnswer(answer: string, citations: Citation[], signal?: AbortSignal): Promise<SentenceVerdict[]> {
  const body = await requestJson<{ sentences: SentenceVerdict[] }>(`${BASE_URL}/audit/run`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ answer, citations }) }, { signal, timeoutMs: 120_000 })
  return body.sentences
}

export interface ObservabilityRouteRow { path: string; requests: number; cost_usd: number; avg_duration_ms: number }
export interface ObservabilitySummary { total_requests: number; total_cost_usd: number; total_input_tokens: number; total_output_tokens: number; avg_duration_ms: number; by_route: ObservabilityRouteRow[] }
export interface ObservabilityRequestRow { request_id: string; method: string; path: string; status_code: number; duration_ms: number; input_tokens: number; output_tokens: number; cost_usd: number; llm_calls: number; created_at: string }

export async function fetchObservabilitySummary(): Promise<ObservabilitySummary> {
  return requestJson(`${BASE_URL}/observability/summary`)
}

export async function fetchRecentRequests(limit = 50): Promise<ObservabilityRequestRow[]> {
  const body = await requestJson<{ requests: ObservabilityRequestRow[] }>(`${BASE_URL}/observability/requests?limit=${limit}`)
  return body.requests
}

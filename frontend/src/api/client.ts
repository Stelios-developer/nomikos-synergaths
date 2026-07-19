import { getAgentKey, setAgentKey, getSessionId } from '../utils/session'

// Thin fetch wrapper for the backend. In dev, Vite proxies /api -> localhost:8010
// (see vite.config.ts). In prod, set VITE_API_BASE_URL to the deployed Render URL.
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

// Only needed if the backend has API_KEY set (see backend/services/security.py).
// Unset by default — local dev works with no key at all.
const API_KEY = import.meta.env.VITE_API_KEY as string | undefined

// The general API_KEY gate and the Action Agent's dedicated AGENT_API_KEY
// gate share the same X-API-Key header on the backend — they're just
// checked against two (possibly different) configured values. A runtime
// key a visitor enters via components/AgentKeyUnlock.tsx takes precedence
// over the build-time VITE_API_KEY baked in at deploy time.
function authHeaders(): Record<string, string> {
  const key = getAgentKey() || API_KEY
  return key ? { 'X-API-Key': key } : {}
}

// Sent on every document-related request (upload/list/delete/query/citation
// pages, and every multi-agent route that reads documents) so this browser's
// uploads stay invisible to every other visitor — see utils/session.ts and
// backend/services/session_scope.py. Deliberately NOT sent to /agent/run
// (no documents involved), /audit/run (grades an already-fetched answer,
// not a fresh document read), or /observability|/evaluation (aggregate
// system metrics, not per-visitor data).
function sessionHeaders(): Record<string, string> {
  return { 'X-Session-ID': getSessionId() }
}

export interface UploadResult {
  filename: string
  chunk_count: number
  method: 'pymupdf' | 'ocr'
}

export interface DocumentInfo {
  filename: string
  chunk_count: number
  method: string
  upload_date: string
}

export interface Citation {
  filename: string
  page: number
  text: string
}

export interface EvalScores {
  faithfulness: number
  relevance: number
}

export interface HistoryTurn {
  role: 'user' | 'assistant'
  content: string
}

// Used by utils/richText.tsx's renderAuditedRichText — defined here early
// since that shared renderer references it regardless of whether the
// Hallucination Auditor feature itself has landed yet.
export interface SentenceVerdict {
  text: string
  supported: boolean
  reason: string
}

type StreamEvent =
  | { type: 'token'; content: string }
  | { type: 'status'; message: string; query: string }
  | { type: 'done'; citations: Citation[]; eval: EvalScores | null }
  | { type: 'error'; message: string }

// --- Runtime config (backend/main.py: GET /config) ---
// Public, unauthenticated probe so the UI can render the Action Agent's
// code-execution affordance as locked or active up front, rather than the
// visitor discovering it's locked only after a failed run.
export interface AppConfig {
  agentEnabled: boolean
}

export async function fetchConfig(): Promise<AppConfig> {
  const res = await fetch(`${BASE_URL}/config`, { headers: authHeaders() })
  const body = await handle<{ agent_enabled: boolean }>(res)
  return { agentEnabled: body.agent_enabled }
}

// Verifies a candidate agent key against the backend BEFORE persisting it
// (see components/AgentKeyUnlock.tsx) — a wrong guess never "looks"
// unlocked only to fail on the first real run_code call.
export async function tryUnlockAgent(key: string): Promise<boolean> {
  const res = await fetch(`${BASE_URL}/config`, { headers: { 'X-API-Key': key } })
  const body = await handle<{ agent_enabled: boolean }>(res)
  if (body.agent_enabled) setAgentKey(key)
  return body.agent_enabled
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail ?? `Request failed: ${res.status}`)
  }
  return res.json()
}

export async function uploadPdf(file: File): Promise<UploadResult> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch(`${BASE_URL}/upload`, {
    method: 'POST',
    headers: { ...authHeaders(), ...sessionHeaders() },
    body: formData,
  })
  return handle<UploadResult>(res)
}

export async function listDocuments(): Promise<DocumentInfo[]> {
  const res = await fetch(`${BASE_URL}/documents`, { headers: { ...authHeaders(), ...sessionHeaders() } })
  return handle<DocumentInfo[]>(res)
}

export async function deleteDocument(filename: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/documents/${encodeURIComponent(filename)}`, {
    method: 'DELETE',
    headers: { ...authHeaders(), ...sessionHeaders() },
  })
  await handle(res)
}

// Streams the answer via SSE (backend uses POST + text/event-stream, so we
// parse the stream manually with fetch rather than the EventSource API,
// which only supports GET).
export async function askQuestionStream(
  question: string,
  documentFilter: string | undefined,
  history: HistoryTurn[],
  onToken: (content: string) => void,
  onStatus?: (message: string) => void,
): Promise<{ citations: Citation[]; evalScores: EvalScores | null }> {
  const res = await fetch(`${BASE_URL}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...sessionHeaders() },
    body: JSON.stringify({ question, document_filter: documentFilter, history }),
  })

  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail ?? `Request failed: ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let citations: Citation[] = []
  let evalScores: EvalScores | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''

    for (const raw of events) {
      const line = raw.trim()
      if (!line.startsWith('data:')) continue
      const parsed = JSON.parse(line.slice(5).trim()) as StreamEvent

      if (parsed.type === 'token') onToken(parsed.content)
      else if (parsed.type === 'status') onStatus?.(parsed.message)
      else if (parsed.type === 'done') {
        citations = parsed.citations
        evalScores = parsed.eval
      } else if (parsed.type === 'error') {
        throw new Error(parsed.message)
      }
    }
  }

  return { citations, evalScores }
}

export async function fetchEvaluation() {
  const res = await fetch(`${BASE_URL}/evaluation`, { headers: authHeaders() })
  return handle(res)
}

// --- Action Agent (backend/services/code_agent.py) ---
// Entirely independent of the document RAG pipeline above: no chunks, no
// citations, no ChromaDB. A multi-agent, tool-calling, self-correcting
// agent: a Planner breaks the goal into steps, a Coder decides (via
// native tool-calling) whether to run code or finish, a Reviewer vets
// every snippet before it reaches the sandbox, and the sandbox itself
// (Docker if available, subprocess fallback otherwise) reports real
// runtime errors back into the loop. Streamed over SSE the same way /query is.

export interface AgentResult {
  success: boolean
  stdout: string
  imageBase64: string | null
  attempts: number
  summary?: string | null
  error?: string | null
  sandboxBackend?: string | null
}

type AgentStreamEvent =
  | { type: 'plan'; steps: string[] }
  | { type: 'code'; attempt: number; code: string }
  | { type: 'review'; attempt: number; approved: boolean; feedback: string }
  | { type: 'error'; attempt: number; message: string }
  | {
      type: 'done'
      success: boolean
      stdout: string
      image_base64: string | null
      attempts: number
      summary?: string | null
      error?: string | null
      sandbox_backend?: string | null
    }

export interface AgentCallbacks {
  onPlan: (steps: string[]) => void
  onCode: (attempt: number, code: string) => void
  onReview: (attempt: number, approved: boolean, feedback: string) => void
  onError: (attempt: number, message: string) => void
}

export async function runActionAgent(goal: string, callbacks: AgentCallbacks): Promise<AgentResult> {
  const res = await fetch(`${BASE_URL}/agent/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ goal }),
  })

  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail ?? `Request failed: ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: AgentResult = { success: false, stdout: '', imageBase64: null, attempts: 0 }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''

    for (const raw of events) {
      const line = raw.trim()
      if (!line.startsWith('data:')) continue
      const parsed = JSON.parse(line.slice(5).trim()) as AgentStreamEvent

      if (parsed.type === 'plan') callbacks.onPlan(parsed.steps)
      else if (parsed.type === 'code') callbacks.onCode(parsed.attempt, parsed.code)
      else if (parsed.type === 'review') callbacks.onReview(parsed.attempt, parsed.approved, parsed.feedback)
      else if (parsed.type === 'error') callbacks.onError(parsed.attempt, parsed.message)
      else if (parsed.type === 'done') {
        result = {
          success: parsed.success,
          stdout: parsed.stdout,
          imageBase64: parsed.image_base64,
          attempts: parsed.attempts,
          summary: parsed.summary,
          error: parsed.error,
          sandboxBackend: parsed.sandbox_backend,
        }
      }
    }
  }

  return result
}

// --- Supervisor (backend/services/supervisor.py) ---
// Orchestrates the two subsystems above instead of duplicating either:
// decides via native tool-calling whether a request needs document
// retrieval (search_documents -> the RAG pipeline), code execution
// (run_code -> the Action Agent), or both chained together. The
// action_* events below are forwarded verbatim from the Action Agent's
// own trace, so the UI can render a nested sub-trace when it's invoked.

export interface SupervisorResult {
  summary: string
  error?: boolean
}

type SupervisorStreamEvent =
  | { type: 'route'; tool: 'search_documents' | 'run_code'; input: string }
  | { type: 'rag_token'; content: string }
  | { type: 'rag_done'; citations: Citation[] }
  | { type: 'action_plan'; steps: string[] }
  | { type: 'action_code'; attempt: number; code: string }
  | { type: 'action_review'; attempt: number; approved: boolean; feedback: string }
  | { type: 'action_error'; attempt: number; message: string }
  | {
      type: 'action_done'
      success: boolean
      stdout: string
      image_base64: string | null
      attempts: number
      summary?: string | null
      error?: string | null
      sandbox_backend?: string | null
    }
  | { type: 'done'; summary: string; error?: boolean }

export interface SupervisorCallbacks {
  onRoute: (tool: 'search_documents' | 'run_code', input: string) => void
  onRagToken: (content: string) => void
  onRagDone: (citations: Citation[]) => void
  onActionPlan: (steps: string[]) => void
  onActionCode: (attempt: number, code: string) => void
  onActionReview: (attempt: number, approved: boolean, feedback: string) => void
  onActionError: (attempt: number, message: string) => void
  onActionDone: (result: AgentResult) => void
}

export async function runSupervisor(
  question: string,
  documentFilter: string | undefined,
  callbacks: SupervisorCallbacks,
): Promise<SupervisorResult> {
  const res = await fetch(`${BASE_URL}/supervisor/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...sessionHeaders() },
    body: JSON.stringify({ question, document_filter: documentFilter }),
  })

  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail ?? `Request failed: ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: SupervisorResult = { summary: '' }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''

    for (const raw of events) {
      const line = raw.trim()
      if (!line.startsWith('data:')) continue
      const parsed = JSON.parse(line.slice(5).trim()) as SupervisorStreamEvent

      if (parsed.type === 'route') callbacks.onRoute(parsed.tool, parsed.input)
      else if (parsed.type === 'rag_token') callbacks.onRagToken(parsed.content)
      else if (parsed.type === 'rag_done') callbacks.onRagDone(parsed.citations)
      else if (parsed.type === 'action_plan') callbacks.onActionPlan(parsed.steps)
      else if (parsed.type === 'action_code') callbacks.onActionCode(parsed.attempt, parsed.code)
      else if (parsed.type === 'action_review') callbacks.onActionReview(parsed.attempt, parsed.approved, parsed.feedback)
      else if (parsed.type === 'action_error') callbacks.onActionError(parsed.attempt, parsed.message)
      else if (parsed.type === 'action_done') {
        callbacks.onActionDone({
          success: parsed.success,
          stdout: parsed.stdout,
          imageBase64: parsed.image_base64,
          attempts: parsed.attempts,
          summary: parsed.summary,
          error: parsed.error,
          sandboxBackend: parsed.sandbox_backend,
        })
      } else if (parsed.type === 'done') {
        result = { summary: parsed.summary, error: parsed.error }
      }
    }
  }

  return result
}

// --- Citation drill-down (backend/routers/documents.py: GET /documents/{filename}/page) ---
// Renders the original PDF page a citation came from, with the cited
// excerpt highlighted server-side, and returns a blob object URL for an
// <img> tag (see components/PdfPageModal.tsx). Callers must revoke the
// returned URL when done (PdfPageModal does this on unmount/citation change).
export async function getPageImageUrl(filename: string, page: number, snippet: string): Promise<string> {
  const params = new URLSearchParams({ page: String(page), snippet })
  const res = await fetch(`${BASE_URL}/documents/${encodeURIComponent(filename)}/page?${params}`, {
    headers: { ...authHeaders(), ...sessionHeaders() },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail ?? `Request failed: ${res.status}`)
  }
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}

// --- Advisory Panel (backend/services/advisory_panel.py) ---
// Three advisor personas (Aggressive Tax Optimizer, Conservative
// Compliance Officer, Risk Assessor) run CONCURRENTLY over one shared
// retrieval, then a Moderator synthesizes their agreement/disagreement.
// Advisor events arrive in COMPLETION order, not a fixed sequence.

export interface AdvisorAnswer {
  id: string
  label: string
  emoji: string
  answer: string
}

export interface PanelResult {
  moderatorSummary: string
}

type PanelStreamEvent =
  | { type: 'citations'; citations: Citation[] }
  | { type: 'advisor'; id: string; label: string; emoji: string; answer: string }
  | { type: 'done'; moderator_summary: string }

export interface PanelCallbacks {
  onCitations: (citations: Citation[]) => void
  onAdvisor: (advisor: AdvisorAnswer) => void
}

export async function runAdvisoryPanel(
  question: string,
  documentFilter: string | undefined,
  callbacks: PanelCallbacks,
): Promise<PanelResult> {
  const res = await fetch(`${BASE_URL}/panel/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...sessionHeaders() },
    body: JSON.stringify({ question, document_filter: documentFilter }),
  })

  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail ?? `Request failed: ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: PanelResult = { moderatorSummary: '' }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''

    for (const raw of events) {
      const line = raw.trim()
      if (!line.startsWith('data:')) continue
      const parsed = JSON.parse(line.slice(5).trim()) as PanelStreamEvent

      if (parsed.type === 'citations') callbacks.onCitations(parsed.citations)
      else if (parsed.type === 'advisor') {
        callbacks.onAdvisor({ id: parsed.id, label: parsed.label, emoji: parsed.emoji, answer: parsed.answer })
      } else if (parsed.type === 'done') {
        result = { moderatorSummary: parsed.moderator_summary }
      }
    }
  }

  return result
}

// --- Debate Agents (backend/services/debate.py) ---
// Two personas argue OPPOSING, document-grounded positions across
// multiple rounds of DIRECT rebuttal (unlike the Panel's independent
// parallel opinions), then a Judge rules on which side is better
// supported. Both sides within a round run CONCURRENTLY, so argument
// events arrive in completion order, not a fixed left/right sequence.

export interface DebateArgument {
  round: number
  side: 'for' | 'against'
  label: string
  emoji: string
  text: string
}

export interface DebateResult {
  verdict: string
}

type DebateStreamEvent =
  | { type: 'citations'; citations: Citation[] }
  | { type: 'argument'; side: 'for' | 'against'; round: number; label: string; emoji: string; text: string }
  | { type: 'verdict'; summary: string }

export interface DebateCallbacks {
  onCitations: (citations: Citation[]) => void
  onArgument: (arg: DebateArgument) => void
}

export async function runDebateAgents(
  question: string,
  documentFilter: string | undefined,
  callbacks: DebateCallbacks,
): Promise<DebateResult> {
  const res = await fetch(`${BASE_URL}/debate/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...sessionHeaders() },
    body: JSON.stringify({ question, document_filter: documentFilter }),
  })

  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail ?? `Request failed: ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: DebateResult = { verdict: '' }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''

    for (const raw of events) {
      const line = raw.trim()
      if (!line.startsWith('data:')) continue
      const parsed = JSON.parse(line.slice(5).trim()) as DebateStreamEvent

      if (parsed.type === 'citations') callbacks.onCitations(parsed.citations)
      else if (parsed.type === 'argument') {
        callbacks.onArgument({
          round: parsed.round,
          side: parsed.side,
          label: parsed.label,
          emoji: parsed.emoji,
          text: parsed.text,
        })
      } else if (parsed.type === 'verdict') {
        result = { verdict: parsed.summary }
      }
    }
  }

  return result
}

// --- Multi-hop Research Agent (backend/services/multihop.py) ---
// Decomposes a compound question into standalone sub-questions, retrieves
// + Corrective-RAG-grades each CONCURRENTLY, merges the results, and
// streams one final synthesized answer across all of them.

export interface SubRetrieval {
  subQuestion: string
  citations: Citation[]
}

export interface ResearchResult {
  citations: Citation[]
}

type ResearchStreamEvent =
  | { type: 'subquestions'; subquestions: string[] }
  | { type: 'subretrieval'; sub_question: string; citations: Citation[] }
  | { type: 'token'; content: string }
  | { type: 'done'; citations: Citation[] }

export interface ResearchCallbacks {
  onSubquestions: (subquestions: string[]) => void
  onSubretrieval: (sub: SubRetrieval) => void
  onToken: (content: string) => void
}

export async function runResearchAgent(
  question: string,
  documentFilter: string | undefined,
  history: HistoryTurn[],
  callbacks: ResearchCallbacks,
): Promise<ResearchResult> {
  const res = await fetch(`${BASE_URL}/research/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...sessionHeaders() },
    body: JSON.stringify({ question, document_filter: documentFilter, history }),
  })

  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail ?? `Request failed: ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: ResearchResult = { citations: [] }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''

    for (const raw of events) {
      const line = raw.trim()
      if (!line.startsWith('data:')) continue
      const parsed = JSON.parse(line.slice(5).trim()) as ResearchStreamEvent

      if (parsed.type === 'subquestions') callbacks.onSubquestions(parsed.subquestions)
      else if (parsed.type === 'subretrieval') {
        callbacks.onSubretrieval({ subQuestion: parsed.sub_question, citations: parsed.citations })
      } else if (parsed.type === 'token') callbacks.onToken(parsed.content)
      else if (parsed.type === 'done') result = { citations: parsed.citations }
    }
  }

  return result
}

// --- Hallucination Auditor (backend/services/auditor.py) ---
// On-demand, non-streaming: grades every sentence of an already-generated
// answer as supported/unsupported by its citations, in one LLM call.
// Not sent with sessionHeaders() — this grades an answer + citations the
// client already has, it doesn't read documents fresh (see the comment on
// sessionHeaders above).
export async function auditAnswer(answer: string, citations: Citation[]): Promise<SentenceVerdict[]> {
  const res = await fetch(`${BASE_URL}/audit/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ answer, citations }),
  })
  const body = await handle<{ sentences: SentenceVerdict[] }>(res)
  return body.sentences
}

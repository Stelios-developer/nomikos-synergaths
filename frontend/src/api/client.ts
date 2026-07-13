// Thin fetch wrapper for the backend. In dev, Vite proxies /api -> localhost:8000
// (see vite.config.ts). In prod, set VITE_API_BASE_URL to the deployed Render URL.
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

// Only needed if the backend has API_KEY set (see backend/services/security.py).
// Unset by default — local dev works with no key at all.
const API_KEY = import.meta.env.VITE_API_KEY as string | undefined

function authHeaders(): Record<string, string> {
  return API_KEY ? { 'X-API-Key': API_KEY } : {}
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

type StreamEvent =
  | { type: 'token'; content: string }
  | { type: 'done'; citations: Citation[]; eval: EvalScores | null }
  | { type: 'error'; message: string }

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
    headers: authHeaders(),
    body: formData,
  })
  return handle<UploadResult>(res)
}

export async function listDocuments(): Promise<DocumentInfo[]> {
  const res = await fetch(`${BASE_URL}/documents`, { headers: authHeaders() })
  return handle<DocumentInfo[]>(res)
}

export async function deleteDocument(filename: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/documents/${encodeURIComponent(filename)}`, {
    method: 'DELETE',
    headers: authHeaders(),
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
): Promise<{ citations: Citation[]; evalScores: EvalScores | null }> {
  const res = await fetch(`${BASE_URL}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
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

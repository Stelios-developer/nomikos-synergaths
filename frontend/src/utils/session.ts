// --- Per-visitor session isolation -----------------------------------------
// A random UUID generated once per browser and persisted in localStorage,
// sent as X-Session-ID on every document-related request (see
// api/client.ts::sessionHeaders). The backend stamps it onto every uploaded
// chunk and filters every read/list/delete by it (services/session_scope.py)
// so two anonymous visitors sharing the same public deployment never see or
// can delete each other's documents — no accounts, no API_KEY required.
const SESSION_ID_KEY = 'rag_session_id'

export function getSessionId(): string {
  let id = localStorage.getItem(SESSION_ID_KEY)
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem(SESSION_ID_KEY, id)
  }
  return id
}

// --- Action Agent code-execution key -------------------------------------
// A key a visitor can optionally paste in at runtime (see
// components/AgentKeyUnlock.tsx) to unlock code execution for themselves,
// without rebuilding or redeploying the frontend. Only ever persisted after
// the backend confirms it's valid (api/client.ts::tryUnlockAgent) — never
// stored blind. Backend counterpart: services/security.py::AGENT_API_KEY.
const AGENT_KEY = 'rag_agent_key'

export function getAgentKey(): string {
  return localStorage.getItem(AGENT_KEY) ?? ''
}

export function setAgentKey(key: string): void {
  if (key) localStorage.setItem(AGENT_KEY, key)
  else localStorage.removeItem(AGENT_KEY)
}

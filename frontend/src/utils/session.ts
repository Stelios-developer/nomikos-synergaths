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

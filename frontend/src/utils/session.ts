// A random browser-scoped ID keeps one visitor's documents isolated from
// another visitor's documents without requiring user accounts.
const SESSION_ID_KEY = 'rag_session_id'

export function getSessionId(): string {
  let id = localStorage.getItem(SESSION_ID_KEY)
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem(SESSION_ID_KEY, id)
  }
  return id
}

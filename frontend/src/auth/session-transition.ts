type SessionSnapshot = {
  data: unknown | null
  isPending: boolean
  isRefetching: boolean
}

type SessionStore = {
  get: () => SessionSnapshot
  listen: (listener: (snapshot: SessionSnapshot) => void) => () => void
}

// Better Auth refreshes its session atom after sign-out and notifies other tabs.
// Let that refresh settle before reloading, while bounding logout latency if it fails.
export function waitForSignedOutSession(store: SessionStore, timeoutMs = 2000): Promise<void> {
  return new Promise((resolve) => {
    let unsubscribe = () => {}
    let finished = false
    const finish = () => {
      if (finished) return
      finished = true
      clearTimeout(timer)
      unsubscribe()
      resolve()
    }
    const inspect = (snapshot: SessionSnapshot) => {
      if (snapshot.data === null && !snapshot.isPending && !snapshot.isRefetching) finish()
    }
    const timer = setTimeout(finish, timeoutMs)
    try {
      unsubscribe = store.listen(inspect)
      inspect(store.get())
    } catch {
      // A client-store failure must not prevent the already successful logout.
      finish()
    }
  })
}

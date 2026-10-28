/** Memory-only, actor-owned resource. A failed read is never an empty success. */
export interface ResourceSnapshot<T> {
  status: 'idle' | 'loading' | 'success' | 'error'
  data: T | null
  error: Error | null
  updatedAt: number | null
}

export class Resource<T> {
  private snapshot: ResourceSnapshot<T> = { status: 'idle', data: null, error: null, updatedAt: null }
  private revision = 0
  private pending: AbortController | null = null
  private listeners = new Set<() => void>()
  private loader: (signal: AbortSignal) => Promise<T>

  constructor(loader: (signal: AbortSignal) => Promise<T>) { this.loader = loader }
  getSnapshot = () => this.snapshot
  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }
  private publish(next: ResourceSnapshot<T>) {
    this.snapshot = next
    this.listeners.forEach((listener) => listener())
  }
  clear() {
    this.revision++
    this.pending?.abort()
    this.pending = null
    this.publish({ status: 'idle', data: null, error: null, updatedAt: null })
  }
  async load(): Promise<void> {
    const revision = ++this.revision
    this.pending?.abort()
    const controller = new AbortController()
    this.pending = controller
    this.publish({ ...this.snapshot, status: 'loading', error: null })
    try {
      const data = await this.loader(controller.signal)
      if (revision !== this.revision) return
      this.publish({ status: 'success', data, error: null, updatedAt: Date.now() })
    } catch (error) {
      if (revision !== this.revision) return
      const status = error && typeof error === 'object' && 'status' in error ? error.status : null
      const forget = status === 401 || status === 403 || status === 404
      this.publish({
        ...this.snapshot, status: 'error',
        data: forget ? null : this.snapshot.data,
        updatedAt: forget ? null : this.snapshot.updatedAt,
        error: error instanceof Error ? error : new Error('Could not load this resource.'),
      })
    } finally {
      if (revision === this.revision) this.pending = null
    }
  }
}

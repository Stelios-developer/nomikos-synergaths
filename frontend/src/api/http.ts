/** Cookie-authenticated transport with a total budget, including body reads.
 * Inspired by Padel's bounded transport; never automatically retries mutations.
 */
export interface RequestOptions {
  signal?: AbortSignal
  timeoutMs?: number
  fetchImpl?: typeof fetch
}

export class ApiError extends Error {
  status: number
  code: string
  requestId: string | null
  retryAfter: string | null
  uncertain: boolean

  constructor(message: string, options: {
    status?: number; code?: string; requestId?: string | null
    retryAfter?: string | null; uncertain?: boolean
  } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = options.status ?? 0
    this.code = options.code ?? 'REQUEST_FAILED'
    this.requestId = options.requestId ?? null
    this.retryAfter = options.retryAfter ?? null
    this.uncertain = options.uncertain ?? false
  }
}

export async function responseError(res: Response): Promise<ApiError> {
  const parsed: unknown = await res.json().catch(() => null)
  const body = parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : {}
  const detail = typeof body.detail === 'string' ? body.detail : null
  const fallback: Record<number, string> = {
    401: 'Your session expired. Please sign in again.',
    403: 'You do not have access to this resource.',
    429: 'Too many requests. Please wait before trying again.',
    500: 'The service could not complete this request.',
    502: 'A required service is unavailable.',
    503: 'A required service is temporarily unavailable.',
  }
  return new ApiError(detail ?? fallback[res.status] ?? `Request failed: ${res.status}`, {
    status: res.status,
    code: typeof body.code === 'string' ? body.code : `HTTP_${res.status}`,
    requestId: res.headers.get('X-Request-ID'),
    retryAfter: res.headers.get('Retry-After'),
  })
}

export async function withResponse<T>(
  url: string, init: RequestInit,
  consume: (response: Response, signal: AbortSignal) => Promise<T>,
  options: RequestOptions = {},
): Promise<T> {
  const controller = new AbortController()
  const signal = options.signal ?? init.signal
  const method = (init.method ?? 'GET').toUpperCase()
  const mutation = !['GET', 'HEAD', 'OPTIONS'].includes(method)
  const budget = options.timeoutMs ?? 30_000
  if (!Number.isFinite(budget) || budget <= 0) throw new RangeError('A positive request budget is required.')
  const headers = new Headers(init.headers)
  if (mutation) headers.set('X-CSRF-Protection', 'nexus-v1')
  let timer: ReturnType<typeof setTimeout> | undefined
  let onAbort: (() => void) | undefined
  let sent = false
  const deadline = new Promise<never>((_, reject) => {
    onAbort = () => {
      reject(new DOMException('Request cancelled', 'AbortError'))
      controller.abort()
    }
    if (signal?.aborted) onAbort()
    else signal?.addEventListener('abort', onAbort, { once: true })
    timer = setTimeout(() => {
      reject(new ApiError(mutation
        ? 'The response timed out. The operation may already have completed; refresh before retrying.'
        : 'The request timed out. Please try again.', {
        code: 'TIMEOUT', uncertain: mutation && sent,
      }))
      controller.abort()
    }, budget)
  })
  const work = (async () => {
    controller.signal.throwIfAborted()
    sent = true
    const res = await (options.fetchImpl ?? fetch)(url, {
      ...init, headers, credentials: 'include', signal: controller.signal,
    })
    return consume(res, controller.signal)
  })()
  try {
    return await Promise.race([work, deadline])
  } catch (error) {
    if (error instanceof TypeError) throw new ApiError(mutation
      ? 'Connection lost. The operation may already have completed; refresh before retrying.'
      : 'Could not contact the service. Check your connection.', {
      code: 'NETWORK', uncertain: mutation && sent,
    })
    throw error
  } finally {
    clearTimeout(timer)
    if (onAbort) signal?.removeEventListener('abort', onAbort)
    controller.abort()
  }
}

export function requestJson<T>(url: string, init: RequestInit = {}, options: RequestOptions = {}): Promise<T> {
  return withResponse(url, init, async (res) => {
    if (!res.ok) throw await responseError(res)
    if (res.status === 204) return undefined as T
    try { return await res.json() as T } catch (error) {
      if (!(error instanceof SyntaxError)) throw error
      throw new ApiError('The service returned an invalid response. Refresh before retrying.', {
        code: 'INVALID_RESPONSE', uncertain: !['GET', 'HEAD', 'OPTIONS'].includes((init.method ?? 'GET').toUpperCase()),
      })
    }
  }, options)
}

/** SSE framing supports CRLF, comments, multiline data and split UTF-8 bytes. */
export async function consumeEvents(res: Response, onEvent: (event: unknown) => void, signal: AbortSignal): Promise<void> {
  if (!res.ok) throw await responseError(res)
  if (!res.body) throw new ApiError('The stream has no response body.', { code: 'INVALID_STREAM' })
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = '', completed = false
  const cancel = () => { void reader.cancel().catch(() => {}) }
  signal.addEventListener('abort', cancel, { once: true })
  const dispatch = (frame: string) => {
    const data = frame.split('\n').filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).replace(/^ /, '')).join('\n')
    if (!data) return
    let event: unknown
    try { event = JSON.parse(data) } catch { throw new ApiError('The service returned invalid stream data.', { code: 'INVALID_STREAM' }) }
    if (!event || typeof event !== 'object' || !('type' in event)) throw new ApiError('The service returned an invalid event.', { code: 'INVALID_STREAM' })
    if (event.type === 'error') {
      const message = 'message' in event && typeof event.message === 'string' ? event.message : 'The analysis could not complete.'
      throw new ApiError(message, {
        code: 'code' in event && typeof event.code === 'string' ? event.code : 'ANALYSIS_FAILED',
        uncertain: 'uncertain' in event && event.uncertain === true,
      })
    }
    onEvent(event)
    if (event.type === 'done') completed = true
  }
  try {
    while (!completed) {
      signal.throwIfAborted()
      const { done, value } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      // Keep a trailing CR until its possible LF arrives in the next chunk.
      buffer = buffer.replace(/\r\n/g, '\n')
      if (buffer.length > 1_048_576) throw new ApiError('A stream frame exceeded the size limit.', { code: 'INVALID_STREAM' })
      let end: number
      while ((end = buffer.indexOf('\n\n')) >= 0) {
        dispatch(buffer.slice(0, end))
        buffer = buffer.slice(end + 2)
        if (completed) break
      }
      if (done) break
    }
    signal.throwIfAborted()
    if (!completed) throw new ApiError('The stream ended before completion. Refresh before retrying.', { code: 'INCOMPLETE_STREAM', uncertain: true })
  } finally {
    signal.removeEventListener('abort', cancel)
    cancel()
    reader.releaseLock()
  }
}

export function streamEvents(url: string, init: RequestInit, onEvent: (event: unknown) => void, options: RequestOptions = {}): Promise<void> {
  return withResponse(url, init, (res, signal) => consumeEvents(res, onEvent, signal), {
    timeoutMs: 960_000, ...options,
  })
}

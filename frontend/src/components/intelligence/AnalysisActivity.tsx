import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { listAnalysisJobs, resolveAnalysisJob, type AnalysisJob } from '../../api/client'
import { Resource } from '../../api/resource'
import { ApiError } from '../../api/http'
import Dialog from '../ui/Dialog'

const labels: Record<AnalysisJob['state'], string> = {
  accepted: 'Queued', dispatching: 'Analysing', uncertain: 'Check progress',
  cancel_requested: 'Cancellation requested', cancelled: 'Closed', failed: 'Could not start', complete: 'Ready',
}

function detail(job: AnalysisJob): string {
  if (job.state === 'accepted') return 'Waiting safely in the queue. You can leave this page.'
  if (job.state === 'dispatching') return 'Your analysis continues in the background.'
  if (job.state === 'uncertain') return 'Completion could not be confirmed. Check saved progress; the analysis will not be sent again.'
  if (job.state === 'cancel_requested') return 'Further stages are blocked. An in-flight request may finish; its late result will not be saved.'
  if (job.state === 'failed') return 'The analysis did not start. Check service availability before requesting it again.'
  return job.state === 'complete' ? job.result_available ? 'Saved results are available.' : 'This attempt completed. Its saved result is no longer available.' : 'This attempt is closed. It will not run again.'
}

export default function AnalysisActivity({ onOpen }: { onOpen: (filename: string, jobId: string) => void }) {
  const resource = useMemo(() => new Resource<AnalysisJob[]>(listAnalysisJobs), [])
  const snapshot = useSyncExternalStore(resource.subscribe, resource.getSnapshot)
  const [showAll, setShowAll] = useState(false)
  const [pending, setPending] = useState<{ job: AnalysisJob; action: 'cancel' | 'close' } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const mutation = useRef<AbortController | null>(null)
  const mounted = useRef(false)
  useEffect(() => {
    mounted.current = true
    void resource.load()
    const refresh = () => { if (document.visibilityState === 'visible' && resource.getSnapshot().status !== 'loading') void resource.load() }
    const timer = window.setInterval(refresh, 5000)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      mounted.current = false
      mutation.current?.abort()
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', refresh)
      resource.clear()
    }
  }, [resource])
  const jobs = snapshot.data ?? []
  const open = jobs.filter(job => !['complete', 'cancelled'].includes(job.state))
  const visible = showAll ? jobs : open
  const stale = snapshot.status === 'error' || snapshot.status === 'loading'
  const confirm = async () => {
    if (!pending || busy) return
    const controller = new AbortController()
    mutation.current = controller
    setBusy(true); setError(null)
    try {
      await resolveAnalysisJob(pending.job.job_id, pending.action, controller.signal)
      if (!mounted.current) return
      setPending(null)
      await resource.load()
    } catch (cause) {
      if (mounted.current) {
        if (cause instanceof ApiError && [401,403,404].includes(cause.status ?? 0)) {
          resource.clear();setPending(null)
        }
        setError(cause instanceof Error ? cause.message : 'The request could not be confirmed. Refresh saved activity before trying again.')
      }
    } finally {
      if (mounted.current) setBusy(false)
      if (mutation.current === controller) mutation.current = null
    }
  }
  return (
    <section className="analysis-activity surface-card" aria-labelledby="analysis-activity-title">
      <header className="surface-heading">
        <div><span className="eyebrow">YOUR ANALYSIS QUEUE</span><h3 id="analysis-activity-title">Background activity</h3>
          <p>Leave the page. Your analysis stays on track.</p></div>
        <div className="activity-controls">
          <button type="button" aria-pressed={showAll} onClick={() => setShowAll(value => !value)}>{showAll ? 'Show active' : 'Show history'}</button>
          <button type="button" disabled={snapshot.status === 'loading'} onClick={() => void resource.load()}>Refresh activity</button>
        </div>
      </header>
      {snapshot.error && <p role="alert">Activity could not be refreshed. Saved entries may be out of date; actions are paused.</p>}
      {error && !pending && <p role="alert">{error}</p>}
      {!snapshot.data && snapshot.status !== 'error' && <p role="status">Loading activity…</p>}
      {snapshot.data && visible.length === 0 && <div className="activity-empty">{showAll ? 'No analysis history yet.' : 'All caught up. No analysis needs attention.'}</div>}
      <div className="activity-list">
        {visible.map(job => (
          <article className="activity-row" key={job.job_id} aria-label={`Analysis of ${job.filename}`}>
            <div className="activity-copy"><span className={`activity-status activity-status-${job.state}`}>{labels[job.state]}</span>
              <h4>{job.filename}</h4><p>{detail(job)}</p>
              {['uncertain', 'cancel_requested'].includes(job.state) && !job.can_close && <small>Safe closure is available after {new Date(job.deadline).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}.</small>}
            </div>
            <div className="activity-actions">
              <button type="button" disabled={busy || stale || (job.state === 'complete' && !job.result_available)} onClick={() => onOpen(job.filename, job.job_id)}>View saved progress</button>
              {job.can_cancel && <button type="button" disabled={busy || stale} onClick={() => { setError(null); setPending({ job, action: 'cancel' }) }}>Cancel analysis</button>}
              {job.can_close && <button type="button" disabled={busy || stale} onClick={() => { setError(null); setPending({ job, action: 'close' }) }}>Close attempt</button>}
            </div>
          </article>
        ))}
      </div>
      {pending && <Dialog open titleId="activity-confirm-title" onClose={() => { if (!busy) setPending(null) }}>
        <h2 id="activity-confirm-title">{pending.action === 'cancel' ? 'Cancel this analysis?' : 'Close this attempt?'}</h2>
        <p>{pending.action === 'cancel' ? 'Queued work will stop. For work already running, further stages and late saves are blocked. An accepted AI request may still finish.' : 'This attempt will stay closed. A new analysis will use a fresh identity; this request does not start it.'}</p>
        <div className="activity-dialog-actions"><button type="button" disabled={busy} onClick={() => setPending(null)}>Keep reviewing</button>
          <button type="button" disabled={busy || stale} onClick={() => void confirm()}>{busy ? 'Saving…' : pending.action === 'cancel' ? 'Confirm cancellation' : 'Confirm closure'}</button></div>
        {error && <p role="alert">{error}</p>}
      </Dialog>}
    </section>
  )
}

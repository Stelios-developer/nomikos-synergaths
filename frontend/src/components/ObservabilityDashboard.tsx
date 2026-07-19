import { useEffect, useState } from 'react'
import {
  fetchObservabilitySummary,
  fetchRecentRequests,
  type ObservabilitySummary,
  type ObservabilityRequestRow,
} from '../api/client'
import CountUp from './CountUp'
import MiniBarChart from './MiniBarChart'

function StatTile({ icon, label, value }: { icon: string; label: string; value: React.ReactNode }) {
  return (
    <div className="card-hover rounded-lg border border-panel-border bg-black/20 p-3">
      <div className="mb-1 flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-gray-500">
        <span>{icon}</span>
        <span>{label}</span>
      </div>
      <p className="text-lg font-semibold text-gold">{value}</p>
    </div>
  )
}

function formatCost(usd: number): string {
  if (usd === 0) return '$0.00'
  if (usd < 0.01) return `$${usd.toFixed(6)}`
  return `$${usd.toFixed(4)}`
}

// Cost/latency/tracing view — distinct from EvalDashboard (answer
// quality). Reads services/observability.py's SQLite-backed request
// metrics: every request in the app gets a correlation ID, a structured
// JSON log line, an OTel span, and one row here. This is what makes "why
// did this specific query behave the way it did" answerable instead of
// invisible.
export default function ObservabilityDashboard() {
  const [summary, setSummary] = useState<ObservabilitySummary | null>(null)
  const [requests, setRequests] = useState<ObservabilityRequestRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([fetchObservabilitySummary(), fetchRecentRequests(20)])
      .then(([s, r]) => {
        setSummary(s)
        setRequests(r)
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load observability data.'))
  }, [])

  if (error) return <p className="text-xs text-red-400">{error}</p>
  if (!summary || !requests) return <p className="text-xs text-gray-500">Loading observability data…</p>

  if (summary.total_requests === 0) {
    return <p className="text-xs text-gray-500">No requests logged yet — use any tab to populate this.</p>
  }

  return (
    <div className="animate-fade-in-up space-y-4 rounded-lg border border-panel-border bg-panel p-4">
      <div className="grid grid-cols-2 gap-2">
        <StatTile icon="📨" label="Total requests" value={<CountUp value={summary.total_requests} />} />
        <StatTile
          icon="💰"
          label="Total cost"
          value={<CountUp value={summary.total_cost_usd} format={formatCost} />}
        />
        <StatTile
          icon="⏱️"
          label="Avg latency"
          value={<CountUp value={summary.avg_duration_ms} format={(n) => `${n.toFixed(0)} ms`} />}
        />
        <StatTile
          icon="🔤"
          label="Total tokens"
          value={
            <CountUp
              value={summary.total_input_tokens + summary.total_output_tokens}
              format={(n) => Math.round(n).toLocaleString()}
            />
          }
        />
      </div>

      <div>
        <h3 className="mb-2 text-xs uppercase tracking-wide text-gray-500">Cost by route</h3>
        <div className="rounded-lg border border-panel-border bg-black/20 p-3">
          <MiniBarChart
            data={summary.by_route.map((r) => ({ label: r.path, value: r.cost_usd }))}
            formatValue={formatCost}
          />
        </div>
        <ul className="mt-2 space-y-1">
          {summary.by_route.map((r) => (
            <li
              key={r.path}
              className="card-hover flex items-center justify-between rounded border border-panel-border px-2 py-1 text-xs"
            >
              <span className="text-gray-300">{r.path}</span>
              <span className="flex gap-3 text-[10px] text-gray-500">
                <span>{r.requests}×</span>
                <span className="text-gold">{formatCost(r.cost_usd)}</span>
                <span>{r.avg_duration_ms.toFixed(0)} ms avg</span>
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div>
        <h3 className="mb-2 text-xs uppercase tracking-wide text-gray-500">Recent requests</h3>
        <ul className="max-h-72 space-y-1 overflow-y-auto">
          {requests.map((r, i) => (
            <li
              key={r.request_id}
              style={{ animationDelay: `${Math.min(i, 10) * 30}ms` }}
              className="card-hover animate-fade-in-up rounded border border-panel-border p-2 text-xs"
            >
              <div className="mb-1 flex items-center justify-between">
                <span className="truncate text-gray-300">
                  {r.method} {r.path}
                </span>
                <span className={r.status_code < 400 ? 'text-emerald-400' : 'text-red-400'}>{r.status_code}</span>
              </div>
              <div className="flex flex-wrap gap-3 text-[10px] text-gray-500">
                <span title="Correlation ID — cross-reference against structured JSON logs">
                  id: {r.request_id}
                </span>
                <span>{r.duration_ms.toFixed(0)} ms</span>
                <span>{r.llm_calls} LLM call{r.llm_calls === 1 ? '' : 's'}</span>
                <span>{r.input_tokens + r.output_tokens} tokens</span>
                <span className="text-gold">{formatCost(r.cost_usd)}</span>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

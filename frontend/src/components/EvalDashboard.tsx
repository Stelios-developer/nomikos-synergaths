import { useEffect, useState } from 'react'
import { fetchEvaluation } from '../api/client'

interface EvalHistoryItem {
  question: string
  faithfulness: number
  relevance: number
  created_at: string
}

interface EvalData {
  avg_faithfulness: number
  avg_relevance: number
  total_queries: number
  history: EvalHistoryItem[]
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100)
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs text-gray-400">
        <span>{label}</span>
        <span className="text-gold">{pct}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-panel-border">
        <div className="h-full rounded-full bg-gold" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export default function EvalDashboard() {
  const [data, setData] = useState<EvalData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchEvaluation()
      .then((d) => setData(d as EvalData))
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load evaluation data.'))
  }, [])

  if (error) return <p className="text-xs text-red-400">{error}</p>
  if (!data) return <p className="text-xs text-gray-500">Loading evaluation data…</p>

  if (data.total_queries === 0) {
    return <p className="text-xs text-gray-500">No queries evaluated yet — ask a question to populate this.</p>
  }

  return (
    <div className="space-y-4 rounded-lg border border-panel-border bg-panel p-4">
      <div className="space-y-3">
        <ScoreBar label="Avg. faithfulness" value={data.avg_faithfulness} />
        <ScoreBar label="Avg. context relevance" value={data.avg_relevance} />
      </div>
      <p className="text-xs text-gray-500">{data.total_queries} total queries evaluated</p>

      <div>
        <h3 className="mb-2 text-xs uppercase tracking-wide text-gray-500">Recent queries</h3>
        <ul className="space-y-2">
          {data.history.map((item, i) => (
            <li key={i} className="rounded border border-panel-border p-2 text-xs">
              <p className="mb-1 truncate text-gray-300">{item.question}</p>
              <div className="flex gap-3 text-[10px] text-gray-500">
                <span>faithfulness: <span className="text-gold">{item.faithfulness.toFixed(2)}</span></span>
                <span>relevance: <span className="text-gold">{item.relevance.toFixed(2)}</span></span>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

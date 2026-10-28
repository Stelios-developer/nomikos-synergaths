interface BarDatum {
  label: string
  value: number
}

interface MiniBarChartProps {
  data: BarDatum[]
  formatValue?: (n: number) => string
}

// Lightweight horizontal bar "chart" built from plain divs (no charting
// library) — bar width is proportional to the largest value in the
// dataset, so relative cost/traffic across routes is visible at a glance
// instead of forcing the reader to compare raw numbers in a list.
export default function MiniBarChart({ data, formatValue = (n) => String(n) }: MiniBarChartProps) {
  const max = Math.max(...data.map((d) => d.value), 0.000001)

  return (
    <div className="space-y-2.5">
      {data.map((d, i) => (
        <div key={i} className="space-y-1">
          <div className="flex items-center justify-between text-[10px] text-gray-400">
            <span className="truncate">{d.label}</span>
            <span className="shrink-0 font-medium text-gold">{formatValue(d.value)}</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-panel-border">
            <div
              className="h-full rounded-full bg-gradient-to-r from-gold/50 to-gold transition-all duration-700 ease-out"
              style={{ width: `${Math.max(2, (d.value / max) * 100)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

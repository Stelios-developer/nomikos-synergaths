import { useEffect, useRef, useState } from 'react'

interface CountUpProps {
  value: number
  duration?: number
  format?: (n: number) => string
}

// Lightweight, dependency-free number-counter animation: animates from
// the previously rendered value (starting at 0 on first mount) to the new
// `value` via requestAnimationFrame whenever it changes. Used across the
// Ops/Evaluation dashboards so a stat appearing or updating reads as a
// live, data-driven surface rather than a static label popping in.
export default function CountUp({ value, duration = 700, format = (n) => String(Math.round(n)) }: CountUpProps) {
  const [display, setDisplay] = useState(0)
  const fromRef = useRef(0)
  const rafRef = useRef<number | undefined>(undefined)

  useEffect(() => {
    const from = fromRef.current
    const to = value
    if (from === to) return

    const start = performance.now()

    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - t, 3)
      setDisplay(from + (to - from) * eased)
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick)
      } else {
        fromRef.current = to
      }
    }

    rafRef.current = requestAnimationFrame(tick)
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [value, duration])

  return <>{format(display)}</>
}

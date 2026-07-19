import { useState } from 'react'
import { tryUnlockAgent } from '../api/client'

interface Props {
  onUnlocked: () => void
  compact?: boolean
}

// Lets a visitor unlock code execution (the Action Agent, and the
// Supervisor's run_code tool) for themselves by entering the
// operator-issued agent key — no rebuild/redeploy needed. The key is
// verified against GET /config (api/client.ts::tryUnlockAgent) before
// anything is persisted, so a wrong guess never "looks" unlocked only to
// fail on the first real run.
export default function AgentKeyUnlock({ onUnlocked, compact = false }: Props) {
  const [key, setKey] = useState('')
  const [checking, setChecking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    const trimmed = key.trim()
    if (!trimmed || checking) return
    setChecking(true)
    setError(null)
    try {
      const ok = await tryUnlockAgent(trimmed)
      if (ok) onUnlocked()
      else setError('Λάθος κλειδί.')
    } catch {
      setError('Ο έλεγχος του κλειδιού απέτυχε.')
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className={compact ? 'flex flex-wrap items-center gap-2' : 'flex flex-col items-center gap-2'}>
      <div className="flex gap-2">
        <input
          type="password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder="Agent access key"
          className="rounded-md border border-panel-border bg-panel px-3 py-1.5 text-xs text-gray-100
            placeholder:text-gray-500 transition-colors focus:border-gold focus:outline-none"
        />
        <button
          onClick={submit}
          disabled={checking || !key.trim()}
          className="whitespace-nowrap rounded-md bg-gold px-3 py-1.5 text-xs font-medium text-black transition-all
            hover:brightness-110 active:scale-95 disabled:opacity-40 disabled:hover:brightness-100"
        >
          {checking ? 'Έλεγχος…' : 'Unlock'}
        </button>
      </div>
      {error && <p className="text-[11px] text-red-400">{error}</p>}
    </div>
  )
}

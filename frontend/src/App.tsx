import { useEffect, useRef, useState } from 'react'
import UploadZone from './components/UploadZone'
import DocumentList, { type DocumentListHandle } from './components/DocumentList'
import ChatInterface from './components/ChatInterface'
import CitationsPanel from './components/CitationsPanel'
import EvalDashboard from './components/EvalDashboard'
import ActionAgent from './components/ActionAgent'
import Supervisor from './components/Supervisor'
import AdvisoryPanel from './components/AdvisoryPanel'
import DebateAgents from './components/DebateAgents'
import { fetchConfig, type Citation } from './api/client'

type RightTab = 'sources' | 'evaluation'
type AppMode = 'documents' | 'agent' | 'supervisor' | 'panel' | 'debate'

const NAV_ITEMS: { mode: AppMode; icon: string; label: string }[] = [
  { mode: 'documents', icon: '📄', label: 'Document Assistant' },
  { mode: 'agent', icon: '⚡', label: 'Action Agent' },
  { mode: 'supervisor', icon: '🧭', label: 'Supervisor' },
  { mode: 'panel', icon: '⚖️', label: 'Advisory Panel' },
  { mode: 'debate', icon: '🥊', label: 'Debate Agents' },
]

function App() {
  const [mode, setMode] = useState<AppMode>('documents')
  const [selectedFilename, setSelectedFilename] = useState<string | null>(null)
  const [citations, setCitations] = useState<Citation[]>([])
  const [hoveredCitation, setHoveredCitation] = useState<number | null>(null)
  const [rightTab, setRightTab] = useState<RightTab>('sources')
  const [agentEnabled, setAgentEnabled] = useState(false)
  const docListRef = useRef<DocumentListHandle>(null)

  // GET /config is public/unauthenticated — tells the Action Agent tab
  // whether code execution is locked BEFORE the visitor tries anything.
  useEffect(() => {
    fetchConfig()
      .then((c) => setAgentEnabled(c.agentEnabled))
      .catch(() => setAgentEnabled(false))
  }, [])

  return (
    <div className="flex h-screen flex-col bg-bg text-gray-100">
      <header className="flex items-center justify-between gap-6 border-b border-panel-border px-5 py-3">
        <h1 className="text-sm font-semibold tracking-wide text-gold">Document RAG Assistant</h1>

        <nav className="flex items-center gap-1 rounded-lg border border-panel-border bg-panel/60 p-1">
          {NAV_ITEMS.map(({ mode: m, icon, label }) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors
                ${mode === m ? 'bg-gold/15 text-gold' : 'text-gray-400 hover:text-gray-200'}`}
            >
              <span className="mr-1.5">{icon}</span>
              {label}
            </button>
          ))}
        </nav>
      </header>

      {mode === 'agent' ? (
        <div className="flex-1 overflow-hidden">
          <ActionAgent agentEnabled={agentEnabled} onUnlocked={() => setAgentEnabled(true)} />
        </div>
      ) : mode === 'supervisor' ? (
        <div className="flex-1 overflow-hidden">
          <Supervisor agentEnabled={agentEnabled} onUnlocked={() => setAgentEnabled(true)} />
        </div>
      ) : mode === 'panel' ? (
        <div className="flex-1 overflow-hidden">
          <AdvisoryPanel />
        </div>
      ) : mode === 'debate' ? (
        <div className="flex-1 overflow-hidden">
          <DebateAgents />
        </div>
      ) : (
        <div className="flex flex-1 overflow-hidden">
          {/* Sidebar */}
          <aside className="flex w-72 flex-col gap-4 border-r border-panel-border p-4">
            <UploadZone onUploaded={() => docListRef.current?.refresh()} />

            <div className="flex-1 overflow-y-auto">
              <h2 className="mb-2 text-xs uppercase tracking-wide text-gray-500">Documents</h2>
              <DocumentList ref={docListRef} selectedFilename={selectedFilename} onSelect={setSelectedFilename} />
            </div>

            {/* Session isolation is on by default with no login — this is
                the only place a visitor is told their uploads are private
                to their own browser (see utils/session.ts, services/session_scope.py). */}
            <p className="text-[10px] leading-relaxed text-gray-600">
              🔒 Documents you upload are only visible in this browser — no accounts, no shared storage with
              other visitors.
            </p>
          </aside>

          {/* Chat */}
          <main className="flex-1 p-4">
            <ChatInterface
              documentFilter={selectedFilename}
              onCitations={setCitations}
              onHoverCitation={setHoveredCitation}
            />
          </main>

          {/* Citations / Evaluation */}
          <aside className="w-80 border-l border-panel-border p-4">
            <div className="mb-3 flex gap-1 rounded-md bg-panel p-1 text-xs">
              <button
                onClick={() => setRightTab('sources')}
                className={`flex-1 rounded px-2 py-1 ${rightTab === 'sources' ? 'bg-gold/15 text-gold' : 'text-gray-400'}`}
              >
                Sources
              </button>
              <button
                onClick={() => setRightTab('evaluation')}
                className={`flex-1 rounded px-2 py-1 ${rightTab === 'evaluation' ? 'bg-gold/15 text-gold' : 'text-gray-400'}`}
              >
                Evaluation
              </button>
            </div>

            {rightTab === 'sources' ? (
              <CitationsPanel citations={citations} hoveredIndex={hoveredCitation} />
            ) : (
              <EvalDashboard />
            )}
          </aside>
        </div>
      )}
    </div>
  )
}

export default App

import { useRef, useState } from 'react'
import UploadZone from './components/UploadZone'
import DocumentList, { type DocumentListHandle } from './components/DocumentList'
import ChatInterface from './components/ChatInterface'
import CitationsPanel from './components/CitationsPanel'
import EvalDashboard from './components/EvalDashboard'
import type { Citation } from './api/client'

type RightTab = 'sources' | 'evaluation'

function App() {
  const [selectedFilename, setSelectedFilename] = useState<string | null>(null)
  const [citations, setCitations] = useState<Citation[]>([])
  const [hoveredCitation, setHoveredCitation] = useState<number | null>(null)
  const [rightTab, setRightTab] = useState<RightTab>('sources')
  const docListRef = useRef<DocumentListHandle>(null)

  return (
    <div className="flex h-screen bg-bg text-gray-100">
      {/* Sidebar */}
      <aside className="flex w-72 flex-col gap-4 border-r border-panel-border p-4">
        <h1 className="text-sm font-semibold tracking-wide text-gold">Document RAG Assistant</h1>

        <UploadZone onUploaded={() => docListRef.current?.refresh()} />

        <div className="flex-1 overflow-y-auto">
          <h2 className="mb-2 text-xs uppercase tracking-wide text-gray-500">Documents</h2>
          <DocumentList ref={docListRef} selectedFilename={selectedFilename} onSelect={setSelectedFilename} />
        </div>
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
  )
}

export default App

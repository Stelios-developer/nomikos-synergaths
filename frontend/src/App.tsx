import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import UploadZone from './components/documents/UploadZone'
import DocumentList, {
  type DocumentListHandle,
} from './components/documents/DocumentList'
import ChatInterface from './components/intelligence/ChatInterface'
import AnalysisActivity from './components/intelligence/AnalysisActivity'
import CitationsPanel from './components/documents/CitationsPanel'
import PdfPageModal from './components/documents/PdfPageModal'
import DocumentIntelligencePanel, {
  type CaseWorkspaceView,
  type IntelligenceWorkflowState,
} from './components/intelligence/DocumentIntelligencePanel'
import Icon, { DocumentMark, type IconName } from './components/ui/Icon'
import { BRAND_NAME } from './brand'
import Dialog from './components/ui/Dialog'
import {
  type Citation,
  type DocumentIntelligenceCase,
  type UploadResult,
} from './api/client'
import { authClient } from './auth/client'
import { waitForSignedOutSession } from './auth/session-transition'

type SectionId = CaseWorkspaceView | 'ask'
const SECTIONS: { id: SectionId; label: string; detail: string }[] = [
  {
    id: 'overview',
    label: 'Overview',
    detail: 'The big picture, without the noise.',
  },
  {
    id: 'facts',
    label: 'Facts & obligations',
    detail: 'What the document says. What it requires.',
  },
  {
    id: 'timeline',
    label: 'Timeline',
    detail: 'Every date, owner and deadline in one place.',
  },
  {
    id: 'risks',
    label: 'Risk radar',
    detail: 'Understand the exposure. Focus on what matters.',
  },
  {
    id: 'actions',
    label: 'Action plan',
    detail: 'Clear next steps, grounded in your source.',
  },
  {
    id: 'decisions',
    label: 'Decision center',
    detail: 'Consider the recommendation. Inspect the evidence.',
  },
  {
    id: 'evidence',
    label: 'Evidence',
    detail: 'Trace every finding back to the original page.',
  },
  {
    id: 'ask',
    label: 'Document assistant',
    detail: 'A focused conversation with your evidence.',
  },
]

export default function App() {
  const { data: authSession } = authClient.useSession()
  const [filename, setFilename] = useState<string | null>(null)
  const [section, setSection] = useState<SectionId>('overview')
  const [journey, setJourney] = useState<IntelligenceWorkflowState>({
    phase: 'opening',
    stage: null,
  })
  const [citations, setCitations] = useState<Citation[]>([])
  const [hoveredCitation, setHoveredCitation] = useState<number | null>(null)
  const [viewingCitation, setViewingCitation] = useState<Citation | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [librarySearch, setLibrarySearch] = useState('')
  const [readOnlyProgress, setReadOnlyProgress] = useState(false)
  const [savedJobId, setSavedJobId] = useState<string | null>(null)
  const [displayName, setDisplayName] = useState('')
  const [settingsStatus, setSettingsStatus] = useState<string | null>(null)
  const [settingsError, setSettingsError] = useState(false)
  const [saving, setSaving] = useState(false)
  const [signingOut, setSigningOut] = useState(false)
  const [accountError, setAccountError] = useState<string | null>(null)
  const listRef = useRef<DocumentListHandle>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const accountName = authSession?.user.name || 'Your workspace'
  const accountEmail = authSession?.user.email || ''
  const ready = journey.phase === 'brief' || journey.phase === 'review_required'
  const active = SECTIONS.find((item) => item.id === section)!

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'auto' })
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const animation = contentRef.current?.animate(
      [
        { opacity: 0, transform: 'translateY(7px)' },
        { opacity: 1, transform: 'translateY(0)' },
      ],
      { duration: 260, easing: 'cubic-bezier(.2,.8,.2,1)' },
    )
    return () => animation?.cancel()
  }, [section, filename])

  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setSearchOpen((value) => !value)
      }
    }
    window.addEventListener('keydown', shortcut)
    return () => window.removeEventListener('keydown', shortcut)
  }, [])

  const selectDocument = useCallback((next: string | null) => {
    setReadOnlyProgress(false)
    setSavedJobId(null)
    setFilename(next)
    setSection('overview')
    setCitations([])
    setHoveredCitation(null)
    setJourney({ phase: 'opening', stage: null })
  }, [])

  const openSavedProgress = useCallback((next: string, jobId: string) => {
    selectDocument(next)
    setReadOnlyProgress(true)
    setSavedJobId(jobId)
  }, [selectDocument])
  const uploaded = useCallback(
    (result: UploadResult) => {
      listRef.current?.refresh()
      selectDocument(result.filename)
    },
    [selectDocument],
  )
  const caseReady = useCallback((documentCase: DocumentIntelligenceCase) => {
    setJourney({
      phase:
        documentCase.status === 'needs_human_review' ||
        documentCase.audit?.passed === false
          ? 'review_required'
          : 'brief',
      stage: 'audit_complete',
    })
  }, [])
  const openSettings = () => {
    setDisplayName(accountName)
    setSettingsStatus(null)
    setSettingsOpen(true)
  }

  const saveSettings = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!displayName.trim()) {
      setSettingsError(true)
      setSettingsStatus('Please enter a display name.')
      return
    }
    setSaving(true)
    setSettingsStatus(null)
    try {
      const result = await authClient.updateUser({ name: displayName.trim() })
      if (result.error)
        throw new Error(
          result.error.message || 'Could not update your account.',
        )
      setSettingsError(false)
      setSettingsStatus('Your changes have been saved.')
      await authClient.getSession()
    } catch (error) {
      setSettingsError(true)
      setSettingsStatus(
        error instanceof Error ? error.message : 'Please try again.',
      )
    } finally {
      setSaving(false)
    }
  }

  const signOut = async () => {
    setSigningOut(true)
    setAccountError(null)
    try {
      const result = await authClient.signOut()
      if (result.error)
        throw new Error(
          result.error.message || 'Could not sign out. Please try again.',
        )
      await waitForSignedOutSession(authClient.$store.atoms.session)
      window.location.assign('/')
    } catch (error) {
      setAccountError(
        error instanceof Error ? error.message : 'Please try again.',
      )
      setSigningOut(false)
    }
  }

  const railButton = (
    icon: IconName,
    label: string,
    onClick: () => void,
    current = false,
    disabled = false,
  ) => (
    <button
      key={icon}
      className={'rail-button ' + (current ? 'is-active' : '')}
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-current={current ? 'page' : undefined}
      disabled={disabled}
    >
      <Icon name={icon} />
      <span className="rail-tooltip" aria-hidden="true">
        {label}
      </span>
    </button>
  )

  return (
    <div className="dmc-desktop">
      <a href="#workspace-content" className="skip-link">
        Skip to content
      </a>
      <div className="dmc-frame">
        <aside className="dmc-rail" aria-label="Workspace navigation">
          <button
            className="rail-brand"
            onClick={() => selectDocument(null)}
            aria-label={`${BRAND_NAME} document library`}
            title={BRAND_NAME}
          >
            <DocumentMark />
          </button>
          <nav className="rail-sections" aria-label="Document sections">
            {SECTIONS.map((item) =>
              railButton(
                item.id,
                item.label,
                () => setSection(item.id),
                !!filename && section === item.id,
                !filename || (item.id === 'ask' && !ready),
              ),
            )}
          </nav>
          <nav className="rail-footer" aria-label="Workspace tools">
            {railButton(
              'files',
              'Manage files',
              () => selectDocument(null),
              !filename,
            )}
            {railButton('settings', 'Account settings', openSettings)}
            {railButton(
              'logout',
              signingOut ? 'Signing out…' : 'Sign out',
              () => void signOut(),
              false,
              signingOut,
            )}
          </nav>
        </aside>

        <div className="dmc-workspace">
          <header className="dmc-topbar">
            <div className="topbar-location">
              <span className="topbar-brand">
                {BRAND_NAME} <span>/</span>
              </span>
              <h1>{filename ? active.label : 'Documents'}</h1>
            </div>
            <div className="topbar-tools">
              <button
                className="workspace-search"
                onClick={() => {
                  setSearch('')
                  setSearchOpen(true)
                }}
                aria-label="Search workspace"
              >
                <Icon name="search" />
                <span>Search workspace</span>
                <kbd>Ctrl K</kbd>
              </button>
              <button
                className="profile-control"
                onClick={openSettings}
                aria-label="Open account settings"
              >
                <span className="profile-avatar">
                  {accountName.slice(0, 1).toUpperCase()}
                </span>
                <span className="profile-copy">
                  <strong>{accountName}</strong>
                  <small>{accountEmail}</small>
                </span>
                <Icon name="chevron" />
              </button>
            </div>
          </header>

          <main id="workspace-content" className="dmc-content" tabIndex={-1}>
            {accountError && (
              <p className="surface-error" role="alert">
                {accountError}
              </p>
            )}
            <div ref={contentRef}>
              {!filename ? (
                <>
                  <header className="page-heading">
                    <div>
                      <span className="eyebrow">YOUR WORKSPACE</span>
                      <h2>Clarity starts here.</h2>
                      <p>
                        Your documents, findings and decisions. All connected.
                      </p>
                    </div>
                    <span className="quiet-badge">
                      <i /> Account-scoped access
                    </span>
                  </header>
                  <section className="library-dashboard">
                    <article className="library-intro surface-card">
                      <span className="eyebrow">FROM SOURCE TO NEXT STEP</span>
                      <h3>
                        Less noise.
                        <br />
                        <span>More understanding.</span>
                      </h3>
                      <p>
                        Turn a PDF into a structured case. Know what it says,
                        what needs attention and where to go next.
                      </p>
                      <div className="library-capabilities">
                        <span>
                          <Icon name="facts" /> Facts & obligations
                        </span>
                        <span>
                          <Icon name="timeline" /> Dates & deadlines
                        </span>
                        <span>
                          <Icon name="evidence" /> Linked evidence
                        </span>
                      </div>
                      <p className="library-intro-note">
                        AI helps you investigate. You stay in control of the
                        decision.
                      </p>
                    </article>
                    <section
                      className="library-upload surface-card"
                      aria-label="New document"
                    >
                      <header className="surface-heading">
                        <h3>New document</h3>
                        <Icon name="upload" />
                      </header>
                      <UploadZone onUploaded={uploaded} />
                      <p className="workspace-data-note">
                        Relevant excerpts may be sent to your configured AI
                        provider. Upload only documents you are authorized to
                        process.
                      </p>
                    </section>
                  </section>
                  <section
                    className="library-files surface-card"
                    aria-labelledby="library-title"
                  >
                    <header className="surface-heading">
                      <div>
                        <span className="eyebrow">CASE LIBRARY</span>
                        <h3 id="library-title">Pick up where you left off</h3>
                      </div>
                      <label className="library-filter">
                        <Icon name="search" />
                        <input
                          aria-label="Search documents"
                          placeholder="Find a document…"
                          value={librarySearch}
                          onChange={(event) =>
                            setLibrarySearch(event.target.value)
                          }
                        />
                      </label>
                    </header>
                    <DocumentList
                      ref={listRef}
                      selectedFilename={null}
                      onSelect={selectDocument}
                      searchQuery={librarySearch}
                    />
                  </section>
                  <AnalysisActivity onOpen={openSavedProgress} />
                </>
              ) : (
                <>
                  <header className="page-heading case-page-heading">
                    <div>
                      <span className="document-breadcrumb">
                        <Icon name="facts" />
                        <span title={filename}>{filename}</span>
                      </span>
                      <p>{active.detail}</p>
                    </div>
                    {journey.phase === 'review_required' && (
                      <button
                        className="review-badge"
                        onClick={() => setSection('evidence')}
                      >
                        <i /> Human review required <Icon name="chevron" />
                      </button>
                    )}
                  </header>
                  <div hidden={section === 'ask'}>
                    <DocumentIntelligencePanel
                      key={`${filename}:${savedJobId ?? 'current'}`}
                      filename={filename}
                      analysisJobId={savedJobId}
                      view={section === 'ask' ? 'overview' : section}
                      autoStart={!readOnlyProgress}
                      onWorkflowChange={setJourney}
                      onCaseReady={caseReady}
                      onViewCitation={setViewingCitation}
                      onNavigate={setSection}
                    />
                  </div>
                  {ready && (
                    <section
                      hidden={section !== 'ask'}
                      className="investigation-layout"
                      aria-label="Document investigation"
                    >
                      <div className="case-chat surface-card">
                        <ChatInterface
                          documentFilter={filename}
                          onCitations={setCitations}
                          onHoverCitation={setHoveredCitation}
                          onViewCitation={setViewingCitation}
                        />
                      </div>
                      <aside className="case-evidence surface-card">
                        <header className="surface-heading">
                          <div>
                            <span className="eyebrow">SOURCE TRAIL</span>
                            <h3>The evidence behind it</h3>
                          </div>
                          <Icon name="evidence" />
                        </header>
                        <CitationsPanel
                          citations={citations}
                          hoveredIndex={hoveredCitation}
                          onViewSource={setViewingCitation}
                        />
                      </aside>
                    </section>
                  )}
                </>
              )}
            </div>
            <footer className="workspace-footnote">
              <span>
                <DocumentMark /> Evidence first. Decisions yours.
              </span>
              <span>{BRAND_NAME} · Document intelligence</span>
            </footer>
          </main>
        </div>
      </div>

      <Dialog
        open={settingsOpen}
        titleId="settings-title"
        onClose={() => setSettingsOpen(false)}
      >
        <header className="dialog-heading">
          <div>
            <span className="eyebrow">YOUR ACCOUNT</span>
            <h2 id="settings-title">Make it yours.</h2>
            <p>Manage your workspace identity.</p>
          </div>
          <button
            className="icon-button"
            onClick={() => setSettingsOpen(false)}
            aria-label="Close settings"
          >
            <Icon name="close" />
          </button>
        </header>
        <form
          className="settings-form"
          onSubmit={(event) => void saveSettings(event)}
        >
          <label>
            Display name
            <input
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              autoComplete="name"
              maxLength={120}
              required
              autoFocus
            />
          </label>
          <label>
            Email address
            <input value={accountEmail} readOnly />
          </label>
          <p className="muted-copy">
            Your sign-in email cannot be changed here.
          </p>
          {settingsStatus && (
            <p
              className={settingsError ? 'surface-error' : 'surface-success'}
              role={settingsError ? 'alert' : 'status'}
            >
              {settingsStatus}
            </p>
          )}
          <footer>
            <button
              type="button"
              className="secondary-button"
              onClick={() => setSettingsOpen(false)}
            >
              Cancel
            </button>
            <button className="primary-button" disabled={saving}>
              {saving ? 'Saving…' : 'Save changes'}
              <Icon name="arrow" />
            </button>
          </footer>
        </form>
      </Dialog>
      <Dialog
        open={searchOpen}
        titleId="search-title"
        onClose={() => setSearchOpen(false)}
        className="search-dialog"
      >
        <header className="dialog-heading">
          <h2 id="search-title">Go somewhere.</h2>
          <button
            className="icon-button"
            onClick={() => setSearchOpen(false)}
            aria-label="Close search"
          >
            <Icon name="close" />
          </button>
        </header>
        <label className="command-input">
          <Icon name="search" />
          <input
            aria-label="Search workspace destinations"
            autoFocus
            placeholder="Find a page or search your documents…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <div className="command-results">
          <button
            onClick={() => {
              selectDocument(null)
              setLibrarySearch(search)
              setSearchOpen(false)
            }}
          >
            <Icon name="files" />
            <span>
              Document library
              <small>
                {search
                  ? 'Search files for “' + search + '”'
                  : 'Browse and manage your files'}
              </small>
            </span>
            <Icon name="arrow" />
          </button>
          {filename &&
            SECTIONS.filter((item) =>
              (item.label + ' ' + item.detail)
                .toLowerCase()
                .includes(search.toLowerCase()),
            ).map((item) => (
              <button
                key={item.id}
                disabled={item.id === 'ask' && !ready}
                onClick={() => {
                  setSection(item.id)
                  setSearchOpen(false)
                }}
              >
                <Icon name={item.id} />
                <span>
                  {item.label}
                  <small>{item.detail}</small>
                </span>
                <Icon name="arrow" />
              </button>
            ))}
        </div>
      </Dialog>
      <PdfPageModal
        citation={viewingCitation}
        onClose={() => setViewingCitation(null)}
      />
    </div>
  )
}

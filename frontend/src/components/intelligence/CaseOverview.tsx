import { useState } from 'react'
import type { Citation, DocumentIntelligenceCase } from '../../api/client'
import type { CaseWorkspaceView } from './types'
import Icon from '../ui/Icon'
import { calendarDate } from '../../utils/dates'

interface Props {
  documentCase: DocumentIntelligenceCase
  onNavigate?: (view: CaseWorkspaceView) => void
  onViewCitation: (citation: Citation) => void
}

const dateKey = (year: number, month: number, day: number) =>
  `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`

export function DeadlineCalendar({
  documentCase,
  onNavigate,
  onViewCitation,
}: Props) {
  const dates = (documentCase.deadlines ?? [])
    .filter((entry) => calendarDate(entry.date))
    .sort((a, b) => a.date.localeCompare(b.date))
  const today = new Date()
  const initial =
    dates.find(
      (entry) =>
        entry.date >=
        dateKey(today.getFullYear(), today.getMonth(), today.getDate()),
    ) ?? dates[0]
  const [month, setMonth] = useState(() =>
    initial ? calendarDate(initial.date)! : today,
  )
  const [selected, setSelected] = useState<string | null>(initial?.date ?? null)
  const year = month.getFullYear(),
    monthNumber = month.getMonth()
  const offset = (new Date(year, monthNumber, 1).getDay() + 6) % 7
  const days = new Date(year, monthNumber + 1, 0).getDate()
  const selectedEntries = dates.filter((entry) => entry.date === selected)
  const moveMonth = (direction: number) => {
    const next = new Date(year, monthNumber + direction, 1)
    setMonth(next)
    setSelected(
      dates.find((entry) =>
        entry.date.startsWith(
          dateKey(next.getFullYear(), next.getMonth(), 1).slice(0, 7),
        ),
      )?.date ?? null,
    )
  }
  return (
    <section
      className="deadline-calendar surface-card"
      aria-label="Source deadline calendar"
    >
      <header className="surface-heading">
        <h3>Deadline calendar</h3>
        <button
          className="icon-button"
          onClick={() => onNavigate?.('timeline')}
          aria-label="Open timeline"
        >
          <Icon name="arrow" />
        </button>
      </header>
      <div className="calendar-controls">
        <button
          className="icon-button"
          onClick={() => moveMonth(-1)}
          aria-label="Previous month"
        >
          <Icon name="chevron" className="rotate-half" />
        </button>
        <strong aria-live="polite">
          {month.toLocaleDateString('en-GB', {
            month: 'long',
            year: 'numeric',
          })}
        </strong>
        <button
          className="icon-button"
          onClick={() => moveMonth(1)}
          aria-label="Next month"
        >
          <Icon name="chevron" />
        </button>
      </div>
      <div className="calendar-grid">
        {['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((day, index) => (
          <span key={index} className="calendar-weekday" aria-hidden="true">
            {day}
          </span>
        ))}
        {Array.from({ length: offset }, (_, index) => (
          <span key={`empty-${index}`} aria-hidden="true" />
        ))}
        {Array.from({ length: days }, (_, index) => {
          const key = dateKey(year, monthNumber, index + 1)
          const events = dates.filter((entry) => entry.date === key)
          return (
            <button
              key={key}
              className={`calendar-day ${selected === key ? 'is-selected' : ''} ${events.length ? 'has-deadline' : ''}`}
              aria-pressed={selected === key}
              aria-label={`${key}${events.length ? `, ${events.length} source deadlines` : ', no source deadlines'}`}
              onClick={() => setSelected(key)}
            >
              {index + 1}
              {events.length > 0 && <i />}
            </button>
          )
        })}
      </div>
      <div className="calendar-agenda" aria-live="polite">
        {selectedEntries.length ? (
          selectedEntries.map((entry) => (
            <article key={entry.id}>
              <span className="eyebrow">{entry.date}</span>
              <strong>{entry.event}</strong>
              <small>{entry.owner || 'Owner not specified in source'}</small>
              <div className="case-source-links">
                {entry.citation_ids.map((id) => {
                  const source = documentCase.citations.find(
                    (item) => item.id === id,
                  )
                  return (
                    source && (
                      <button
                        key={id}
                        onClick={() =>
                          onViewCitation({
                            filename: source.filename,
                            page: source.page,
                            text: source.excerpt,
                          })
                        }
                      >
                        Page {source.page} <Icon name="arrow" />
                      </button>
                    )
                  )
                })}
              </div>
            </article>
          ))
        ) : (
          <p>
            {dates.length
              ? 'No source deadlines on this date.'
              : 'No calendar dates extracted yet. Relative dates and undated obligations remain in Timeline.'}
          </p>
        )}
      </div>
    </section>
  )
}

export default function CaseOverview(props: Props) {
  const { documentCase, onNavigate } = props
  const findings: { label: string; value: number; view: CaseWorkspaceView }[] =
    [
      { label: 'Facts', value: documentCase.facts?.length ?? 0, view: 'facts' },
      {
        label: 'Obligations',
        value: documentCase.obligations?.length ?? 0,
        view: 'facts',
      },
      { label: 'Risks', value: documentCase.risks?.length ?? 0, view: 'risks' },
      {
        label: 'Decisions',
        value: documentCase.final_action_pack?.decisions_required?.length ?? 0,
        view: 'decisions',
      },
      {
        label: 'Actions',
        value: documentCase.final_action_pack?.action_items?.length ?? 0,
        view: 'actions',
      },
    ]
  const max = Math.max(1, ...findings.map((item) => item.value))
  const total = findings.reduce((sum, item) => sum + item.value, 0)
  const [selected, setSelected] = useState(0)
  return (
    <div className="overview-dashboard">
      <section
        className="findings-chart surface-card"
        aria-label="Extracted findings by category"
      >
        <header className="surface-heading">
          <div>
            <h3>Your document, mapped.</h3>
            <p>Real findings from the completed analysis.</p>
          </div>
          <span className="quiet-badge">Source-backed</span>
        </header>
        <div className="chart-summary">
          <strong>{total}</strong>
          <span>
            extracted findings{' '}
            <small>
              {documentCase.document.page_count ?? '—'} pages ·{' '}
              {documentCase.document.chunk_count ?? '—'} source fragments
            </small>
          </span>
        </div>
        <div className="findings-bars">
          {findings.map((item, index) => (
            <button
              className={`finding-column ${selected === index ? 'is-selected' : ''}`}
              key={item.label}
              aria-label={`${item.label}: ${item.value} extracted. Select category.`}
              aria-pressed={selected === index}
              onClick={() => setSelected(index)}
            >
              <span className="finding-bar-area">
                <span className="finding-value">{item.value}</span>
                <span
                  className="finding-bar"
                  style={{ height: `${(item.value / max) * 100}%` }}
                />
              </span>
              <span className="finding-label">{item.label}</span>
            </button>
          ))}
        </div>
        <footer className="chart-footer">
          <span>
            Counts reflect extracted items, not a completeness guarantee.
          </span>
          <button onClick={() => onNavigate?.(findings[selected].view)}>
            Explore {findings[selected].label.toLowerCase()}{' '}
            <Icon name="arrow" />
          </button>
        </footer>
      </section>
      <DeadlineCalendar {...props} />
    </div>
  )
}

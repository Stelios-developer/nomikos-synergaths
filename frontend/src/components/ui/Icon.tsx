import type { ReactNode } from 'react'

export type IconName =
  | 'overview'
  | 'facts'
  | 'timeline'
  | 'risks'
  | 'actions'
  | 'decisions'
  | 'evidence'
  | 'ask'
  | 'files'
  | 'settings'
  | 'logout'
  | 'search'
  | 'close'
  | 'arrow'
  | 'chevron'
  | 'upload'

const paths: Record<IconName, ReactNode> = {
  overview: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="2" />
      <rect x="14" y="3" width="7" height="7" rx="2" />
      <rect x="3" y="14" width="7" height="7" rx="2" />
      <rect x="14" y="14" width="7" height="7" rx="2" />
    </>
  ),
  facts: (
    <>
      <path d="M8 3h8l4 4v13H8zM16 3v5h4M11 12h6M11 16h6" />
      <path d="M4 7v13" />
    </>
  ),
  timeline: (
    <>
      <rect x="3" y="5" width="18" height="16" rx="3" />
      <path d="M7 3v4M17 3v4M3 11h18M7 15h2M13 15h2M7 18h2" />
    </>
  ),
  risks: (
    <>
      <path d="m12 3 8 3v6c0 4-4 7-8 9-4-2-8-5-8-9V6zM12 8v5M12 16h.01" />
    </>
  ),
  actions: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="m8 12 3 3 5-6" />
    </>
  ),
  decisions: (
    <>
      <path d="M4 5h16v13H4zM9 5v13M12 9h5M12 13h3" />
    </>
  ),
  evidence: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="m16 16 5 5m-13-11 2 2 3-4" />
    </>
  ),
  ask: (
    <>
      <path d="M4 4h16v12H10l-6 4zM8 9h8M8 12h4" />
    </>
  ),
  files: (
    <>
      <path d="M3 7V5a2 2 0 0 1 2-2h5l3 3h6a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 9h18" />
    </>
  ),
  settings: (
    <>
      <path d="m9 3-.7 3-2.7 1.5L3 7l-1 3 2.2 2L4 15l-1 2 2 2 2.5-.7L10 20l1 2 3-1 .5-2.5 2.5-1.5 3 .5 1-3-2-2 .3-3 1-2-2-2-2.5.7L13 4l-1-2z" />
      <circle cx="11.5" cy="12" r="3" />
    </>
  ),
  logout: (
    <>
      <path d="M10 4H4v16h6M10 12h11m-4-4 4 4-4 4" />
    </>
  ),
  search: (
    <>
      <circle cx="10" cy="10" r="6" />
      <path d="m15 15 5 5" />
    </>
  ),
  close: <path d="m6 6 12 12M6 18 18 6" />,
  arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
  chevron: <path d="m9 5 7 7-7 7" />,
  upload: (
    <>
      <path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6" />
    </>
  ),
}

export default function Icon({
  name,
  className = '',
}: {
  name: IconName
  className?: string
}) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  )
}

export function DocumentMark() {
  return (
    <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true">
      <path
        fill="currentColor"
        d="m3 7 11 9L3 25zm26 0-11 9 11 9zM5 4h22L16 13zm0 24 11-9 11 9z"
      />
    </svg>
  )
}

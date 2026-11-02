# NOMIKOS SYNERGATHS workspace design

## Product identity

The public product name is **NOMIKOS SYNERGATHS**. Shared frontend copy uses
`frontend/src/brand.ts`; page metadata, account emails and workflow display names
use the same spelling. The longer name has compact, readable typography in the
header and authentication screens.

Legacy cookie prefixes, CSRF values, database/volume names, webhook paths,
workflow IDs and encrypted-backup identifiers remain compatibility contracts,
not public branding. Do not rename them without a separate data/session migration.
Historical exports, backups and user-uploaded documents are not rewritten.

The workspace uses a dark, graphite dashboard system inspired by the supplied
reference. The palette intentionally differs from the earlier green UI.
White selected navigation, thin outlines, restrained blue accents and
consistent card headers connect every destination.

## Structure

- An icon rail holds the eight case destinations. Tooltips, accessible names
  and a visible selected state accompany every icon. Files, account settings
  and sign-out stay in its footer.
- A sticky header holds the destination, workspace search and account control.
  Search supports Ctrl/Cmd+K, page navigation and filtering file names. It is
  not presented as full-text document search.
- Overview combines actual extraction counts, a source-deadline calendar,
  document context, evidence checks and next steps. It contains no simulated
  financial metrics or completeness percentage.
- Facts, Timeline, Risks, Action plan, Decision center, Evidence and Assistant
  have focused layouts. Evidence exposes claim checks and original sources.
  Decisions and actions remain proposals, not approval or execution controls.
- The Assistant preserves its conversation between tab changes. Stream updates
  scroll the message container, not the entire page.
- Authentication, recovery, settings, file deletion, source previews, loading,
  empty and error states use the same visual system.

## Implementation

frontend/src/styles/ separates foundation tokens, workspace layout,
intelligence cards, the assistant and account/dialog styles. Icons are local
SVGs; fonts use a local system stack. No remote font request is needed.

The application still uses Better Auth and the existing backend endpoints.
There is no demo-session switch, auth bypass or synthetic dashboard data in
the production bundle. Mutation requests retain the existing CSRF header.

The calendar accepts valid, unambiguous YYYY-MM-DD source dates only. Relative
dates and undated obligations remain in Timeline. Review badges are conditional
and appear once in the shared page heading.

Native dialogs have Escape/backdrop dismissal, body-scroll locking and a Tab
loop. Focus indicators, reduced-motion preferences and responsive layouts are
part of the shared styles.

## Verification

From frontend/:

~~~powershell
npm run build
npm run lint
~~~

The browser regression suite installs pinned Playwright/axe development
dependencies. Use an installed Chrome channel or matching bundled Chromium,
Firefox and WebKit. Start a dedicated Vite server in one terminal:

~~~powershell
cd frontend
$env:DMC_AUTH_PROXY_TARGET='http://127.0.0.1:5199'
npm run dev -- --host 127.0.0.1 --port 5197 --strictPort
~~~

Then, from the repository root:

~~~powershell
$env:UI_TEST_URL='http://127.0.0.1:5197'
$env:DMC_AUTH_PROXY_TARGET='http://127.0.0.1:5199'
$env:UI_TEST_BROWSER='chrome'
npm run test:ui
~~~

`UI_TEST_ENGINE` selects chromium/firefox/webkit. `UI_TEST_BROWSER` optionally
selects an installed Chromium channel. The root command requires an isolated
loopback URL and refuses port 5173.

The test uses synthetic .test account/document fixtures, with a loopback-only
auth server verified by a random probe, blocks external requests and writes screenshots to ignored
output/engineering-ui/<engine>/. It exercises all tabs, responsive overflow, sticky
headers, the calendar, keyboard dialog navigation, settings submission,
search, source previews, conversation continuity, deletion, upload validation,
analysis retry, failed initial load/refresh, sign-out and automated accessibility.
These are UI/contract checks, **not evidence that
the live backend, authentication provider, n8n or PDF scanner passed an
end-to-end integration/security audit**.

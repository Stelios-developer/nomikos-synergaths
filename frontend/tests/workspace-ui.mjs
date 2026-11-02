import assert from 'node:assert/strict'
import { mkdir, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { filename, documentCase, session } from './fixtures/workspace.mjs'

// Start Vite first. Uses Playwright from node_modules or the QA runtime's NODE_PATH.
// Every API request is intercepted. This is a UI regression suite, not a live auth/security test.
const require = createRequire(import.meta.url)
const engines = require('playwright')
const AxeBuilder = require('@axe-core/playwright').default
const engine = process.env.UI_TEST_ENGINE || 'chromium'
if (!['chromium', 'firefox', 'webkit'].includes(engine)) throw new Error('Unknown browser engine')
const base = process.env.UI_TEST_URL || 'http://127.0.0.1:5173'
const output = new URL(
  '../../output/engineering-ui/' + engine + '/',
  import.meta.url,
).pathname.replace(/^\/([A-Z]:)/, '$1')
await mkdir(output, { recursive: true })
const browser = await engines[engine].launch({
  headless: true,
  ...(engine === 'chromium' && process.env.UI_TEST_BROWSER ? { channel: process.env.UI_TEST_BROWSER } : {}),
})
let checks = 0
let complete = false
const startedAt = new Date().toISOString()
const brand = 'NOMIKOS SYNERGATHS'
const check = (condition, label) => {
  assert.ok(condition, label)
  checks++
  console.log('PASS ' + label)
}
const tabs = [
  'Overview',
  'Facts & obligations',
  'Timeline',
  'Risk radar',
  'Action plan',
  'Decision center',
  'Evidence',
  'Document assistant',
]
const activeSession = structuredClone(session)
let authenticated = true,
  files = [
    { filename, chunk_count: 24, method: 'pymupdf', upload_date: '2026-10-01' },
  ]
let storedCase = structuredClone(documentCase),
  libraryFails = true,
  caseMissing = false,
  analysisFails = false,
  analysisUncertain = false,
  workflowRequests = 0,
  savedName = null
let activityJobs = []
let lastResultJobId = null
let activityResolutions = 0
const errors = []
const context = await browser.newContext({
  viewport: { width: 1440, height: 1050 },
  reducedMotion: 'reduce',
})
const page = await context.newPage()
page.on('pageerror', (error) => {
  errors.push(error.message)
  console.error('Browser runtime error:', error.name, error.message, error.stack)
})
page.on('request', (request) => {
  if (request.url().startsWith(new URL('/api/auth/', base).href))
    console.log('Synthetic auth request:', request.method(), new URL(request.url()).pathname)
})
page.on('requestfailed', (request) => {
  if (request.url().startsWith(new URL('/api/auth/', base).href))
    console.error('Synthetic auth request failed:', request.method(), new URL(request.url()).pathname, request.failure()?.errorText)
})
await page.route('**/*', async (route) => {
  const request = route.request(),
    url = new URL(request.url()),
    path = url.pathname
  const json = (data, status = 200) =>
    route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(data),
    })
  if (path.startsWith('/api/auth/')) {
    if (path.endsWith('/get-session'))
      return json(authenticated ? activeSession : null)
    if (path.endsWith('/update-user')) {
      savedName = request.postDataJSON().name
      activeSession.user.name = savedName
      return json({ status: true })
    }
    if (path.endsWith('/sign-out')) {
      authenticated = false
      return json({ success: true })
    }
    return json({ code: 'UI_FIXTURE', message: 'Test-only auth response' }, 400)
  }
  if (path.startsWith('/api/')) {
    if (request.method() !== 'GET')
      check(
        request.headers()['x-csrf-protection'] === 'nexus-v1',
        'Mutation retains the CSRF header',
      )
    if (path === '/api/analysis/jobs' && request.method() === 'GET') return json(activityJobs)
    if (path.startsWith('/api/analysis/jobs/') && path.endsWith('/result')) {
      lastResultJobId = path.split('/')[4]
      return caseMissing ? json({ detail: 'No saved result' }, 404) : json(storedCase)
    }
    if (path.startsWith('/api/analysis/jobs/') && path.endsWith('/resolve')) {
      const id = path.split('/')[4]
      const action = request.postDataJSON().action
      const job = activityJobs.find(item => item.job_id === id)
      activityResolutions++
      Object.assign(job, { state: action === 'close' || job.state === 'accepted' ? 'cancelled' : 'cancel_requested', can_cancel: false, can_close: false })
      return json(job)
    }
    if (path === '/api/documents' && request.method() === 'GET')
      return libraryFails ? json({ detail: 'Library temporarily unavailable' }, 503) : json(files)
    if (path.endsWith('/intelligence'))
      return caseMissing
        ? json({ detail: 'No case yet' }, 404)
        : json(storedCase)
    if (path.endsWith('/intelligence/stream')) {
      workflowRequests++
      if (analysisUncertain)
        return route.fulfill({ contentType: 'text/event-stream', body: 'data: {"type":"error","message":"Check saved progress before starting again.","code":"ANALYSIS_UNCERTAIN","uncertain":true}\n\n' })
      if (analysisFails)
        return json({ detail: 'Test analysis unavailable' }, 503)
      caseMissing = false
      const events = [
        'started',
        'dna_complete',
        'facts_complete',
        'risks_complete',
        'brief_complete',
        'audit_complete',
      ].map((stage) => ({ type: 'stage', stage }))
      events.push({ type: 'done', case: storedCase })
      return route.fulfill({
        contentType: 'text/event-stream',
        body: events
          .map((event) => 'data: ' + JSON.stringify(event) + '\n\n')
          .join(''),
      })
    }
    if (path.endsWith('/page'))
      return route.fulfill({
        contentType: 'image/svg+xml',
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="white"/><text x="40" y="70" font-size="22" fill="black">Synthetic source preview</text><rect x="40" y="100" width="420" height="35" fill="#ffe588"/><text x="45" y="123" font-size="16" fill="black">First release: 15 October 2026</text></svg>',
      })
    if (path === '/api/query') {
      const events = [
        {
          type: 'token',
          content: 'The first release is due on **15 October 2026** [1].',
        },
        {
          type: 'done',
          citations: [
            { filename, page: 2, text: documentCase.citations[0].excerpt },
          ],
          eval: null,
        },
      ]
      return route.fulfill({
        contentType: 'text/event-stream',
        body: events
          .map((event) => 'data: ' + JSON.stringify(event) + '\n\n')
          .join(''),
      })
    }
    if (path === '/api/audit/run')
      return json({
        sentences: [
          {
            text: 'The first release is due on 15 October 2026.',
            supported: true,
            reason: 'Source match',
          },
        ],
      })
    if (path === '/api/upload') {
      files = [
        {
          filename: 'Uploaded fixture.pdf',
          chunk_count: 24,
          method: 'pymupdf',
        },
      ]
      storedCase.document.filename = 'Uploaded fixture.pdf'
      return json({
        filename: 'Uploaded fixture.pdf',
        chunk_count: 24,
        method: 'pymupdf',
      })
    }
    if (request.method() === 'DELETE') {
      files = []
      return json({ deleted: true })
    }
    return json({ detail: 'Unexpected fixture endpoint: ' + path }, 404)
  }
  if (url.origin === new URL(base).origin) return route.continue()
  return route.abort() // No external data or font requests are needed.
})
const shot = async (name) => {
  await page.mouse.move(0, 0)
  return page.screenshot({ path: output + name + '.png', fullPage: true })
}
const openFile = async () => {
  await page.locator('.document-select-button').first().click()
  await page.locator('.findings-chart').waitFor()
}
const noOverflow = async (label) =>
  check(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1,
    ),
    label,
  )
const checkBrand = async (label) => {
  check((await page.title()).startsWith(brand), label + ': new browser title')
  check(!/\bnexus\b/i.test(await page.locator('body').innerText()), label + ': no old visible brand')
}
const accessibility = []
const scan = async (label) => {
  const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']).analyze()
  accessibility.push({ label, violations: result.violations, incomplete: result.incomplete })
  check(result.violations.length === 0, 'Automated accessibility: ' + label + ': ' + JSON.stringify(result.violations.map(v => ({ id: v.id, targets: v.nodes.map(n => n.target) }))))
}
try {
  await page.goto(base)
  await page.getByText('Library unavailable. Your documents have not been confirmed as empty.').waitFor()
  check((await page.getByText('A fresh start.', { exact: true }).count()) === 0, 'Failed initial load never looks like an empty library')
  libraryFails = false
  await page.getByRole('button', { name: 'Retry library', exact: true }).click()
  await page.locator('.document-select-button').waitFor()
  libraryFails = true
  await page.getByRole('button', { name: 'Refresh library', exact: true }).click()
  await page.getByText(/Showing the last successful result/).waitFor()
  check(!(await page.locator('.document-select-button').first().isEnabled()), 'Stale library stays visible but actions wait for a successful refresh')
  libraryFails = false
  await page.getByRole('button', { name: 'Retry library', exact: true }).click()
  await page.locator('.document-select-button:enabled').waitFor()
  await checkBrand('Document library')
  check(
    await page.getByRole('button', { name: brand + ' document library', exact: true }).isVisible(),
    'New accessible brand on the navigation rail',
  )
  await shot('library-desktop')
  await page.getByLabel('Search documents', { exact: true }).fill('no-match')
  await page.getByText('No matching documents').waitFor()
  check(
    (await page.locator('.document-select-button').count()) === 0,
    'Document filter has a real empty result',
  )
  await page.getByLabel('Search documents', { exact: true }).fill('')
  await openFile()
  for (const [index, tab] of tabs.entries()) {
    await page
      .getByRole('navigation', { name: 'Document sections' })
      .getByRole('button', { name: tab, exact: true })
      .click()
    await page
      .getByRole('heading', { level: 1, name: tab, exact: true })
      .waitFor()
    check(
      (await page.locator('.review-badge:visible').count()) === 1,
      'One review notice on ' + tab,
    )
    await noOverflow('Desktop fits: ' + tab)
    await checkBrand(tab)
    await scan(tab)
    await page.evaluate(() => scrollTo(0, document.body.scrollHeight))
    check(
      await page
        .locator('.dmc-topbar')
        .evaluate((header) => header.getBoundingClientRect().top >= -1),
      'Header stays visible on scroll: ' + tab,
    )
    await page.evaluate(() => scrollTo(0, 0))
    await shot('tab-' + index)
  }
  await page.getByRole('button', { name: 'Overview', exact: true }).click()
  await page.getByRole('button', { name: 'Next month', exact: true }).click()
  check(
    (await page.getByText('November 2026', { exact: true }).count()) === 1,
    'Calendar navigation changes month',
  )
  await page
    .getByRole('button', { name: 'Previous month', exact: true })
    .click()
  await page
    .getByRole('button', { name: 'Facts & obligations', exact: true })
    .click()
  await page
    .locator('.case-section--facts .case-source-links button')
    .first()
    .click()
  await page.locator('.source-preview-dialog img').waitFor()
  check(
    await page
      .locator('.source-preview-dialog')
      .evaluate((dialog) => dialog.open),
    'Original page opens in a focus-contained dialog',
  )
  await page.keyboard.press('Escape')
  check(
    (await page.locator('.source-preview-dialog').count()) === 0,
    'Source preview closes with Escape',
  )
  await page
    .getByRole('button', { name: 'Document assistant', exact: true })
    .click()
  await page
    .getByLabel('Ask a question about your documents')
    .fill('When is the release due?')
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await page.locator('.citation-source-card').waitFor()
  check(
    await page.locator('.chat-workspace').getByText(brand, { exact: true }).count() > 0,
    'Assistant messages use the new brand',
  )
  await page.getByRole('button', { name: 'Overview', exact: true }).click()
  await page
    .getByRole('button', { name: 'Document assistant', exact: true })
    .click()
  check(
    await page
      .getByText('When is the release due?', { exact: true })
      .isVisible(),
    'Conversation survives a tab change',
  )
  await shot('assistant-conversation')
  await page.keyboard.press('Control+k')
  await page
    .getByPlaceholder('Find a page or search your documents…')
    .fill('risk')
  await page
    .locator('.command-results')
    .getByRole('button', { name: /Risk radar/ })
    .click()
  check(
    await page
      .getByRole('heading', { name: 'Risk radar', level: 1 })
      .isVisible(),
    'Workspace search navigates to a matching tab',
  )
  await page
    .getByRole('button', { name: 'Account settings', exact: true })
    .click()
  for (let index = 0; index < 12; index++) {
    await page.keyboard.press('Tab')
    check(
      await page.evaluate(
        () => !!document.activeElement?.closest('dialog[open]'),
      ),
      'Settings keyboard focus stays in the dialog',
    )
  }
  await page.getByLabel('Display name').fill('Updated QA Name')
  await page.getByRole('button', { name: 'Save changes' }).click()
  await page.getByText('Your changes have been saved.').waitFor()
  check(
    savedName === 'Updated QA Name',
    'Settings submits the actual name update',
  )
  await shot('account-settings')
  await page.keyboard.press('Escape')
  check(
    (await page.locator('dialog[open]').count()) === 0,
    'Settings closes with Escape',
  )
  for (const width of [320, 390, 768]) {
    await page.setViewportSize({ width, height: 844 })
    for (const tab of tabs) {
      await page
        .getByRole('navigation', { name: 'Document sections' })
        .getByRole('button', { name: tab, exact: true })
        .click()
      await noOverflow(width + 'px fits: ' + tab)
    }
    await page.getByRole('button', { name: 'Overview', exact: true }).click()
    await shot('overview-' + width)
  }
  await page.setViewportSize({ width: 1440, height: 1050 })
  await page.getByRole('button', { name: 'Manage files', exact: true }).click()
  const makeJob = (id, name, state, expired = false) => ({
    job_id: id.repeat(32), filename: name, state, attempts: state === 'accepted' ? 0 : 1,
    deadline: new Date(Date.now() + (expired ? -60_000 : 900_000)).toISOString(),
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(), reason: '',
    can_cancel: true, can_close: expired, result_available: false,
  })
  activityJobs = [makeJob('a', 'Queued fixture.pdf', 'accepted'), makeJob('b', 'Uncertain fixture.pdf', 'uncertain'), makeJob('c', 'Expired fixture.pdf', 'uncertain', true)]
  await page.getByRole('button', { name: 'Refresh activity' }).and(page.locator(':enabled')).click()
  const queued = page.getByRole('article', { name: 'Analysis of Queued fixture.pdf' })
  const uncertainJob = page.getByRole('article', { name: 'Analysis of Uncertain fixture.pdf' })
  await queued.waitFor()
  check((await uncertainJob.getByRole('button', { name: 'Close attempt' }).count()) === 0, 'Uncertain work cannot be closed before its safe deadline')
  await scan('Background activity')
  await queued.getByRole('button', { name: 'Cancel analysis' }).and(page.locator(':enabled')).click()
  await page.getByRole('heading', { name: 'Cancel this analysis?' }).waitFor()
  await scan('Activity confirmation')
  await page.getByRole('button', { name: 'Confirm cancellation' }).click()
  await queued.waitFor({ state: 'detached' })
  check(activityResolutions === 1, 'Queued cancellation is one explicit mutation')
  const expiredJob = page.getByRole('article', { name: 'Analysis of Expired fixture.pdf' })
  await expiredJob.getByRole('button', { name: 'Close attempt' }).and(page.locator(':enabled')).click()
  await page.getByRole('button', { name: 'Confirm closure' }).click()
  await expiredJob.waitFor({ state: 'detached' })
  check(activityResolutions === 2, 'Expired uncertain work can be explicitly closed')
  await uncertainJob.getByRole('button', { name: 'Cancel analysis' }).and(page.locator(':enabled')).click()
  await page.getByRole('button', { name: 'Confirm cancellation' }).click()
  await uncertainJob.getByText('Cancellation requested', { exact: true }).waitFor()
  check(activityResolutions === 3, 'In-flight cancellation is clearly shown as requested')
  await shot('background-activity')
  caseMissing = true
  const beforeProgressRead = workflowRequests
  await uncertainJob.getByRole('button', { name: 'View saved progress' }).and(page.locator(':enabled')).click()
  await page.getByRole('heading', { name: 'No saved result yet' }).waitFor()
  check(workflowRequests === beforeProgressRead, 'Opening activity progress never dispatches analysis when no saved case exists')
  check(lastResultJobId === 'b'.repeat(32), 'Saved progress reads the exact attempt rather than the latest case for a filename')
  caseMissing = false
  const completedFixture = structuredClone(storedCase)
  storedCase = { ...structuredClone(storedCase), stage: 'facts_complete', status: 'in_progress', audit: {}, final_action_pack: {} }
  await page.getByRole('button', { name: 'Manage files', exact: true }).click()
  await page.getByRole('article', { name: 'Analysis of Uncertain fixture.pdf' }).getByRole('button', { name: 'View saved progress' }).and(page.locator(':enabled')).click()
  await page.getByRole('heading', { name: 'Saved progress', exact: true }).waitFor()
  check((await page.getByText('Analysis finished', { exact: true }).count()) === 0, 'A partial saved case is never labelled as a finished analysis')
  check(workflowRequests === beforeProgressRead, 'Inspecting a partial case does not dispatch another analysis')
  storedCase = completedFixture
  activityJobs = []
  await page.getByRole('button', { name: 'Manage files', exact: true }).click()
  await page
    .getByRole('button', { name: 'Delete ' + filename, exact: true })
    .click()
  await shot('delete-confirmation')
  await page.getByRole('button', { name: 'Keep', exact: true }).click()
  await page
    .getByRole('button', { name: 'Delete ' + filename, exact: true })
    .click()
  await page.getByRole('button', { name: 'Remove', exact: true }).click()
  await page.getByText('A fresh start.').waitFor()
  check(files.length === 0, 'File deletion confirms and refreshes the library')
  await page
    .locator('input[type=file]')
    .setInputFiles({
      name: 'not-a-pdf.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('fixture'),
    })
  await page.getByText('Επίλεξε ένα αρχείο PDF.').waitFor()
  check(files.length === 0, 'Non-PDF upload is rejected before a request')
  caseMissing = true
  analysisFails = true
  await page
    .locator('input[type=file]')
    .setInputFiles({
      name: 'Uploaded fixture.pdf',
      mimeType: 'application/pdf',
      buffer: Buffer.from('%PDF-1.7 fixture-only'),
    })
  await page.getByRole('button', { name: 'Retry analysis' }).waitFor()
  await shot('analysis-error')
  analysisFails = false
  analysisUncertain = true
  await page.getByRole('button', { name: 'Retry analysis' }).click()
  await page.getByRole('button', { name: 'Check saved progress' }).waitFor()
  check((await page.getByRole('button', { name: 'Retry analysis' }).count()) === 0,
    'Uncertain analysis offers a saved-progress read rather than another write')
  const dispatchedBeforeRead = workflowRequests
  analysisUncertain = false
  caseMissing = false
  await page.getByRole('button', { name: 'Check saved progress' }).click()
  await page.locator('.findings-chart').waitFor()
  await page.getByRole('button', { name: 'Document assistant', exact: true })
    .and(page.locator(':enabled')).waitFor()
  check(workflowRequests === dispatchedBeforeRead, 'Checking saved progress never starts another workflow')
  check(
    await page
      .getByRole('button', { name: 'Document assistant', exact: true })
      .isEnabled(),
    'Analysis retry restores the completed workspace',
  )
  storedCase = {
    ...storedCase,
    status: 'verified',
    audit: { ...storedCase.audit, passed: true },
    final_action_pack: {
      ...storedCase.final_action_pack,
      verification_status: 'verified',
      human_review_required: false,
    },
  }
  await page.getByRole('button', { name: 'Manage files', exact: true }).click()
  await openFile()
  check(
    (await page.locator('.review-badge').count()) === 0,
    'No review notice when evidence passes',
  )
  const logoutNavigation = page.waitForEvent('framenavigated', { predicate: frame => frame === page.mainFrame(), timeout: 10_000 })
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await logoutNavigation
  await page
    .getByRole('button', { name: 'Enter private workspace', exact: true })
    .waitFor()
  check(!authenticated, 'Sign out reaches the authentication screen')
  await checkBrand('Sign in')
  await scan('Sign in')
  await shot('auth-desktop')
  await page
    .getByRole('button', { name: 'Create account', exact: true })
    .click()
  await page.getByLabel('Your name', { exact: true }).waitFor()
  await checkBrand('Sign up')
  await shot('signup-desktop')
  await page.setViewportSize({ width: 390, height: 844 })
  await noOverflow('Mobile sign-up fits')
  await scan('Mobile sign up')
  check(
    await page.locator('.auth-mobile-brand').getByText(brand, { exact: true }).isVisible(),
    'Full brand stays visible on mobile authentication',
  )
  await shot('auth-mobile')
  check(errors.length === 0, 'No browser runtime errors: ' + errors.join('; '))
  console.log(
    'Completed ' +
      checks +
      ' UI assertions. All API calls were isolated fixtures.',
  )
  complete = true
} finally {
  await writeFile(output + 'accessibility.json', JSON.stringify({
    schema_version: 1, engine, browser_version: browser.version(), started_at: startedAt,
    completed_at: new Date().toISOString(), gate: complete ? 'PASSED' : 'FAILED', assertions: checks,
    scope: 'synthetic fixtures; automated checks only; incomplete findings need manual review', scans: accessibility,
  }, null, 2))
  await browser.close()
}

import { Fragment, useState } from 'react'
import type { FormEvent } from 'react'
import { authClient } from '../../auth/client'
import { DocumentMark } from '../ui/Icon'
import { BRAND_NAME } from '../../brand'

type AuthMode = 'sign-in' | 'sign-up' | 'reset' | 'set-new-password'

function BrandMark() {
  return (
    <span className="auth-brand-mark" aria-hidden="true">
      <DocumentMark />
    </span>
  )
}

function FormMessage({
  message,
  kind,
}: {
  message: string | null
  kind: 'error' | 'success'
}) {
  if (!message) return null
  return (
    <p
      className={`auth-form-message ${kind}`}
      role={kind === 'error' ? 'alert' : 'status'}
    >
      {message}
    </p>
  )
}

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const { data: session, isPending } = authClient.useSession()
  const resetToken = new URLSearchParams(window.location.search).get('token')
  const [mode, setMode] = useState<AuthMode>(
    window.location.pathname === '/reset-password' && resetToken
      ? 'set-new-password'
      : 'sign-in',
  )
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  if (isPending) {
    return (
      <main
        className="auth-loading-screen"
        aria-label="Checking your secure session"
      >
        <div className="auth-loading-orbit">
          <span />
        </div>
        <p>Opening your private workspace</p>
      </main>
    )
  }

  if (session?.user) return <Fragment key={session.user.id}>{children}</Fragment>

  const switchMode = (nextMode: AuthMode) => {
    setMode(nextMode)
    setError(null)
    setSuccess(null)
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSuccess(null)
    setBusy(true)
    try {
      if (mode === 'sign-in') {
        const result = await authClient.signIn.email({ email, password })
        if (result.error)
          throw new Error(result.error.message || 'We could not sign you in.')
      } else if (mode === 'sign-up') {
        const result = await authClient.signUp.email({ name, email, password })
        if (result.error)
          throw new Error(
            result.error.message || 'We could not create your account.',
          )
        setSuccess(
          'Your workspace is ready. Check your inbox if email verification is enabled.',
        )
      } else if (mode === 'reset') {
        const result = await authClient.requestPasswordReset({
          email,
          redirectTo: `${window.location.origin}/reset-password`,
        })
        if (result.error)
          throw new Error(
            result.error.message || 'We could not start the password reset.',
          )
        setSuccess(
          'If this email belongs to an account, a reset link is on its way.',
        )
      } else {
        if (password !== confirmPassword)
          throw new Error('The passwords do not match.')
        const result = await authClient.resetPassword({
          newPassword: password,
          token: resetToken ?? undefined,
        })
        if (result.error)
          throw new Error(
            result.error.message || 'We could not reset your password.',
          )
        setSuccess('Your password was updated. You can now sign in.')
        setPassword('')
        setConfirmPassword('')
        window.history.replaceState({}, '', '/')
        setMode('sign-in')
      }
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : 'Something went wrong. Please try again.',
      )
    } finally {
      setBusy(false)
    }
  }

  const title =
    mode === 'sign-in'
      ? 'Your documents. Your decisions.'
      : mode === 'sign-up'
        ? 'Build a private evidence workspace.'
        : mode === 'reset'
          ? 'Reset your secure access.'
          : 'Choose a new password.'
  const detail =
    mode === 'sign-in'
      ? 'Sign in to continue exactly where your evidence trail left off.'
      : mode === 'sign-up'
        ? 'Create your account and keep every source, question and analysis scoped to you.'
        : mode === 'reset'
          ? 'We will send a single-use reset link without revealing whether an account exists.'
          : 'Use a unique password of at least 12 characters to secure your workspace.'

  return (
    <main className="auth-shell">
      <section className="auth-hero" aria-label={`${BRAND_NAME} document intelligence`}>
        <div className="auth-hero-grid" aria-hidden="true" />
        <div className="auth-brand-lockup">
          <BrandMark />
          <span>{BRAND_NAME}</span>
        </div>
        <div className="auth-hero-copy">
          <span className="auth-kicker">
            <i /> Evidence-first document intelligence
          </span>
          <h1>
            Know what matters
            <br />
            before you act.
          </h1>
          <p>
            Turn complex PDFs into clear decisions, with every answer anchored
            to its source.
          </p>
        </div>
        <div className="auth-proof-grid">
          <article>
            <strong>Private workspace</strong>
            <span>Your files stay tied to your account.</span>
          </article>
          <article>
            <strong>Evidence attached</strong>
            <span>Open the source behind every answer.</span>
          </article>
          <article>
            <strong>Decisions, clarified</strong>
            <span>Surface deadlines, obligations and risk.</span>
          </article>
        </div>
        <p className="auth-hero-footer">
          Your documents and analyses stay scoped to your account.
        </p>
      </section>

      <section className="auth-panel" aria-label="Account access">
        <div className="auth-panel-inner">
          <div className="auth-mobile-brand">
            <BrandMark />
            <span>{BRAND_NAME}</span>
          </div>
          {(mode === 'sign-in' || mode === 'sign-up') && (
            <div className="auth-tabs" role="group" aria-label="Account access">
              <button
                className={mode === 'sign-in' ? 'active' : ''}
                aria-pressed={mode === 'sign-in'}
                type="button"
                onClick={() => switchMode('sign-in')}
              >
                Sign in
              </button>
              <button
                className={mode === 'sign-up' ? 'active' : ''}
                aria-pressed={mode === 'sign-up'}
                type="button"
                onClick={() => switchMode('sign-up')}
              >
                Create account
              </button>
            </div>
          )}
          <header className="auth-form-heading">
            <span className="eyebrow">
              {mode === 'reset' || mode === 'set-new-password'
                ? 'ACCOUNT RECOVERY'
                : 'PRIVATE WORKSPACE'}
            </span>
            <h2>{title}</h2>
            <p>{detail}</p>
          </header>
          <form className="auth-form" onSubmit={submit}>
            {mode === 'sign-up' && (
              <label>
                <span>Your name</span>
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  autoComplete="name"
                  minLength={2}
                  maxLength={100}
                  required
                  placeholder="How should we address you?"
                />
              </label>
            )}
            {mode !== 'set-new-password' && (
              <label>
                <span>Work email</span>
                <input
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  type="email"
                  autoComplete="email"
                  required
                  placeholder="you@company.com"
                />
              </label>
            )}
            {mode !== 'reset' && (
              <label>
                <span>Password</span>
                <input
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  type="password"
                  autoComplete={
                    mode === 'sign-in' ? 'current-password' : 'new-password'
                  }
                  minLength={12}
                  required
                  placeholder={
                    mode === 'sign-up'
                      ? 'At least 12 characters'
                      : 'Your password'
                  }
                />
              </label>
            )}
            {mode === 'set-new-password' && (
              <label>
                <span>Confirm new password</span>
                <input
                  value={confirmPassword}
                  onChange={(event) => setConfirmPassword(event.target.value)}
                  type="password"
                  autoComplete="new-password"
                  minLength={12}
                  required
                  placeholder="Repeat your new password"
                />
              </label>
            )}
            <FormMessage message={error} kind="error" />
            <FormMessage message={success} kind="success" />
            <button className="auth-submit" disabled={busy} type="submit">
              {busy
                ? 'Securing your access…'
                : mode === 'sign-in'
                  ? 'Enter private workspace'
                  : mode === 'sign-up'
                    ? 'Create secure workspace'
                    : mode === 'reset'
                      ? 'Send reset link'
                      : 'Save new password'}{' '}
              {!busy && <i aria-hidden="true">→</i>}
            </button>
          </form>
          <div className="auth-form-footer">
            {mode === 'sign-in' && (
              <button type="button" onClick={() => switchMode('reset')}>
                Forgot password?
              </button>
            )}
            {mode === 'reset' && (
              <button type="button" onClick={() => switchMode('sign-in')}>
                ← Back to sign in
              </button>
            )}
            {mode === 'set-new-password' && (
              <button
                type="button"
                onClick={() => {
                  window.history.replaceState({}, '', '/')
                  switchMode('sign-in')
                }}
              >
                ← Back to sign in
              </button>
            )}
            {mode === 'sign-up' && (
              <p>
                By creating an account, you agree to use this workspace only for
                documents you are allowed to process.
              </p>
            )}
          </div>
          <p className="auth-security-note">
            <i aria-hidden="true">◈</i> Protected by secure, HttpOnly sessions.
            Your password is never stored in the browser.
          </p>
        </div>
      </section>
    </main>
  )
}

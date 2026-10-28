import { Component, type ReactNode } from 'react'

/** A render failure must not expose a stack or leave a blank workspace. */
export default class AppErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() {
    if (!this.state.failed) return this.props.children
    return (
      <main className="surface-card" role="alert" style={{ maxWidth: 640, margin: '10vh auto', padding: 32 }}>
        <h1>The workspace could not be displayed.</h1>
        <p>Your stored documents have not been deleted. Reload the workspace to recover.</p>
        <button className="primary-button" type="button" onClick={() => window.location.reload()}>Reload workspace</button>
      </main>
    )
  }
}

/** Cross-platform dispatcher; fixed commands, no shell-built user input. */
import { spawnSync } from 'node:child_process'
import { existsSync, mkdtempSync, mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const candidates = process.platform === 'win32'
  ? ['backend/.venv/Scripts/python.exe', 'backend/venv/Scripts/python.exe']
  : ['backend/.venv/bin/python', 'backend/venv/bin/python']
const python = process.env.DMC_PYTHON || candidates.map(p => resolve(root, p)).find(existsSync) || (process.platform === 'win32' ? 'python' : 'python3')
function run(executable, args, cwd = root, env = process.env) {
  const result = spawnSync(executable, args, { cwd, env, stdio: 'inherit', windowsHide: true })
  if (result.error) throw result.error
  if (result.status !== 0) process.exit(result.status ?? 1)
}
// Invoke the npm JS CLI directly on Windows rather than passing arguments to a shell.
function npmAt(directory, ...args) {
  if (!process.env.npm_execpath) throw new Error('Run this dispatcher through npm run.')
  run(process.execPath, [process.env.npm_execpath, ...args], resolve(root, directory))
}
const command = process.argv[2]
if (command === 'check') {
  run(python, ['scripts/lock_dependencies.py', '--check'])
  run(python, ['scripts/quality/repository_check.py'])
  run(python, ['-m', 'ruff', 'check', 'backend', 'scripts', '--select', 'E9,F63,F7,F82'])
  npmAt('frontend', 'run', 'lint')
  npmAt('frontend', 'run', 'build')
  npmAt('auth-service', 'exec', '--', 'tsc', '--noEmit')
} else if (command === 'test') {
  run(python, ['-m', 'unittest', 'discover', '-s', 'scripts/tests', '-p', 'test_*.py'])
  npmAt('frontend', 'test')
  npmAt('auth-service', 'test')
} else if (command === 'backend') {
  mkdirSync(resolve(root, 'tmp'), { recursive: true })
  const temp = mkdtempSync(resolve(root, 'tmp', 'backend-tests-'))
  run(python, ['-m', 'pytest', '-q', '--basetemp', resolve(temp, 'data')], resolve(root, 'backend'))
} else if (command === 'ui') {
  // The target must be a dedicated Vite test server; every API is intercepted.
  if (!process.env.UI_TEST_URL) throw new Error('Set UI_TEST_URL to an isolated loopback test server, not your live workspace.')
  const target = new URL(process.env.UI_TEST_URL)
  if (!['127.0.0.1', 'localhost', '[::1]'].includes(target.hostname) || target.port === '5173') throw new Error('Use a dedicated loopback test port, e.g. 5197.')
  run(process.execPath, ['tests/workspace-ui.mjs'], resolve(root, 'frontend'))
} else if (command === 'audit-python') {
  run(python, ['scripts/security/audit_python.py', '--allow-osv'])
} else if (command === 'integration') {
  run(python, ['scripts/integration_vectors.py'])
} else {
  throw new Error('Expected check, test, backend, ui or audit-python.')
}

import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import test from 'node:test';

test('account emails and auth identity use Documents Made Clear without changing session cookies', () => {
  const script = `
    import assert from 'node:assert/strict';
    const sent = [];
    globalThis.fetch = async (url, options) => {
      assert.equal(String(url), 'https://api.resend.com/emails');
      sent.push(JSON.parse(options.body));
      return new Response('{}', { status: 200 });
    };
    const { auth, pool } = await import('./src/auth.ts');
    try {
      assert.equal(auth.options.appName, 'Documents Made Clear');
      assert.equal(auth.options.advanced.cookiePrefix, 'nexus');
      const input = { user: { email: 'member@example.test' }, url: 'https://app.example.test/reset' };
      await auth.options.emailAndPassword.sendResetPassword(input);
      await auth.options.emailVerification.sendVerificationEmail(input);
      assert.deepEqual(sent.map(email => email.subject), [
        'Reset your Documents Made Clear password',
        'Verify your Documents Made Clear email',
      ]);
      for (const email of sent) {
        assert.equal(email.from, 'Documents Made Clear <test@example.test>');
        assert.match(email.html, /Documents Made Clear/);
      }
      console.log('BRAND_OK');
    } finally {
      await pool.end();
    }
  `;
  const result = spawnSync(process.execPath, ['--import', 'tsx', '--input-type=module', '-e', script], {
    cwd: process.cwd(),
    env: { ...process.env, APP_ENV: 'development', NODE_ENV: 'development',
      DATABASE_URL: 'postgresql://test:dummy@localhost/test',
      BETTER_AUTH_SECRET: 'test-only-brand-secret-'.repeat(3),
      REQUIRE_EMAIL_VERIFICATION: 'false', RESEND_API_KEY: 'test-only-placeholder',
      EMAIL_FROM: 'NEXUS <test@example.test>',
      APP_ORIGIN: 'https://app.example.test', BETTER_AUTH_URL: 'https://auth.example.test' },
    encoding: 'utf8',
  });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /BRAND_OK/);
});

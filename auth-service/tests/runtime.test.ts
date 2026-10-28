import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import test from 'node:test';
import { isProductionEnvironment } from '../src/runtime.js';

test('either production flag enables safeguards, even when flags disagree', () => {
  for (const env of [
    { APP_ENV: 'production', NODE_ENV: 'development' },
    { APP_ENV: 'development', NODE_ENV: 'production' },
    { APP_ENV: ' Production ' },
  ]) assert.equal(isProductionEnvironment(env), true);
  assert.equal(isProductionEnvironment({ APP_ENV: 'development', NODE_ENV: 'development' }), false);
});

for (const productionFlag of ['APP_ENV', 'NODE_ENV']) {
  test(`${productionFlag} production rejects disabled email verification`, () => {
    const result = spawnSync(process.execPath, ['--import', 'tsx', '-e', "import('./src/auth.ts')"], {
      cwd: process.cwd(),
      env: { ...process.env, APP_ENV: 'development', NODE_ENV: 'development',
        [productionFlag]: 'production', DATABASE_URL: 'postgresql://test:dummy@localhost/test',
        BETTER_AUTH_SECRET: 's'.repeat(40), REQUIRE_EMAIL_VERIFICATION: 'false' },
      encoding: 'utf8',
    });
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /REQUIRE_EMAIL_VERIFICATION=true is mandatory/);
  });

  test(`${productionFlag} alone enforces secure cookies with valid production settings`, () => {
    const result = spawnSync(process.execPath, ['--import', 'tsx', '-e',
      "import('./src/auth.ts').then(async ({auth,pool}) => { console.log('SECURE='+auth.options.advanced.defaultCookieAttributes.secure); await pool.end(); })"], {
      cwd: process.cwd(),
      env: { ...process.env, APP_ENV: 'development', NODE_ENV: 'development',
        [productionFlag]: 'production', DATABASE_URL: 'postgresql://test:dummy@localhost/test',
        BETTER_AUTH_SECRET: 's'.repeat(40), REQUIRE_EMAIL_VERIFICATION: 'true',
        RESEND_API_KEY: 'test-only-placeholder', EMAIL_FROM: 'test@nexus.test',
        APP_ORIGIN: 'https://app.nexus.test', BETTER_AUTH_URL: 'https://auth.nexus.test' },
      encoding: 'utf8',
    });
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /SECURE=true/);
  });
}

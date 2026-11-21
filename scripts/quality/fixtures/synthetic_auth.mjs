// Runs only inside an internal disposable test network. Never log cookies.
let input = '';
for await (const chunk of process.stdin) input += chunk;
const config = JSON.parse(input);
const { auth, pool } = await import('/app/src/auth.ts');
const { getMigrations } = await import('better-auth/db/migration');
const assert = (condition) => { if (!condition) throw new Error('Synthetic auth assertion failed'); };
const call = (path, method = 'GET', body, cookie) => auth.handler(new Request(
  process.env.BETTER_AUTH_URL + '/api/auth' + path,
  { method, headers: { origin: process.env.APP_ORIGIN, 'content-type': 'application/json', ...(cookie ? { cookie } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}) }
));
try {
  if (config.phase === 'create') {
    await (await getMigrations(auth.options)).runMigrations();
    const users = [];
    for (const email of ['alice@example.test', 'bob@example.test']) {
      const response = await call('/sign-up/email', 'POST', { name: 'Synthetic', email, password: config.password });
      assert(response.status === 200);
      const data = await response.json();
      const cookie = response.headers.getSetCookie().map(item => item.split(';', 1)[0]).join('; ');
      assert(cookie.includes('session_token=') && data.user?.id);
      users.push({ id: data.user.id, cookie });
    }
    assert(users[0].id !== users[1].id);
    const wrongPassword = await call('/sign-in/email', 'POST', { email: 'alice@example.test', password: 'Wrong-synthetic-password-42' });
    assert(wrongPassword.status === 401);
    console.log(JSON.stringify({ users }));
  } else if (config.phase === 'signout') {
    for (const user of config.users) assert((await call('/sign-out', 'POST', {}, user.cookie)).status === 200);
    console.log(JSON.stringify({ signed_out: true }));
  } else throw new Error('Unknown synthetic auth phase');
} finally { await pool.end(); }

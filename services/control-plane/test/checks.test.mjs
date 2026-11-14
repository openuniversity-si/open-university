// VAZÃO F37 (D-299): POST /v1/check-run under node --test. A real Ed25519 key is the app's (PKCS#8 PEM, as the origin
// CLI reads --signing-key); a fake fetch plays Origin's token exchange and check-runs endpoints and checks the app JWT
// against the key's public half. No network.
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { generateKeyPairSync, verify } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { MemoryStore, handle } from '../src/core.js';
import { APP_AUDIENCE, APP_JWT_TTL_S, ORIGIN_API, TOKENS, TOKEN_MARGIN_MS, checkRunRoute } from '../src/checks.js';

const BUDGET_S = String(JSON.parse(readFileSync(new URL('../../../config/registry/service/service.job_budget_s.json', import.meta.url), 'utf8')).default);
const PAIR = generateKeyPairSync('ed25519');
const PEM = PAIR.privateKey.export({ type: 'pkcs8', format: 'pem' });
const REPO = 'openuniversity-si/open-university';
const HEAD = 'a'.repeat(40);
const T0 = Date.parse('2026-11-03T19:00:00Z');
const ENV = { BUDGET_S, EVENTS_TOKEN: 'events', REPO, ORIGIN_APP_PRIVATE_KEY: PEM, ORIGIN_APP_ID: 'app_tower', ORIGIN_APP_INSTALLATION_ID: 'inst_1' };
const BODY = { repo: REPO, headSha: HEAD, checkSuite: { key: 'tower', name: 'Tower', externalId: 'tower/gate' },
  checkRun: { key: 'tower/gate', name: 'tower/gate', status: 'completed', conclusion: 'success', externalId: 'tower/gate' } };
const same = (left, right) => left === right;

function origin({ token = { token: 'oit_one', expiresAt: new Date(T0 + 900000).toISOString() }, tokenStatus = 200, runStatus = 200 } = {}) {
  const calls = [];
  const fetcher = async (url, init) => {
    calls.push({ url, init });
    if (url.endsWith('/access_tokens')) return new Response(JSON.stringify(token), { status: tokenStatus });
    return new Response(JSON.stringify({ outcome: 'created' }), { status: runStatus });
  };
  return { calls, fetcher };
}

function request(body = BODY, token = 'events', method = 'POST') {
  return new Request('https://control.test/v1/check-run', { method, headers: { authorization: `Bearer ${token}` },
    body: method === 'POST' ? JSON.stringify(body) : undefined });
}

function decoded(part) {
  return JSON.parse(Buffer.from(part, 'base64url').toString());
}

beforeEach(() => TOKENS.clear());

test('absent today: without the app settings the route answers 503 and names them, and calls nobody', async () => {
  for (const name of ['ORIGIN_APP_PRIVATE_KEY', 'ORIGIN_APP_ID', 'ORIGIN_APP_INSTALLATION_ID', 'EVENTS_TOKEN']) {
    const { calls, fetcher } = origin();
    const response = await checkRunRoute(request(), { ...ENV, [name]: undefined }, T0, fetcher, same);
    assert.equal(response.status, 503);
    assert.match((await response.json()).error, new RegExp(`not configured \\(.*${name}`));
    assert.equal(calls.length, 0);
  }
});

test('the events token is required and only POST is served', async () => {
  const { calls, fetcher } = origin();
  assert.equal((await checkRunRoute(request(BODY, 'wrong'), ENV, T0, fetcher, same)).status, 401);
  assert.equal((await checkRunRoute(request(BODY, 'events', 'GET'), ENV, T0, fetcher, same)).status, 405);
  assert.equal(calls.length, 0);
});

test('only the Worker\'s REPO and a full head sha are posted', async () => {
  const { calls, fetcher } = origin();
  assert.equal((await checkRunRoute(request({ ...BODY, repo: 'someone/else' }), ENV, T0, fetcher, same)).status, 400);
  assert.equal((await checkRunRoute(request({ ...BODY, headSha: 'abc' }), ENV, T0, fetcher, same)).status, 400);
  assert.equal((await checkRunRoute(request({ ...BODY, checkRun: null }), ENV, T0, fetcher, same)).status, 400);
  assert.equal(calls.length, 0);
});

test('the app JWT is EdDSA over the app key, iss the app, aud origin-apps, 300 s; the run goes with the oit_ token', async () => {
  const { calls, fetcher } = origin();
  const response = await checkRunRoute(request(), ENV, T0, fetcher, same);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { outcome: 'created' });
  const [exchange, post] = calls;
  assert.equal(exchange.url, `${ORIGIN_API}/app/installations/inst_1/access_tokens`);
  assert.equal(exchange.init.method, 'POST');
  const jwt = exchange.init.headers.authorization.slice('Bearer '.length);
  const [header, claims, signature] = jwt.split('.');
  assert.deepEqual(decoded(header), { alg: 'EdDSA', typ: 'JWT' });
  const now = Math.floor(T0 / 1000);
  assert.deepEqual(decoded(claims), { iss: 'app_tower', aud: APP_AUDIENCE, iat: now, exp: now + APP_JWT_TTL_S });
  assert.ok(verify(null, Buffer.from(`${header}.${claims}`), PAIR.publicKey, Buffer.from(signature, 'base64url')));
  assert.equal(post.url, `${ORIGIN_API}/repos/openuniversity-si/open-university/check-runs`);
  assert.equal(post.init.headers.authorization, 'Bearer oit_one');
  const { repo, ...origin_body } = BODY;
  assert.deepEqual(JSON.parse(post.init.body), origin_body);
});

test('the installation token is reused until a minute before it ends, then minted again', async () => {
  const { calls, fetcher } = origin();
  await checkRunRoute(request(), ENV, T0, fetcher, same);
  await checkRunRoute(request(), ENV, T0 + 60000, fetcher, same);
  assert.equal(calls.filter((call) => call.url.endsWith('/access_tokens')).length, 1);
  await checkRunRoute(request(), ENV, T0 + 900000 - TOKEN_MARGIN_MS, fetcher, same);
  assert.equal(calls.filter((call) => call.url.endsWith('/access_tokens')).length, 2);
});

test('Origin refusing the exchange or the run is a 502 with its status; a 401 run drops the cached token', async () => {
  let { fetcher } = origin({ tokenStatus: 403 });
  let response = await checkRunRoute(request(), ENV, T0, fetcher, same);
  assert.equal(response.status, 502);
  assert.match((await response.json()).error, /installation token answered 403/);
  ({ fetcher } = origin({ runStatus: 401 }));
  response = await checkRunRoute(request(), ENV, T0, fetcher, same);
  assert.equal(response.status, 502);
  assert.match((await response.json()).error, /check-runs answered 401/);
  assert.equal(TOKENS.size, 0);
});

test('a key that is not an Ed25519 PKCS#8 PEM is named, never printed', async () => {
  const { calls, fetcher } = origin();
  const response = await checkRunRoute(request(), { ...ENV, ORIGIN_APP_PRIVATE_KEY: 'not a key' }, T0, fetcher, same);
  assert.equal(response.status, 502);
  const { error } = await response.json();
  assert.match(error, /ORIGIN_APP_PRIVATE_KEY is not an Ed25519 PKCS#8 PEM key/);
  assert.doesNotMatch(error, /not a key/);
  assert.equal(calls.length, 0);
});

test('the Worker routes /v1/check-run (core.handle), its fetch injectable as ORIGIN_FETCH', async () => {
  const { calls, fetcher } = origin();
  const response = await handle(request(), { ...ENV, ORIGIN_FETCH: fetcher }, new MemoryStore(), T0);
  assert.equal(response.status, 200);
  assert.equal(calls.length, 2);
  const off = await handle(request(), { BUDGET_S, EVENTS_TOKEN: 'events' }, new MemoryStore(), T0);
  assert.equal(off.status, 503);
});

// VAZÃO F35: the engine's config overrides as one versioned Durable Object key (GET/POST /v1/config). A read is one
// storage get and never a list (the event-log window it replaces listed 2,000+ rows per read, I-5102f4e9); a write is
// compare-and-set on `version`; the events token guards both. The storage is a fake of the Durable Object's that counts
// the rows each operation touches.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { CONFIG_PREFIX, MemoryStore, handle } from '../src/core.js';

const BUDGET_S = String(JSON.parse(readFileSync(new URL('../../../config/registry/service/service.job_budget_s.json', import.meta.url), 'utf8')).default);
const ENV = { BUDGET_S, EVENTS_TOKEN: 'events', ADMIN_TOKEN: 'admin', RUNNER_TOKEN: 'runner', GITHUB_WEBHOOK_SECRET: 's' };
const T0 = Date.parse('2026-11-03T21:00:00Z');
const REPO = 'openuniversity-si/open-university';

class Storage {
  constructor() { this.held = new Map(); this.rows = { get: 0, list: 0, put: 0 }; }
  async get(key) { this.rows.get += Array.isArray(key) ? key.length : 1; return structuredClone(this.held.get(key)); }
  async put(entries) { for (const [key, value] of Object.entries(entries)) { this.rows.put += 1; this.held.set(key, structuredClone(value)); } }
  async delete(keys) { for (const key of keys) this.held.delete(key); }
  async list({ prefix = '' } = {}) {
    const found = [...this.held.keys()].filter((key) => key.startsWith(prefix)).sort();
    this.rows.list += found.length;
    return new Map(found.map((key) => [key, structuredClone(this.held.get(key))]));
  }
}

async function call(storage, method, { query = `?repo=${REPO}`, token = 'events', body, env = ENV, store = new MemoryStore() } = {}) {
  const request = new Request(`https://control/v1/config${method === 'GET' ? query : ''}`, {
    method, headers: token ? { authorization: `Bearer ${token}` } : {}, body: body === undefined ? undefined : JSON.stringify(body),
  });
  const response = await handle(request, env, store, T0, storage);
  return { status: response.status, body: await response.json() };
}

const write = (storage, version, overrides, through = 'e1', repo = REPO) =>
  call(storage, 'POST', { body: { repo, version, overrides, through } });

test('an absent snapshot reads as version 0 with no overrides, for one row and no list', async () => {
  const storage = new Storage();
  const read = await call(storage, 'GET');
  assert.equal(read.status, 200);
  assert.deepEqual(read.body, { version: 0, overrides: {}, through: null, at: null });
  assert.deepEqual(storage.rows, { get: 1, list: 0, put: 0 });
});

test('a write makes the next version and a read returns it from one storage get, whatever the event log holds', async () => {
  const storage = new Storage();
  for (let seq = 1; seq <= 2500; seq += 1) storage.held.set(`ev:${String(seq).padStart(12, '0')}`, { seq, events: [] });
  const written = await write(storage, 0, { 'train.enabled': false }, 'e1');
  assert.equal(written.status, 201);
  assert.deepEqual(written.body, { version: 1, overrides: { 'train.enabled': false }, through: 'e1', at: '2026-11-03T21:00:00.000Z' });
  storage.rows = { get: 0, list: 0, put: 0 };
  const read = await call(storage, 'GET');
  assert.deepEqual(read.body, written.body);
  assert.deepEqual(storage.rows, { get: 1, list: 0, put: 0 }, 'one row read, the 2,500 log records untouched');
  assert.ok(storage.held.has(`${CONFIG_PREFIX}${REPO}`));
});

test('a stale version is refused with 409 and the current snapshot, and nothing is written', async () => {
  const storage = new Storage();
  await write(storage, 0, { 'train.enabled': false }, 'e1');
  await write(storage, 1, { 'train.enabled': true }, 'e2');
  storage.rows = { get: 0, list: 0, put: 0 };
  const stale = await write(storage, 1, { 'gate.x': 3 }, 'e3');
  assert.equal(stale.status, 409);
  assert.equal(stale.body.current.version, 2);
  assert.deepEqual(stale.body.current.overrides, { 'train.enabled': true });
  assert.deepEqual(storage.rows, { get: 1, list: 0, put: 0 });
  const retried = await write(storage, stale.body.current.version, { 'train.enabled': true, 'gate.x': 3 }, 'e3');
  assert.equal(retried.status, 201);
  assert.equal(retried.body.version, 3);
});

test('two writers from the same version: exactly one wins, the other gets 409', async () => {
  const storage = new Storage();
  const [first, second] = await Promise.all([write(storage, 0, { a: 1 }, 'x'), write(storage, 0, { b: 1 }, 'y')]);
  assert.deepEqual([first.status, second.status].sort(), [201, 409]);
  assert.equal((await call(storage, 'GET')).body.version, 1);
});

test('each repository has its own key', async () => {
  const storage = new Storage();
  await write(storage, 0, { a: 1 }, 'x', 'other/repo');
  assert.equal((await call(storage, 'GET')).body.version, 0);
  assert.equal((await call(storage, 'GET', { query: '?repo=other/repo' })).body.version, 1);
});

test('no token, a wrong token, a bad body or a missing repo is refused; without the secret the route is off', async () => {
  const storage = new Storage();
  assert.equal((await call(storage, 'GET', { token: null })).status, 401);
  assert.equal((await call(storage, 'GET', { token: 'wrong' })).status, 401);
  assert.equal((await call(storage, 'POST', { token: 'wrong', body: { repo: REPO, version: 0, overrides: {}, through: null } })).status, 401);
  assert.equal((await call(storage, 'GET', { query: '' })).status, 400);
  for (const body of [{ repo: REPO, version: -1, overrides: {}, through: null }, { repo: REPO, version: 0, overrides: [], through: null },
    { repo: REPO, version: 0.5, overrides: {}, through: null }, { version: 0, overrides: {}, through: null }, { repo: REPO, version: 0, overrides: {} }]) {
    assert.equal((await call(storage, 'POST', { body })).status, 400, JSON.stringify(body));
  }
  assert.equal((await call(storage, 'POST', { body: { repo: REPO, version: 0, overrides: { big: 'x'.repeat(131072) }, through: null } })).status, 413);
  assert.equal((await call(storage, 'PUT', { body: {} })).status, 405);
  assert.equal((await call(storage, 'GET', { env: { ...ENV, EVENTS_TOKEN: '' } })).status, 503);
  assert.equal(storage.held.size, 0);
});

test('a read never dirties the store dump; the snapshot key is not part of it', async () => {
  const storage = new Storage();
  const store = new MemoryStore();
  await call(storage, 'GET', { store });
  assert.equal(store.dirty, false, 'a config read writes nothing back to the Durable Object');
  await write(storage, 0, { a: 1 });
  assert.ok(!Object.keys(new MemoryStore().dump()).some((key) => key.startsWith(CONFIG_PREFIX)));
});

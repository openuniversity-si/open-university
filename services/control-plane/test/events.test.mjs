// CANALE7 (CONTROL-CHANNEL): the engine's event log of the control plane under node --test: append and read per channel,
// paged reads by sequence, the windowed tail, retention, the token, and the route off without its secret. The storage is a
// fake of the Durable Object's (put of an object, list by prefix/start/end/reverse/limit, delete of keys).
//
// CANALE8 (the journal as a trigger): an envelope the journal holds makes the same job the forge-events comment makes
// (jobsOfEnvelopes, one rule for both doors), so pr.ready wakes the train with no comment on the PR; a type nobody names
// is only written down; an event_id already handled makes nothing a second time.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { EVENT_PREFIX, EventLog, MARKER, MemoryStore, handle, jobsOf, settings } from '../src/core.js';

// BUDGET_S as the deploy sends it: service.job_budget_s of the registry (scripts/lib/service_deploy.py), the one budget.
const BUDGET_S = String(JSON.parse(readFileSync(new URL('../../../config/registry/service/service.job_budget_s.json', import.meta.url), 'utf8')).default);
const ENV = { BUDGET_S, EVENTS_TOKEN: 'events', ADMIN_TOKEN: 'admin', RUNNER_TOKEN: 'runner', GITHUB_WEBHOOK_SECRET: 's' };
const T0 = Date.parse('2026-11-01T19:00:00Z');
const REPO = 'openuniversity-si/open-university';

class Storage {
  constructor() { this.held = new Map(); }
  async get(key) { return this.held.get(key); }
  async put(entries) { for (const [key, value] of Object.entries(entries)) this.held.set(key, structuredClone(value)); }
  async delete(keys) { for (const key of keys) this.held.delete(key); }
  async list({ prefix = '', start = '', end = null, reverse = false, limit = Infinity } = {}) {
    let keys = [...this.held.keys()].filter((key) => key.startsWith(prefix) && key >= start && (end === null || key < end)).sort();
    if (reverse) keys.reverse();
    return new Map(keys.slice(0, limit).map((key) => [key, structuredClone(this.held.get(key))]));
  }
}

function request(method, query, { token = 'events', body } = {}) {
  return new Request(`https://control/v1/events${query}`, {
    method, headers: token ? { authorization: `Bearer ${token}` } : {}, body: body === undefined ? undefined : JSON.stringify(body),
  });
}

async function call(storage, method, query, options, env = ENV) {
  const response = await handle(request(method, query, options), env, new MemoryStore(), T0, storage);
  return { status: response.status, body: await response.json() };
}

const envelope = (id, type = 'train.queue.empty') => ({ event_id: id, type, payload: {} });

test('append then read per channel, in order', async () => {
  const storage = new Storage();
  await call(storage, 'POST', '', { body: { channel: { repo: REPO, pr: null }, events: [envelope('a')] } });
  await call(storage, 'POST', '', { body: { channel: { repo: REPO, pr: 7 }, events: [envelope('b', 'pr.ready')] } });
  await call(storage, 'POST', '', { body: { channel: { repo: REPO, pr: null }, events: [envelope('c'), envelope('d')] } });
  const repository = await call(storage, 'GET', `?repo=${REPO}`);
  assert.deepEqual(repository.body.records.flatMap((record) => record.events.map((item) => item.event_id)), ['a', 'c', 'd']);
  const pull = await call(storage, 'GET', `?repo=${REPO}&pr=7`);
  assert.deepEqual(pull.body.records.flatMap((record) => record.events.map((item) => item.event_id)), ['b']);
});

test('a read from a sequence returns only what came after it, and pages', async () => {
  const storage = new Storage();
  const env = { ...ENV, EVENTS_PAGE: '2' };
  for (const id of ['a', 'b', 'c']) await call(storage, 'POST', '', { body: { channel: { repo: REPO, pr: null }, events: [envelope(id)] } }, env);
  const first = await call(storage, 'GET', `?repo=${REPO}`, {}, env);
  assert.equal(first.body.more, true);
  const second = await call(storage, 'GET', `?repo=${REPO}&since=${first.body.next}`, {}, env);
  assert.deepEqual(second.body.records.map((record) => record.events[0].event_id), ['c']);
  assert.equal(second.body.more, false);
});

test('the tail is the newest records, oldest first, and says when it is partial', async () => {
  const storage = new Storage();
  for (const id of ['a', 'b', 'c']) await call(storage, 'POST', '', { body: { channel: { repo: REPO, pr: null }, events: [envelope(id)] } });
  const tail = await call(storage, 'GET', `?repo=${REPO}&tail=2`);
  assert.deepEqual(tail.body.records.map((record) => record.events[0].event_id), ['b', 'c']);
  assert.equal(tail.body.complete, false);
});

test('a window no deeper than the one held is answered from memory, appends included (F28)', async () => {
  const storage = new Storage();
  for (const id of ['a', 'b', 'c']) await call(storage, 'POST', '', { body: { channel: { repo: REPO, pr: null }, events: [envelope(id)] } });
  let listed = 0;
  const list = storage.list.bind(storage);
  storage.list = async (options) => { if (options.reverse) listed += 1; return list(options); };
  const first = await call(storage, 'GET', `?repo=${REPO}&tail=3`);
  assert.deepEqual(first.body.records.map((record) => record.events[0].event_id), ['a', 'b', 'c']);
  assert.equal(first.body.complete, false);  // three records and a window of three: older ones may exist
  await call(storage, 'POST', '', { body: { channel: { repo: REPO, pr: null }, events: [envelope('d')] } });
  const second = await call(storage, 'GET', `?repo=${REPO}&tail=2`);
  assert.deepEqual(second.body.records.map((record) => record.events[0].event_id), ['c', 'd']);
  assert.equal(second.body.complete, false);
  assert.equal(listed, 1);  // only the first window read the storage
  const deeper = await call(storage, 'GET', `?repo=${REPO}&tail=10`);
  assert.deepEqual(deeper.body.records.map((record) => record.events[0].event_id), ['a', 'b', 'c', 'd']);
  assert.equal(deeper.body.complete, true);  // the whole log fits a deeper window
  assert.equal(listed, 2);
  const again = await call(storage, 'GET', `?repo=${REPO}&tail=4`);
  assert.equal(again.body.complete, false);  // as a listed window of 4 over 4 records says: older ones may exist
  assert.equal(listed, 2);
});

test('records past keepEvents are deleted, the newest kept', async () => {
  const storage = new Storage();
  const env = { ...ENV, KEEP_EVENTS: '2' };
  for (const id of ['a', 'b', 'c']) await call(storage, 'POST', '', { body: { channel: { repo: REPO, pr: null }, events: [envelope(id)] } }, env);
  const keys = [...storage.held.keys()].filter((key) => key.startsWith(EVENT_PREFIX));
  assert.deepEqual(keys, [EventLog.key(2), EventLog.key(3)]);
});

test('no token, a wrong token or a bad body is refused; without the secret the route is off', async () => {
  const storage = new Storage();
  assert.equal((await call(storage, 'GET', `?repo=${REPO}`, { token: null })).status, 401);
  assert.equal((await call(storage, 'GET', `?repo=${REPO}`, { token: 'runner' })).status, 401);
  assert.equal((await call(storage, 'POST', '', { body: { channel: { repo: REPO }, events: [] } })).status, 400);
  assert.equal((await call(storage, 'GET', `?repo=${REPO}`, {}, { ...ENV, EVENTS_TOKEN: '' })).status, 503);
  assert.equal(storage.held.size, 0);
});

test('the store dump never holds the event log', async () => {
  const storage = new Storage();
  const store = new MemoryStore();
  await handle(request('POST', '', { body: { channel: { repo: REPO, pr: null }, events: [envelope('a')] } }), ENV, store, T0, storage);
  assert.ok(!JSON.stringify(store.dump()).includes('"event_id"'));
  assert.equal(settings(ENV).keepEvents > 0, true);
});

// ----------------------------------------------------------------------------------------------------------------
// CANALE8: the journal is a trigger. The store is the same across a test's calls here (the Durable Object's one), so
// an event_id handled once stays handled.
// ----------------------------------------------------------------------------------------------------------------

const CFG = settings(ENV);
const HEAD = 'a'.repeat(40);

async function append(storage, store, events, { pr = null, now = T0, repo = REPO } = {}) {
  const response = await handle(request('POST', '', { body: { channel: { repo, pr }, events } }), ENV, store, now, storage);
  return { status: response.status, body: await response.json() };
}

function forgeComment(envelopes) {
  // The body forge_github.GitHubAdapter._render writes: the marker, a headline, then the envelopes as JSON lines.
  const lines = envelopes.map((item) => JSON.stringify(item)).join('\n');
  return `${MARKER}\nforge_events: x\n\n\`\`\`jsonl\n${lines}\n\`\`\`\n`;
}

test('a pr.ready on the journal is the train job the forge-events comment makes, with the same id and reason', async () => {
  const storage = new Storage();
  const store = new MemoryStore();
  const ready = { event_id: 'e1'.repeat(32), type: 'pr.ready', occurred_at: '2026-11-01T19:00:00Z', payload: { pr: 7, sha: HEAD } };
  const sent = await append(storage, store, [ready], { pr: 7 });
  assert.equal(sent.status, 201);
  assert.deepEqual(sent.body.queued, [`train:7#${HEAD}`]);  // seq is still the first field ControlAdapter reads
  assert.equal(typeof sent.body.seq, 'number');
  const comment = jobsOf('issue_comment', { action: 'created', comment: { author_association: 'OWNER', body: forgeComment([ready]) } }, CFG, T0);
  assert.deepEqual(comment.jobs.map((item) => item.id), sent.body.queued);
  assert.equal(comment.jobs[0].reason, store.jobs[0].reason);
  assert.match(store.jobs[0].reason, /^pr\.ready e1e1e1e1/);
  assert.equal(store.jobs[0].state, 'queued');
  assert.equal(store.facts.ready[`7#${HEAD}`], '2026-11-01T19:00:00Z');
});

test('a type nobody names is written down and asks for nothing; pr.merged is a fact, not work', async () => {
  const storage = new Storage();
  const store = new MemoryStore();
  const ignored = await append(storage, store, [{ event_id: 'quiet'.padEnd(64, '0'), type: 'train.queue.empty', payload: {} }]);
  assert.deepEqual(ignored.body.queued, []);
  assert.equal(store.jobs.length, 0);
  const merged = { event_id: 'm'.repeat(64), type: 'pr.merged', occurred_at: '2026-11-01T19:01:00Z',
    payload: { pr: 7, sha: HEAD, batch_id: 'v-1' } };
  const settled = await append(storage, store, [merged], { pr: 7 });
  assert.deepEqual(settled.body.queued, []);
  assert.equal(store.jobs.length, 0);
  assert.equal(store.facts.merges[0].batch_id, 'v-1');
  const written = await call(storage, 'GET', `?repo=${REPO}&pr=7`);
  assert.deepEqual(written.body.records.flatMap((record) => record.events.map((item) => item.event_id)), [merged.event_id]);
});

test('the same event_id sent twice is one train job, and the journal still records both arrivals', async () => {
  const storage = new Storage();
  const store = new MemoryStore();
  const ready = { event_id: 'f'.repeat(64), type: 'pr.ready', occurred_at: '2026-11-01T19:00:00Z', payload: { pr: 7, sha: HEAD } };
  const first = await append(storage, store, [ready], { pr: 7 });
  const again = await append(storage, store, [ready], { pr: 7, now: T0 + 1000 });
  assert.deepEqual(first.body.queued, [`train:7#${HEAD}`]);
  assert.deepEqual(again.body.queued, []);
  assert.equal(store.jobs.length, 1);
  assert.equal(again.body.seq, first.body.seq + 1);
  const written = await call(storage, 'GET', `?repo=${REPO}&pr=7`);
  assert.equal(written.body.records.flatMap((record) => record.events).length, 2);
});

test('two pr.ready of different heads are two train jobs, the older superseded (CONTROL-STORE), and a repeat is caught', async () => {
  const storage = new Storage();
  const store = new MemoryStore();
  const one = { event_id: '1'.repeat(64), type: 'pr.ready', payload: { pr: 7, sha: HEAD } };
  const two = { event_id: '2'.repeat(64), type: 'pr.ready', payload: { pr: 7, sha: 'b'.repeat(40) } };
  const sent = await append(storage, store, [one, two, one], { pr: 7 });
  assert.deepEqual(sent.body.queued, [`train:7#${HEAD}`, `train:7#${'b'.repeat(40)}`]);
  // Supersession: the newer head replaces the older queued train job of the same PR.
  assert.deepEqual(store.jobs.map((item) => item.id), [`train:7#${'b'.repeat(40)}`]);
  assert.equal(store.counters.jobs_superseded_total, 1);
});

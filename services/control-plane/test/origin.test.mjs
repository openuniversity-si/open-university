// CANALE8 (ORIGIN-WEBHOOK): Origin's signed delivery under node --test. A real Ed25519 keypair signs the body exactly as
// Origin does (v1ed,<base64> over the lowercase hex SHA-256 of id.timestamp.body), the key ring is handed the matching
// public JWK instead of fetching /v1/origin/keys, and the delivery must become the same jobs and facts the GitHub route
// makes -- plus the port's envelopes on the engine's journal (/v1/events), on the repository channel and the PR's.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { EventLog, MemoryStore, ORIGIN_PRODUCER, handle, originEnvelope, premisesOf, settings, sha256Hex } from '../src/core.js';
import { KeyRing } from '../src/core.js';

// BUDGET_S as the deploy sends it: service.job_budget_s of the registry (scripts/lib/service_deploy.py), the one budget.
const BUDGET_S = String(JSON.parse(readFileSync(new URL('../../../config/registry/service/service.job_budget_s.json', import.meta.url), 'utf8')).default);
const ENV = { BUDGET_S, GITHUB_WEBHOOK_SECRET: 's', ADMIN_TOKEN: 'admin', RUNNER_TOKEN: 'runner', EVENTS_TOKEN: 'events' };
const CFG = settings(ENV);
const T0 = Date.parse('2026-11-01T19:00:00Z');
const HEAD = 'a'.repeat(40);
const BASE = 'b'.repeat(40);
const MERGE = 'c'.repeat(40);
const REPO = 'openuniversity-si/open-university';

// One keypair for the suite, the way Origin publishes one: an Ed25519 public JWK with only x.
const PAIR = await crypto.subtle.generateKey({ name: 'Ed25519' }, true, ['sign', 'verify']);
const JWK = await crypto.subtle.exportKey('jwk', PAIR.publicKey);
const RING = new KeyRing(async () => [{ kty: 'OKP', crv: 'Ed25519', x: JWK.x }]);

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

async function signed(body, { id = `whd_${Math.random().toString(36).slice(2)}`, at = T0 / 1000, key = PAIR.privateKey } = {}) {
  // The digest Origin signs is the hex SHA-256 of the three headers and the raw body, and the bytes signed are that hex.
  const digest = await sha256Hex(`${id}.${at}.${body}`);
  const bytes = new Uint8Array(await crypto.subtle.sign({ name: 'Ed25519' }, key, new TextEncoder().encode(digest)));
  const signature = `v1ed,${Buffer.from(bytes).toString('base64')}`;
  return { 'webhook-id': id, 'webhook-timestamp': String(at), 'webhook-signature': signature };
}

function delivery(type, payload, { event = {}, time = '2026-11-01T19:00:00Z' } = {}) {
  return JSON.stringify({ deliveryId: 'whd_x', appId: 'app_x', installationId: 'i_x',
    event: { id: event.id || 'evt_x', type, eventTime: time, payload } });
}

function pull(extra = {}, { number = 7, body = 'Premises: P-12, P-34\n' } = {}) {
  return { pullRequest: { id: 1, number: String(number), state: 'open', draft: false, merged: false, title: 't', body,
    head: { ref: 'mod/x', sha: HEAD }, base: { ref: CFG.baseBranch, sha: BASE }, mergeCommitSha: null, ...extra },
  repository: { id: 2, name: 'open-university', owner: { slug: 'openuniversity-si', id: 3, type: 'namespace' } } };
}

async function send(store, type, payload, { storage = null, headers, now = T0, body } = {}) {
  const raw = body || delivery(type, payload);
  const request = new Request('https://control/webhook/origin', { method: 'POST', body: raw,
    headers: { 'content-type': 'application/json', 'webhook-event-type': type, ...(headers || await signed(raw)) } });
  const env = { ...ENV, ORIGIN_RING: RING };
  const response = await handle(request, env, store, now, storage);
  return { status: response.status, body: await response.json() };
}

const journal = async (storage, pr = null) => {
  const found = await new EventLog(storage, CFG).read({ repo: REPO, pr }, { tail: 100 });
  return found.records.flatMap((record) => record.events);
};

test('a signed delivery is accepted and a gate job of the head is queued', async () => {
  const store = new MemoryStore();
  const sent = await send(store, 'pull_request.head_ref.pushed', pull());
  assert.equal(sent.status, 202);
  assert.deepEqual(sent.body.queued, [`gate:7#${HEAD}`]);
  assert.equal(store.jobs[0].kind, 'gate');
  assert.equal(store.jobs[0].repo, REPO);  // the repository the delivery names, not the GitHub one
});

test('a forged signature is refused, counted, and makes no job', async () => {
  const store = new MemoryStore();
  const body = delivery('pull_request.head_ref.pushed', pull());
  const other = await crypto.subtle.generateKey({ name: 'Ed25519' }, true, ['sign', 'verify']);
  const forged = await signed(body, { key: other.privateKey });
  const sent = await send(store, 'pull_request.head_ref.pushed', null, { body, headers: forged });
  assert.equal(sent.status, 401);
  assert.equal(store.jobs.length, 0);
  assert.equal(store.counters.webhook_refused_total, 1);
  const tampered = await signed(body);
  const sent2 = await send(store, 'pull_request.head_ref.pushed', null, { body: body.replace('"t"', '"u"'), headers: tampered });
  assert.equal(sent2.status, 401);
});

test('a delivery stamped outside five minutes, or without its headers, is refused', async () => {
  const store = new MemoryStore();
  const body = delivery('pull_request.head_ref.pushed', pull());
  const old = await signed(body, { at: T0 / 1000 - 400 });
  assert.equal((await send(store, 'x', null, { body, headers: old })).status, 401);
  const ahead = await signed(body, { at: T0 / 1000 + 400 });
  assert.equal((await send(store, 'x', null, { body, headers: ahead })).status, 401);
  assert.equal((await send(store, 'x', null, { body, headers: {} })).status, 401);
  const noSignature = { ...(await signed(body)) };
  delete noSignature['webhook-signature'];
  assert.equal((await send(store, 'x', null, { body, headers: noSignature })).status, 401);
  assert.equal(store.jobs.length, 0);
});

test('a redelivery of the same webhook-id is handled once', async () => {
  const store = new MemoryStore();
  const body = delivery('pull_request.head_ref.pushed', pull());
  const headers = await signed(body, { id: 'whd_same' });
  assert.equal((await send(store, 'pull_request.head_ref.pushed', null, { body, headers })).status, 202);
  const again = await send(store, 'pull_request.head_ref.pushed', null, { body, headers });
  assert.deepEqual(again.body, { duplicate: true });
  assert.equal(store.jobs.length, 1);
  assert.equal(store.counters.webhook_duplicate_total, 1);
});

test('a PR opened records pr.opened on the repository and the PR channel and queues its gate', async () => {
  const store = new MemoryStore();
  const storage = new Storage();
  const sent = await send(store, 'pull_request.created', pull(), { storage });
  assert.equal(sent.body.recorded, 2);
  assert.deepEqual(sent.body.queued, [`gate:7#${HEAD}`]);
  const repository = await journal(storage);
  const change = await journal(storage, 7);
  assert.equal(repository.length, 1);
  assert.deepEqual(change, repository);
  const [envelope] = repository;
  assert.equal(envelope.type, 'pr.opened');
  assert.equal(envelope.version, 1);
  assert.equal(envelope.producer, ORIGIN_PRODUCER);
  assert.equal(envelope.correlation_id, 'evt_x');
  assert.deepEqual(envelope.payload, { repo: REPO, pr: 7, sha: HEAD, unit: null, premises: ['P-12', 'P-34'],
    base_sha: BASE, lane_id: null, units: [] });
  assert.equal(envelope.event_id, await sha256Hex(JSON.stringify([ORIGIN_PRODUCER, 'pr.opened', [REPO, 7, HEAD]])));
});

test('a push to the head records pr.pushed, and a merged PR records the merge and pr.merged', async () => {
  const storage = new Storage();
  const store = new MemoryStore();
  await send(store, 'pull_request.head_ref.pushed', pull(), { storage });
  assert.deepEqual((await journal(storage)).map((item) => item.type), ['pr.pushed']);

  const merged = pull({ state: 'closed', merged: true, mergeCommitSha: MERGE });
  const sent = await send(store, 'pull_request.merged', merged, { storage });
  assert.deepEqual(sent.body.queued, []);
  const types = (await journal(storage)).map((item) => item.type);
  assert.deepEqual(types, ['pr.pushed', 'pr.merged']);
  const merge = (await journal(storage))[1];
  assert.equal(merge.payload.merge_sha, MERGE);
  assert.equal(merge.payload.batch_id, null);
  assert.equal(merge.event_id, await sha256Hex(JSON.stringify([ORIGIN_PRODUCER, 'pr.merged', [REPO, 7, HEAD, MERGE]])));
  assert.equal(store.facts.merges.length, 1);
  assert.equal(store.facts.merges[0].pr, 7);
});

test('a push to the base is a sweep and a push to the wake ref is the train job it carries', async () => {
  const store = new MemoryStore();
  const push = (ref, after, message = 'm') => ({ repository: { name: 'open-university', owner: { slug: 'openuniversity-si' } },
    refUpdates: [{ ref, before: '0'.repeat(40), after, created: false, deleted: false,
      headCommit: { sha: after, message } }], pushedAt: '2026-11-01T19:00:00Z' });
  const base = await send(store, 'repository.pushed', push(`refs/heads/${CFG.baseBranch}`, BASE));
  assert.deepEqual(store.jobs.map((item) => item.kind), ['deploy', 'sweep']);
  assert.equal(base.body.recorded, 1);  // the base's own ref move is journaled (ref.updated); the sweep is the job
  const wake = await send(store, 'repository.pushed',
    push(`refs/heads/${CFG.wakeRef}`, MERGE, JSON.stringify({ pr: 9, sha: BASE, event_id: 'e2' })));
  assert.deepEqual(wake.body.queued, [`train:9#${BASE}`]);
  const gone = await send(store, 'repository.pushed', { repository: push('x', BASE).repository,
    refUpdates: [{ ref: `refs/heads/${CFG.baseBranch}`, after: BASE, deleted: true }] });
  assert.deepEqual(gone.body.queued, []);
});

test('another base, a draft with drafts off, or a closed PR makes no job but is still recorded', async () => {
  const store = new MemoryStore();
  const storage = new Storage();
  assert.deepEqual((await send(store, 'pull_request.head_ref.pushed', pull({ base: { ref: 'main', sha: BASE } }), { storage })).body.queued, []);
  const noDrafts = new KeyRing(async () => [{ kty: 'OKP', crv: 'Ed25519', x: JWK.x }]);
  const raw = delivery('pull_request.created', pull({ draft: true }));
  const request = new Request('https://control/webhook/origin', { method: 'POST', body: raw,
    headers: { 'webhook-event-type': 'pull_request.created', ...(await signed(raw)) } });
  const closed = await handle(request, { ...ENV, ORIGIN_RING: noDrafts, GATE_DRAFTS: 'false' }, store, T0, storage);
  assert.equal(closed.status, 202);
  assert.deepEqual((await closed.json()).queued, []);
  const types = (await journal(storage)).map((item) => item.type);
  assert.deepEqual(types, ['pr.pushed', 'pr.opened']);  // recorded either way: the journal is not the gate's
});

test('a comment or a check run is not the flow\'s business: accepted, quiet, nothing recorded', async () => {
  const store = new MemoryStore();
  const storage = new Storage();
  // A well-formed pull request sits on the payload, the way Origin sends one: the type is what keeps it quiet.
  const sent = await send(store, 'pull_request.comment.created', { ...pull(), comment: { id: 'c', body: 'hi' } }, { storage });
  assert.equal(sent.status, 202);
  assert.deepEqual(sent.body, { queued: [], recorded: 0 });
  const check = await send(store, 'check_run.completed', { ...pull(), checkRun: { id: 'r', status: 'completed' } }, { storage });
  assert.equal(check.status, 202);
  assert.deepEqual(check.body, { queued: [], recorded: 0 });
  assert.equal(storage.held.size, 0);
});

test('without storage the job still queues and the loss of the journal is logged, not hidden', async () => {
  const store = new MemoryStore();
  const sent = await send(store, 'pull_request.created', pull());
  assert.deepEqual(sent.body, { queued: [`gate:7#${HEAD}`], recorded: 2 });
  assert.ok(store.logLines.some((line) => line.kind === 'origin_journal_lost'));
});

test('two deliveries that arrive while the keys are still loading share that load and both verify', async () => {
  let calls = 0;
  let entered;
  const loading = new Promise((resolve) => { entered = resolve; });
  let release;
  const hold = new Promise((resolve) => { release = resolve; });
  const ring = new KeyRing(async () => {
    calls += 1;
    entered();
    await hold;
    return [{ kty: 'OKP', crv: 'Ed25519', x: JWK.x }];
  });
  let inside = 0;
  let secondInside;
  const secondWaiting = new Promise((resolve) => { secondInside = resolve; });
  const verify = ring.verifies.bind(ring);
  ring.verifies = (signature, digest, now) => {
    const result = verify(signature, digest, now);
    if (++inside === 2) secondInside();
    return result;
  };
  const store = new MemoryStore();
  const body = delivery('pull_request.head_ref.pushed', pull());
  const once = async (id) => {
    const request = new Request('https://control/webhook/origin', { method: 'POST', body, headers: {
      'content-type': 'application/json', 'webhook-event-type': 'pull_request.head_ref.pushed', ...(await signed(body, { id })),
    } });
    const response = await handle(request, { ...ENV, ORIGIN_RING: ring }, store, T0, null);
    return response.status;
  };
  const first = once('whd_cold_a');
  await loading;
  let secondStatus;
  const second = once('whd_cold_b').then((status) => { secondStatus = status; return status; });
  await secondWaiting;
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(secondStatus, undefined); // still parked on the in-flight load, not refused
  release();
  assert.deepEqual(await Promise.all([first, second]), [202, 202]);
  assert.equal(calls, 1);
  assert.equal(store.jobs.length, 1);
});

test('the envelope is the port\'s: the natural key of the type, the premises of the body, RFC 3339 time', async () => {
  const envelope = await originEnvelope('pr.pushed', { repo: REPO, pr: 7, sha: HEAD, unit: null, premises: [] },
    { correlationId: 'evt_1', occurredAt: '2026-11-01T19:00:00.000Z' });
  assert.deepEqual(Object.keys(envelope).sort(), ['correlation_id', 'event_id', 'occurred_at', 'payload', 'producer', 'type', 'version']);
  assert.equal(envelope.event_id, await sha256Hex(JSON.stringify([ORIGIN_PRODUCER, 'pr.pushed', [REPO, 7, HEAD]])));
  assert.deepEqual(premisesOf('body\nPremises: P-01, P-02, P-01\nmore'), ['P-01', 'P-02']);
  assert.deepEqual(premisesOf('no premises'), []);
  await assert.rejects(originEnvelope('gate.passed', {}, { correlationId: 'x', occurredAt: 'now' }), /no natural key/);
});

const REF_PUSH = (refUpdates, pushedAt = '2026-11-01T19:00:00Z') => ({
  repository: { name: 'open-university', owner: { slug: 'openuniversity-si' } }, pushedAt, refUpdates });
const refRecords = async (storage) => (await journal(storage)).filter((item) => item.type === 'ref.updated');

test('a push journals each ref move as ref.updated on the repository channel, with its created, deleted and forced flags', async () => {
  const store = new MemoryStore();
  const storage = new Storage();
  await send(store, 'repository.pushed', REF_PUSH([
    { ref: 'refs/heads/mod/x', before: BASE, after: HEAD, created: false, deleted: false, forced: true, headCommit: { sha: HEAD, message: 'm' } },
    { ref: 'refs/heads/new', before: '0'.repeat(40), after: MERGE, created: true, deleted: false, forced: false, headCommit: { sha: MERGE, message: 'm' } },
    { ref: 'refs/heads/gone', before: BASE, after: '0'.repeat(40), created: false, deleted: true, forced: false },
  ]), { storage });
  const records = (await refRecords(storage)).map((item) => item.payload);
  assert.deepEqual(records.map((record) => [record.ref, record.created, record.deleted, record.forced]), [
    ['refs/heads/mod/x', false, false, true], ['refs/heads/new', true, false, false], ['refs/heads/gone', false, true, false]]);
  assert.equal(records[0].pushed_at, '2026-11-01T19:00:00.000Z');
  assert.equal(records[0].pr, null);
  assert.equal(records[0].sha, HEAD);
  assert.deepEqual(records[0].premises, []);
});

test('a push a PR head also reports is counted once: the head_ref event adds pr.pushed and no ref record', async () => {
  const store = new MemoryStore();
  const storage = new Storage();
  await send(store, 'pull_request.head_ref.pushed', pull(), { storage });
  await send(store, 'repository.pushed', REF_PUSH([
    { ref: 'refs/heads/mod/x', before: BASE, after: HEAD, created: false, deleted: false, forced: false, headCommit: { sha: HEAD, message: 'm' } },
  ]), { storage });
  const all = await journal(storage);
  assert.equal(all.filter((item) => item.type === 'ref.updated').length, 1);
  assert.equal(all.filter((item) => item.type === 'pr.pushed').length, 1);
});

test('a redelivery of the same ref move carries the same event_id, so the reader can collapse it', async () => {
  const store = new MemoryStore();
  const storage = new Storage();
  const body = REF_PUSH([{ ref: 'refs/heads/mod/x', before: BASE, after: HEAD, created: false, deleted: false, forced: false,
    headCommit: { sha: HEAD, message: 'm' } }]);
  await send(store, 'repository.pushed', body, { storage });
  await send(store, 'repository.pushed', body, { storage });
  const records = await refRecords(storage);
  assert.equal(records.length, 2);
  assert.equal(records[0].event_id, records[1].event_id);
  assert.equal(records[0].event_id, await sha256Hex(JSON.stringify([ORIGIN_PRODUCER, 'ref.updated', [REPO, 'refs/heads/mod/x', BASE, HEAD]])));
});

test('an update that names no full branch ref or no full tips journals nothing, so the adapter has no record to misread', async () => {
  const store = new MemoryStore();
  const storage = new Storage();
  await send(store, 'repository.pushed', REF_PUSH([
    { ref: 'refs/tags/v1', before: BASE, after: HEAD, created: false, deleted: false, forced: false },
    { ref: 'refs/heads/x', before: 'nope', after: HEAD, created: false, deleted: false, forced: false },
  ]), { storage });
  assert.deepEqual(await refRecords(storage), []);
});

test('a PR merged or closed on Origin cancels its queued jobs, keeps the journal, and leaves a leased job to its budget', async () => {
  const store = new MemoryStore();
  const storage = new Storage();
  await send(store, 'pull_request.head_ref.pushed', pull(), { storage });
  await send(store, 'pull_request.head_ref.pushed', pull({}, { number: 8 }), { storage });
  await send(store, 'pull_request.head_ref.pushed', pull({}, { number: 9 }), { storage });
  store.claim({ name: 'vm' }, ['gate'], T0, CFG);  // gate:7 is leased
  store.enqueue({ id: `train:7#${HEAD}`, kind: 'train', repo: REPO, pr: 7, sha: HEAD, source: 'control', reason: 'r',
    requested_at: new Date(T0).toISOString(), attempt: 1 }, CFG);
  store.enqueue({ id: `gate:7#${BASE}`, kind: 'gate', repo: 'other/repo', pr: 7, sha: BASE, source: 'control', reason: 'r',
    requested_at: new Date(T0).toISOString(), attempt: 1 }, CFG);

  const merged = await send(store, 'pull_request.merged', pull({ state: 'closed', merged: true, mergeCommitSha: MERGE }), { storage });
  assert.equal(merged.status, 202);
  const state = (id) => store.jobs.find((item) => item.id === id).state;
  assert.equal(state(`train:7#${HEAD}`), 'cancelled');
  assert.equal(state(`gate:7#${HEAD}`), 'leased');
  assert.equal(state(`gate:7#${BASE}`), 'queued', 'another repository\'s PR 7 is another PR');
  assert.equal(store.facts.merges.length, 1);
  assert.ok((await journal(storage, 7)).some((item) => item.type === 'pr.merged'), 'the journal is kept');

  const closed = await send(store, 'pull_request.closed', pull({ state: 'closed' }, { number: 8 }), { storage });
  assert.equal(closed.status, 202);
  assert.equal(state(`gate:8#${HEAD}`), 'cancelled');
  assert.equal(state(`gate:9#${HEAD}`), 'queued');
  assert.equal(store.counters.jobs_cancelled_total, 2);
  assert.equal(store.facts.merges.length, 1, 'a close without a merge records no merge');
});

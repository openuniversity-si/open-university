// VAZÃO F34 (I-5102f4e9, SEMENTE §4 "cabe no plano gratuito, com folga"): the rows the Durable Object's storage reads,
// metered per UTC hour and day and exposed on /status and /metrics (rows_read). A get of one key is 1 row, a get of N
// keys N rows, a list the entries it returned; a put or a delete reads none. The storage is a fake of the Durable
// Object's (get of a key or of keys, put of an object, list by prefix/start/end/reverse/limit, delete of keys).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { MemoryStore, handle, metered, settings } from '../src/core.js';
import { Control } from '../src/index.js';

const BUDGET_S = String(JSON.parse(readFileSync(new URL('../../../config/registry/service/service.job_budget_s.json', import.meta.url), 'utf8')).default);
const ENV = { BUDGET_S, EVENTS_TOKEN: 'events', ADMIN_TOKEN: 'admin', RUNNER_TOKEN: 'runner', GITHUB_WEBHOOK_SECRET: 's' };
const T0 = Date.parse('2026-11-04T10:20:00Z');
const HOUR = 3600000;
const REPO = 'openuniversity-si/open-university';

class Storage {
  constructor() { this.held = new Map(); this.writes = []; }
  async get(key) {
    if (Array.isArray(key)) return new Map(key.filter((item) => this.held.has(item)).map((item) => [item, structuredClone(this.held.get(item))]));
    return structuredClone(this.held.get(key));
  }
  async put(entries) { this.writes.push(Object.keys(entries)); for (const [key, value] of Object.entries(entries)) this.held.set(key, structuredClone(value)); }
  async delete(keys) { for (const key of keys) this.held.delete(key); }
  async list({ prefix = '', start = '', end = null, reverse = false, limit = Infinity } = {}) {
    const keys = [...this.held.keys()].filter((key) => key.startsWith(prefix) && key >= start && (end === null || key < end)).sort();
    if (reverse) keys.reverse();
    return new Map(keys.slice(0, limit).map((key) => [key, structuredClone(this.held.get(key))]));
  }
}

const rowsOf = (store, now) => ({ hour: store.rows.hours[new Date(now).toISOString().slice(0, 13)] || 0 });

function call(store, storage, method, path, { body, now = T0, token = 'events' } = {}) {
  const request = new Request(`https://control${path}`, {
    method, headers: token ? { authorization: `Bearer ${token}` } : {}, body: body === undefined ? undefined : JSON.stringify(body),
  });
  return handle(request, ENV, store, now, storage);
}

const append = (store, storage, count, now = T0) => call(store, storage, 'POST', '/v1/events', {
  body: { channel: { repo: REPO, pr: 7 }, events: Array.from({ length: count }, (_, index) => ({ type: 'note', n: index })) }, now,
});

test('the metered view counts a get of one key as 1 row, of N keys as N, a list as the entries it returned', async () => {
  const storage = new Storage();
  await storage.put({ a: 1, b: 2, c: 3, 'ev:1': 1, 'ev:2': 2, 'ev:3': 3 });
  const view = metered(storage);
  assert.equal(metered(storage), view, 'one view per storage');
  assert.equal(await view.get('a'), 1);
  assert.equal(view.drain(), 1);
  await view.get(['a', 'b', 'missing']);
  assert.equal(view.drain(), 3);
  await view.list({ prefix: 'ev:', limit: 2 });
  assert.equal(view.drain(), 2);
  await view.list({ prefix: 'none:' });
  await view.put({ d: 4 });
  await view.delete(['d']);
  assert.equal(view.drain(), 0, 'an empty list, a put and a delete read no row');
});

test('each request adds the rows its storage reads to the hour: config get 1, append 1, a window its depth, then 0', async () => {
  const store = new MemoryStore();
  const storage = new Storage();
  await call(store, storage, 'GET', `/v1/config?repo=${REPO}`);
  assert.equal(rowsOf(store, T0).hour, 1, 'GET /v1/config is one storage get');
  await append(store, storage, 1);
  await append(store, storage, 1);
  assert.equal(rowsOf(store, T0).hour, 3, 'an append reads the sequence key, one row');
  await call(store, storage, 'GET', `/v1/events?repo=${REPO}&pr=7&tail=50`);
  assert.equal(rowsOf(store, T0).hour, 5, 'the first window lists the records it returns (2)');
  await call(store, storage, 'GET', `/v1/events?repo=${REPO}&pr=7&tail=50`);
  assert.equal(rowsOf(store, T0).hour, 5, 'a later window is answered from memory (F28): no row read');
  await call(store, storage, 'GET', `/v1/events?repo=${REPO}&pr=7&since=0`);
  assert.equal(rowsOf(store, T0).hour, 7, 'a paged read lists its page');
  await call(store, storage, 'GET', '/status', { token: null });
  assert.equal(rowsOf(store, T0).hour, 7, '/status reads no storage');
  assert.equal(store.dirty, true, 'the appends changed the state');
});

test('a read alone does not dirty the store: the meter is written alone at most once per ROWS_FLUSH_S', async () => {
  const cfg = settings({ ...ENV, ROWS_FLUSH_S: '300' });
  const store = new MemoryStore();
  store.read(4, T0);
  assert.equal(store.dirty, false);
  assert.deepEqual(Object.keys(store.flush(T0, cfg)), ['rows'], 'the first flush writes the meter, one row');
  store.read(1, T0 + 1000);
  assert.equal(store.flush(T0 + 1000, cfg), null, 'within the window nothing is written');
  assert.deepEqual(store.flush(T0 + 300000, cfg), { rows: { since: '2026-11-04T10', hours: { '2026-11-04T10': 5 } } });
  assert.equal(store.flush(T0 + 900000, cfg), null, 'nothing new read: nothing written');
  store.count('admin_actions_total');
  const whole = store.flush(T0 + 901000, cfg);
  assert.ok('jobs' in whole && whole.rows.hours['2026-11-04T10'] === 5, 'a dirty store writes its dump, the meter with it');
  store.read(2, T0 + 902000);
  const failed = store.flush(T0 + 1300000, cfg);
  store.unsaved(failed);
  assert.deepEqual(Object.keys(store.flush(T0 + 1300001, cfg)), ['rows'], 'a failed write is written again on the next request');
});

test('the day sums its UTC hours; the hour, the hour before and the day roll at UTC boundaries; two days are kept', async () => {
  const store = new MemoryStore();
  const late = Date.parse('2026-11-03T23:40:00Z');
  store.read(100, late - 2 * HOUR);
  store.read(30, late);
  store.read(7, late + 30 * 60000);  // 00:10 the next day
  const at = (now) => {
    const rows = {};
    const request = new Request('https://control/status');
    return handle(request, ENV, store, now).then((response) => response.json()).then((document) => {
      for (const [labels, value] of document.metrics.rows_read) rows[labels.window] = { ...labels, value };
      return rows;
    });
  };
  const before = await at(late);
  assert.equal(before.day.value, 130);
  assert.equal(before.day.at, '2026-11-03');
  assert.equal(before.hour.value, 30);
  assert.equal(before.previous_hour.value, 0);
  assert.equal(before.day.since, '2026-11-03T21');
  const after = await at(late + 30 * 60000);
  assert.deepEqual([after.day.value, after.day.at, after.hour.value, after.previous_hour.value, after.previous_hour.at],
    [7, '2026-11-04', 7, 30, '2026-11-03T23']);
  store.read(1, late + 49 * HOUR);
  assert.equal('2026-11-03T21' in store.rows.hours, false, 'an hour older than two days is dropped');
  assert.equal(store.rows.since, '2026-11-03T21', 'since keeps the first hour metered');
});

test('/metrics prints rows_read as gauges per window, labelled with the UTC day or hour', async () => {
  const store = new MemoryStore();
  const storage = new Storage();
  await call(store, storage, 'GET', `/v1/config?repo=${REPO}`);
  await call(store, storage, 'GET', `/v1/config?repo=${REPO}`, { now: T0 - HOUR });
  const text = await (await handle(new Request('https://control/metrics'), ENV, store, T0)).text();
  assert.match(text, /^# TYPE tower_rows_read gauge$/m);
  assert.match(text, /^tower_rows_read\{window="day",at="2026-11-04",since="2026-11-04T10"\} 2$/m);
  assert.match(text, /^tower_rows_read\{window="hour",at="2026-11-04T10",since="2026-11-04T10"\} 1$/m);
  assert.match(text, /^tower_rows_read\{window="previous_hour",at="2026-11-04T09",since="2026-11-04T10"\} 1$/m);
});

test('the Durable Object counts its load (one row per key) and writes the meter with no other change', async () => {
  const storage = new Storage();
  await storage.put({ jobs: [], counters: { admin_actions_total: 2 } });
  storage.writes = [];
  const waits = [];
  const ctx = { storage, blockConcurrencyWhile: (step) => { const done = step(); waits.push(done); return done; } };
  const control = new Control(ctx, ENV);
  await Promise.all(waits);
  const loaded = Object.values(control.store.rows.hours).reduce((sum, rows) => sum + rows, 0);
  assert.equal(loaded, MemoryStore.KEYS.length, 'the load is a get of every state key');
  assert.equal(control.store.counters.admin_actions_total, 2);
  await control.fetch(new Request('https://control/status'));
  assert.deepEqual(storage.writes, [['rows']], 'a read request writes the meter alone, not the whole state');
  await control.fetch(new Request(`https://control/v1/config?repo=${REPO}`, { headers: { authorization: 'Bearer events' } }));
  assert.deepEqual(storage.writes, [['rows']], 'within ROWS_FLUSH_S the meter is not written again');
  assert.equal(Object.values(control.store.rows.hours).reduce((sum, rows) => sum + rows, 0), MemoryStore.KEYS.length + 1);
  storage.put = async () => { throw new Error('storage down'); };
  await assert.rejects(control.fetch(new Request('https://control/v1/admin', {
    method: 'POST', headers: { authorization: 'Bearer admin' }, body: JSON.stringify({ action: 'pause', reason: 'test' }),
  })), /storage down/);
  assert.equal(control.store.dirty, true, 'a failed write keeps the state to write on the next request');
});

test('a view of a view is the same view: every read is counted once', async () => {
  const storage = new Storage();
  const view = metered(storage);
  assert.equal(metered(view), view);
  await metered(view).get('a');
  assert.equal(view.drain(), 1);
});

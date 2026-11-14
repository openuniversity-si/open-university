// The control plane's logic (GATE-TRAIN-SERVICES, ADR-41, D-086) under node --test: signed and deduplicated webhooks,
// the jobs they make, claims and leases, results, pause, requeue and cancel, the cron tick, status and metrics. No
// network and no Cloudflare runtime: core.js is plain JavaScript over a MemoryStore.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { MARKER, MemoryStore, handle, hmacHex, jobsOf, settings, verify } from '../src/core.js';

const SECRET = 'webhook-secret';
// BUDGET_S as the deploy sends it: service.job_budget_s of the registry (scripts/lib/service_deploy.py), the one budget.
const BUDGET_S = String(JSON.parse(readFileSync(new URL('../../../config/registry/service/service.job_budget_s.json', import.meta.url), 'utf8')).default);
const ENV = { BUDGET_S, GITHUB_WEBHOOK_SECRET: SECRET, ADMIN_TOKEN: 'admin', RUNNER_TOKEN: 'runner' };
const CFG = settings(ENV);
const T0 = Date.parse('2026-10-30T06:00:00Z');
const HEAD = 'a'.repeat(40);
const OTHER = 'b'.repeat(40);

function pull(action, number = 7, extra = {}) {
  return { action, pull_request: { number, state: 'open', draft: false, head: { sha: HEAD }, base: { ref: CFG.baseBranch }, ...extra } };
}

function comment(envelopes, association = 'OWNER') {
  const lines = envelopes.map((item) => JSON.stringify(item)).join('\n');
  return { action: 'created', issue: { number: 7, pull_request: {} },
    comment: { author_association: association, body: `${MARKER}\nforge_events: x\n\n\`\`\`jsonl\n${lines}\n\`\`\`\n` } };
}

async function deliver(store, event, payload, { delivery = `d-${Math.random()}`, secret = SECRET, now = T0 } = {}) {
  const body = JSON.stringify(payload);
  const request = new Request('https://control/webhook', { method: 'POST', body, headers: {
    'x-github-event': event, 'x-github-delivery': delivery, 'x-hub-signature-256': `sha256=${await hmacHex(secret, body)}` } });
  return handle(request, ENV, store, now);
}

function call(store, path, body, token, now = T0) {
  const headers = token ? { authorization: `Bearer ${token}` } : {};
  return handle(new Request(`https://control${path}`, { method: 'POST', body: JSON.stringify(body), headers }), ENV, store, now);
}

const claim = (store, now = T0, name = 'box') => call(store, '/v1/runner/claim', { runner: { name, kind: 'box' }, kinds: ['gate', 'train', 'sweep'] }, 'runner', now);

test('closed PR barriers survive storage and ignore late ready events until an explicit reopen', async () => {
  let store = new MemoryStore();
  await deliver(store, 'pull_request', pull('closed'));
  store = new MemoryStore(store.dump());
  const ready = comment([{ type: 'pr.ready', event_id: 'late', payload: { pr: 7, sha: HEAD } }]);
  await deliver(store, 'issue_comment', ready);
  assert.equal(store.jobs.length, 0);
  assert.equal(store.counters.jobs_closed_ignored_total, 1);
  await deliver(store, 'pull_request', pull('reopened'));
  assert.equal(store.jobs[0].kind, 'gate');
});

test('the budget cannot be missing, zero, negative or nonnumeric', () => {
  for (const value of [undefined, '', '0', '-1', 'invalid']) assert.throws(() => settings({ BUDGET_S: value }), /BUDGET_S/);
  assert.equal(CFG.leaseMs, CFG.budgetMs);
});

test('deploys use the queue budget, retry a failure after backoff, and supersede older pending deploys', async () => {
  const store = new MemoryStore();
  await deliver(store, 'push', { ref: `refs/heads/${CFG.baseBranch}`, after: HEAD });
  const deployClaim = (now) => call(store, '/v1/runner/claim', { runner: { name: 'vm', kind: 'vm' }, kinds: ['deploy'] }, 'runner', now);
  const item = await (await deployClaim(T0)).json();
  assert.equal(item.kind, 'deploy');
  assert.equal(store.jobs.find((held) => held.id === item.id).lease_until, T0 + CFG.budgetMs);
  const result = await call(store, '/v1/runner/result', { job: item.id, outcome: 'failed',
    reason: 'upload refused', runner: { name: 'vm', kind: 'vm' } }, 'runner', T0 + 1);
  assert.equal(result.status, 200);
  assert.equal(store.runners.vm.job, null);
  assert.equal((await deployClaim(T0 + 2)).status, 204);
  assert.equal(store.jobs.filter((held) => held.kind === 'deploy' && held.state === 'queued').length, 1);
  const retry = await (await deployClaim(T0 + CFG.deployRetryMs + 1)).json();
  assert.equal(retry.attempt, 2);
  await call(store, '/v1/runner/result', { job: retry.id, outcome: 'failed', runner: { name: 'vm' } }, 'runner', T0 + CFG.deployRetryMs + 2);
  await deliver(store, 'push', { ref: `refs/heads/${CFG.baseBranch}`, after: OTHER }, { now: T0 + CFG.deployRetryMs + 3 });
  assert.deepEqual(store.jobs.filter((held) => held.kind === 'deploy' && held.state === 'queued').map((held) => held.sha), [OTHER]);
});

test('another runner cannot complete a holder job, and expiry clears the held runner slot', async () => {
  const store = new MemoryStore();
  await deliver(store, 'pull_request', pull('synchronize'));
  const item = await (await claim(store)).json();
  const refused = await call(store, '/v1/runner/result', { job: item.id, outcome: 'passed', runner: { name: 'other' } }, 'runner');
  assert.equal(refused.status, 409);
  await status(store, T0 + CFG.budgetMs);
  assert.equal(store.runners.box.job, null);
  assert.equal(store.jobs[0].outcome, 'died');
});

test('a signature is checked in constant time and a wrong one refused', async () => {
  const body = '{"a":1}';
  assert.equal(await verify(SECRET, body, `sha256=${await hmacHex(SECRET, body)}`), true);
  assert.equal(await verify(SECRET, body, `sha256=${await hmacHex('other', body)}`), false);
  assert.equal(await verify(SECRET, body, null), false);
  const store = new MemoryStore();
  const refused = await deliver(store, 'pull_request', pull('synchronize'), { secret: 'forged' });
  assert.equal(refused.status, 401);
  assert.equal(store.jobs.length, 0);
});

test('a push to a PR on the base is one gate job, and a redelivery is handled once', async () => {
  const store = new MemoryStore();
  const first = await deliver(store, 'pull_request', pull('synchronize'), { delivery: 'same' });
  assert.equal(first.status, 202);
  assert.deepEqual((await first.json()).queued, [`gate:7#${HEAD}`]);
  const again = await deliver(store, 'pull_request', pull('synchronize'), { delivery: 'same' });
  assert.deepEqual(await again.json(), { duplicate: true });
  assert.equal(store.jobs.length, 1);
});

test('another base, a closed PR or a draft with drafts off makes no job', () => {
  assert.deepEqual(jobsOf('pull_request', pull('synchronize', 7, { base: { ref: 'main' } }), CFG, T0).jobs, []);
  assert.deepEqual(jobsOf('pull_request', pull('closed'), CFG, T0).jobs, []);
  const noDrafts = { ...CFG, gateDrafts: false };
  assert.deepEqual(jobsOf('pull_request', pull('opened', 7, { draft: true }), noDrafts, T0).jobs, []);
});

test('pr.ready in a trusted forge-events comment is a train job; an untrusted one is ignored', () => {
  const ready = { type: 'pr.ready', event_id: 'e1', occurred_at: '2026-10-30T06:00:00Z', payload: { pr: 7, sha: HEAD } };
  assert.deepEqual(jobsOf('issue_comment', comment([ready]), CFG, T0).jobs.map((item) => item.id), [`train:7#${HEAD}`]);
  assert.deepEqual(jobsOf('issue_comment', comment([ready], 'NONE'), CFG, T0).jobs, []);
});

test('a wake record pushed to train/wake is a train job, a push to the base a sweep', () => {
  const wake = { ref: `refs/heads/${CFG.wakeRef}`, head_commit: { message: JSON.stringify({ pr: 9, sha: OTHER, event_id: 'e2' }) } };
  assert.deepEqual(jobsOf('push', wake, CFG, T0).jobs.map((item) => item.id), [`train:9#${OTHER}`]);
  const base = { ref: `refs/heads/${CFG.baseBranch}`, after: OTHER };
  assert.deepEqual(jobsOf('push', base, CFG, T0).jobs.map((item) => item.kind), ['deploy', 'sweep']);
});

test('a claim is exclusive, trains first, and a lease past its end is never claimed again', async () => {
  const store = new MemoryStore();
  await deliver(store, 'pull_request', pull('synchronize'));
  await deliver(store, 'issue_comment', comment([{ type: 'pr.ready', payload: { pr: 9, sha: OTHER } }]));
  const first = await (await claim(store)).json();
  assert.equal(first.kind, 'train');
  for (const key of ['state', 'runner', 'claimed_at', 'lease_until', 'outcome', 'result']) assert.ok(!(key in first), key);
  const second = await (await claim(store, T0, 'vm')).json();
  assert.equal(second.kind, 'gate');
  assert.equal((await claim(store, T0, 'third')).status, 204);
  const late = T0 + CFG.leaseMs + 1;
  assert.equal((await claim(store, late, 'third')).status, 204);
  assert.deepEqual(store.jobs.map((item) => item.outcome), ['died', 'died']);
});

test('a result closes the job and is counted; a heartbeat renews nothing', async () => {
  const store = new MemoryStore();
  await deliver(store, 'pull_request', pull('synchronize'));
  const item = await (await claim(store)).json();
  assert.equal(store.jobs[0].lease_until, T0 + CFG.leaseMs);
  const beat = await (await call(store, '/v1/runner/heartbeat', { runner: 'box', job: item.id }, 'runner', T0 + 5000)).json();
  assert.deepEqual(beat, { cancel: false });
  assert.equal(store.jobs[0].lease_until, T0 + CFG.leaseMs, 'the beat did not move the lease');
  assert.equal(store.runners.box.heartbeat, new Date(T0 + 5000).toISOString());
  const done = await call(store, '/v1/runner/result', { job: item.id, outcome: 'passed', duration_s: 120,
    runner: { name: 'box', kind: 'box' }, started_at: '2026-10-30T06:00:00Z', finished_at: '2026-10-30T06:02:00Z' }, 'runner');
  assert.equal(done.status, 200);
  assert.equal(store.jobs[0].state, 'done');
  assert.equal(store.counters.jobs_passed_total, 1);
  assert.equal((await call(store, '/v1/runner/claim', { runner: { name: 'box' } }, 'wrong')).status, 401);
});

test('pause stops claims; cancel reaches a running job; requeue is the next attempt', async () => {
  const store = new MemoryStore();
  await deliver(store, 'pull_request', pull('synchronize'));
  assert.equal((await call(store, '/v1/admin', { action: 'pause' }, 'admin')).status, 400);  // a reason is required
  await call(store, '/v1/admin', { action: 'pause', reason: 'maintenance' }, 'admin');
  assert.equal((await claim(store)).status, 204);
  await call(store, '/v1/admin', { action: 'resume', reason: 'done' }, 'admin');
  const item = await (await claim(store)).json();
  await call(store, '/v1/admin', { action: 'cancel', pr: 7, reason: 'abandoned' }, 'admin');
  assert.deepEqual(await (await call(store, '/v1/runner/heartbeat', { runner: 'box', job: item.id }, 'runner')).json(), { cancel: true });
  const again = await (await call(store, '/v1/admin', { action: 'requeue', pr: 7, reason: 'retry' }, 'admin')).json();
  assert.equal(again.done, `queued gate:7#${HEAD}.2`);
  assert.equal((await call(store, '/v1/admin', { action: 'pause', reason: 'x' }, 'runner')).status, 401);
  assert.ok(store.logLines.some((line) => line.kind === 'admin' && line.action === 'cancel'));
});

test('the tick requeues no lease and queues one sweep per interval', async () => {
  const store = new MemoryStore();
  await deliver(store, 'pull_request', pull('synchronize'));
  await claim(store);
  const late = T0 + CFG.leaseMs + 1;
  const ticked = await (await call(store, '/internal/tick', {}, 'admin', late)).json();
  assert.deepEqual(Object.keys(ticked), ['swept']);
  assert.ok(ticked.swept.startsWith('sweep:'));
  assert.equal(store.jobs.find((item) => item.kind === 'gate').outcome, 'died');
  assert.ok(!store.jobs.some((item) => item.kind === 'gate' && item.state === 'queued'));
  assert.equal((await (await call(store, '/internal/tick', {}, 'admin', late + 1)).json()).swept, null);
  assert.equal((await call(store, '/internal/tick', {}, null, late)).status, 401);
});

test('green to merged and push to verdict are measured from the deliveries', async () => {
  const store = new MemoryStore();
  await deliver(store, 'pull_request', pull('synchronize'), { now: T0 });
  await deliver(store, 'issue_comment', comment([
    { type: 'gate.passed', occurred_at: '2026-10-30T06:02:00.000Z', payload: { pr: 7, sha: HEAD } },
    { type: 'pr.ready', occurred_at: '2026-10-30T06:02:05.000Z', payload: { pr: 7, sha: HEAD } }]));
  await deliver(store, 'issue_comment', comment([
    { type: 'pr.merged', occurred_at: '2026-10-30T06:02:50.000Z', payload: { pr: 7, sha: HEAD, batch_id: 'v-1' } }]));
  assert.equal(store.facts.merges[0].green_to_merged_s, 45);
  assert.equal(store.facts.verdicts[0].push_to_verdict_s, 120);
  const metrics = await (await handle(new Request('https://control/metrics'), ENV, store, T0)).text();
  assert.match(metrics, /^tower_green_to_merged_seconds\{quantile="0.5"\} 45$/m);
  for (const line of metrics.split('\n').filter((item) => item && !item.startsWith('#'))) {
    assert.match(line, /^tower_[a-z_]+(\{[a-z_]+="[^"]*"(,[a-z_]+="[^"]*")*\})? -?[0-9.e+-]+$/);
  }
});

test('status, health and readiness answer without a token; readiness names a missing secret', async () => {
  const store = new MemoryStore();
  const status = await (await handle(new Request('https://control/status'), ENV, store, T0)).json();
  for (const key of ['at', 'switches', 'train', 'queue', 'merges', 'runner', 'window', 'health']) assert.ok(key in status);
  assert.equal((await handle(new Request('https://control/healthz'), { BUDGET_S }, store, T0)).status, 200);
  const ready = await handle(new Request('https://control/readyz'), { BUDGET_S, ADMIN_TOKEN: 'x' }, store, T0);
  assert.equal(ready.status, 503);
  assert.deepEqual((await ready.json()).missing, ['GITHUB_WEBHOOK_SECRET', 'RUNNER_TOKEN']);
  assert.match(await (await handle(new Request('https://control/'), ENV, store, T0)).text(), /Tower control plane/);
});

test('the store survives a dump and a reload (the Durable Object storage round trip)', async () => {
  const store = new MemoryStore();
  await deliver(store, 'pull_request', pull('synchronize'));
  const copy = new MemoryStore(JSON.parse(JSON.stringify(store.dump())));
  assert.deepEqual(copy.dump(), store.dump());
  assert.equal(copy.jobs[0].id, `gate:7#${HEAD}`);
});

// CONTROL-STORE: retention, supersession and TTL of the job store.
const gateJob = (pr, sha, now = T0) => jobsOf('pull_request', pull('synchronize', pr, { head: { sha } }), CFG, now).jobs[0];
const sha = (n) => String(n).padStart(40, '0');

test('retention: over the keepJobs budget the store keeps no history; under budget it keeps what fits', () => {
  const store = new MemoryStore();
  const cfg = { ...CFG, keepJobs: 3 };
  store.jobs = Array.from({ length: 5 }, (_, i) => ({ id: `old${i}`, kind: 'gate', pr: 100 + i, sha: sha(i), state: 'done', requested_at: new Date(T0).toISOString() }));
  // under budget: 1 live + 5 done, room for 2 -> the two newest done jobs stay
  store.enqueue(gateJob(1, sha(1)), cfg);
  assert.deepEqual(store.jobs.filter((j) => j.state === 'done').map((j) => j.id), ['old3', 'old4']);
  // over budget: 4 live > 3 -> no history at all
  for (const pr of [2, 3, 4]) store.enqueue(gateJob(pr, sha(pr)), cfg);
  assert.equal(store.jobs.filter((j) => j.state === 'done').length, 0);
  assert.equal(store.jobs.filter((j) => j.state === 'queued').length, 4);
});

test('supersession: three queued jobs for one PR collapse to the newest, and the counter says so', () => {
  const store = new MemoryStore();
  for (const n of [1, 2, 3]) store.enqueue(gateJob(7, sha(n)), CFG);
  store.enqueue(gateJob(8, sha(1)), CFG);
  const mine = store.jobs.filter((j) => j.pr === 7);
  assert.deepEqual(mine.map((j) => j.sha), [sha(3)]);
  assert.equal(store.jobs.filter((j) => j.pr === 8).length, 1);
  assert.equal(store.counters.jobs_superseded_total, 2);
  // the same sha again is the same job id: not enqueued, nothing superseded
  assert.equal(store.enqueue(gateJob(7, sha(3)), CFG), false);
  assert.equal(store.counters.jobs_superseded_total, 2);
});

test('supersession: a leased or cancelling job is never dropped, and a different kind is left alone', () => {
  const store = new MemoryStore();
  store.enqueue(gateJob(7, sha(1)), CFG);
  store.enqueue(gateJob(9, sha(1)), CFG);
  store.claim({ name: 'box' }, ['gate'], T0, CFG);
  store.claim({ name: 'box2' }, ['gate'], T0, CFG);
  store.jobs.find((j) => j.pr === 9).state = 'cancelling';
  store.enqueue({ ...gateJob(7, sha(2)), kind: 'train', id: `train:7#${sha(2)}` }, CFG);
  store.enqueue(gateJob(7, sha(3)), CFG);
  store.enqueue(gateJob(9, sha(3)), CFG);
  assert.equal(store.jobs.find((j) => j.id === `gate:7#${sha(1)}`).state, 'leased');
  assert.equal(store.jobs.find((j) => j.id === `gate:9#${sha(1)}`).state, 'cancelling');
  assert.ok(store.jobs.some((j) => j.kind === 'train' && j.pr === 7));
  assert.equal(store.counters.jobs_superseded_total, undefined);
});

test('ttl: an old queued job is discarded and never claimed; a leased one whose lease ended died', () => {
  const store = new MemoryStore();
  store.enqueue(gateJob(7, sha(1), T0), CFG);
  store.enqueue(gateJob(8, sha(1), T0), CFG);
  assert.equal(store.claim({ name: 'box' }, ['gate'], T0, CFG).pr, 7);
  const late = T0 + CFG.jobTtlMs + 1;
  // pr 9 is fresh; pr 8 is old and queued; pr 7 is old and leased (its lease ended: died, never reclaimed)
  store.enqueue(gateJob(9, sha(1), late), CFG);
  store.expire(late, CFG);
  assert.equal(store.jobs.find((j) => j.pr === 7).outcome, 'died');
  assert.ok(!store.jobs.some((j) => j.pr === 8), 'the old queued job is gone');
  assert.equal(store.claim({ name: 'box3' }, ['gate'], late, CFG).pr, 9);
  assert.equal(store.claim({ name: 'box4' }, ['gate'], late, CFG), null);
  assert.equal(store.counters.jobs_expired_total, 1);
  assert.equal(store.counters.jobs_died_total, 1);
  assert.equal(CFG.jobTtlMs, 3600 * 1000);
  assert.equal(settings({ BUDGET_S, JOB_TTL_S: '60' }).jobTtlMs, 60000);
});

test('ttl: the tick expires old queued jobs and ended leases, and the metrics carry the counters', async () => {
  const store = new MemoryStore();
  store.enqueue(gateJob(7, sha(1)), CFG);
  store.enqueue(gateJob(8, sha(1)), CFG);
  store.claim({ name: 'box' }, ['gate'], T0, CFG);
  const late = T0 + CFG.jobTtlMs + 1;
  store.tick(late, CFG);
  assert.deepEqual(store.jobs.filter((j) => j.kind === 'gate').map((j) => [j.pr, j.outcome]), [[7, 'died']]);
  store.count('jobs_superseded_total', 0);
  const text = await (await handle(new Request('https://control/metrics'), ENV, store, late)).text();
  assert.match(text, /jobs_expired_total 1/);
  assert.match(text, /jobs_died_total 1/);
  assert.match(text, /jobs_superseded_total 0/);
});

// D-291 (TRAIN-DEFINITIVE): one budget per runner job, an ended lease is a died result, expiry on every request, a
// closed PR cancels its queued work, a runner name is a string, a silent runner leaves, a refused token is named.
const status = async (store, now, env = ENV) => (await handle(new Request('https://control/status'), env, store, now)).json();

test('lease = budget: the registry budget is the lease, and wrangler.toml never sets a second one', async () => {
  assert.equal(CFG.budgetMs, Number(BUDGET_S) * 1000);
  assert.equal(CFG.leaseMs, CFG.budgetMs);
  assert.equal(CFG.runnerStaleMs, 180000);
  assert.equal(CFG.runnerForgetMs, 86400000);
  const toml = await import('node:fs').then((fs) => fs.readFileSync(new URL('../wrangler.toml', import.meta.url), 'utf8'));
  assert.doesNotMatch(toml, /^BUDGET_S =/m);
  assert.doesNotMatch(toml, /^LEASE_S =/m);
  const vars = Object.fromEntries([...toml.matchAll(/^([A-Z_]+) = "([^"]*)"$/gm)].map((match) => [match[1], match[2]]));
  assert.equal(settings({ ...vars, BUDGET_S }).leaseMs, settings({ ...vars, BUDGET_S }).budgetMs);
});

test('an ended lease is a died result with a reason, counted and logged, and a late result is refused', async () => {
  const store = new MemoryStore();
  await deliver(store, 'pull_request', pull('synchronize'));
  const item = await (await claim(store, T0, 'vm')).json();
  assert.equal((await claim(store, T0 + CFG.leaseMs, 'vm')).status, 204, 'the lease ends exactly at the deadline');
  assert.equal(store.jobs[0].state, 'done');
  const late = T0 + CFG.leaseMs + 1;
  assert.equal((await claim(store, late, 'other')).status, 204);
  const held = store.jobs[0];
  assert.equal(held.state, 'done');
  assert.equal(held.outcome, 'died');
  assert.deepEqual(held.result, { job: item.id, outcome: 'died',
    reason: `the lease ended with no result from runner vm (budget ${BUDGET_S} s including reporting)`, runner: { name: 'vm', kind: 'box' },
    started_at: new Date(T0).toISOString(), finished_at: new Date(T0 + CFG.leaseMs).toISOString(), duration_s: Number(BUDGET_S), phases: [], exit: null, verdict_event: null, log_tail: '' });
  assert.equal(store.counters.jobs_died_total, 1);
  assert.ok(store.logLines.some((line) => line.kind === 'died' && line.job === item.id && line.runner === 'vm'));
  const result = await call(store, '/v1/runner/result', { job: item.id, outcome: 'passed', duration_s: 13,
    runner: { name: 'vm', kind: 'box' }, started_at: '2026-10-30T06:00:00Z', finished_at: '2026-10-30T06:00:13Z' }, 'runner', late + 1);
  assert.equal(result.status, 409);
  assert.equal(store.jobs[0].outcome, 'died', 'the definite result stands');
  assert.equal(store.counters.results_late_total, 1);
  assert.equal(store.counters.jobs_passed_total, undefined);
});

test('a cancelling job whose lease ended died too', async () => {
  const store = new MemoryStore();
  await deliver(store, 'pull_request', pull('synchronize'));
  await claim(store);
  await call(store, '/v1/admin', { action: 'cancel', pr: 7, reason: 'abandoned' }, 'admin');
  assert.equal(store.jobs[0].state, 'cancelling');
  await call(store, '/v1/admin', { action: 'pause', reason: 'x' }, 'admin', T0 + CFG.leaseMs + 1);
  assert.equal(store.jobs[0].outcome, 'died');
});

test('every request expires first: GET /status never counts a dead lease or a stale queued job', async () => {
  const store = new MemoryStore();
  await deliver(store, 'pull_request', pull('synchronize'));
  await deliver(store, 'pull_request', pull('synchronize', 8));
  await claim(store);
  assert.equal((await status(store, T0)).jobs.length, 2);
  const after = await status(store, T0 + CFG.leaseMs + 1);
  assert.deepEqual(after.jobs.map((item) => item.pr), [8]);
  assert.equal(store.counters.jobs_died_total, 1);
  assert.deepEqual((await status(store, T0 + CFG.jobTtlMs + 1)).jobs, []);
  assert.equal(store.counters.jobs_expired_total, 1);
  assert.equal((await handle(new Request('https://control/healthz'), ENV, new MemoryStore(), T0)).status, 200);
});

test('a closed PR, merged or not, cancels its queued jobs and leaves a leased one to its budget', async () => {
  assert.deepEqual(jobsOf('pull_request', pull('closed'), CFG, T0).cancels, [{ repo: CFG.repo, pr: 7 }]);
  const store = new MemoryStore();
  await deliver(store, 'pull_request', pull('synchronize', 7));
  await deliver(store, 'issue_comment', comment([{ type: 'pr.ready', payload: { pr: 7, sha: HEAD } }]));
  await deliver(store, 'pull_request', pull('synchronize', 8));
  assert.equal((await (await claim(store)).json()).kind, 'train');  // train:7 is leased, gate:7 and gate:8 queued
  const closed = await deliver(store, 'pull_request', pull('closed', 7, { state: 'closed', merged: true,
    merged_at: '2026-10-30T06:01:00Z' }), { now: T0 + 1000 });
  assert.equal(closed.status, 202);
  const state = Object.fromEntries(store.jobs.map((item) => [item.id, item.state]));
  assert.deepEqual(state, { [`gate:7#${HEAD}`]: 'cancelled', [`train:7#${HEAD}`]: 'leased', [`gate:8#${HEAD}`]: 'queued' });
  assert.equal(store.counters.jobs_cancelled_total, 1);
  assert.ok(store.logLines.some((line) => line.kind === 'cancelled' && line.pr === 7 && line.jobs.length === 1));
  assert.deepEqual(store.facts.merges.map((item) => [item.pr, item.occurred_at]), [[7, '2026-10-30T06:01:00Z']]);
  // the same merge reported again (pr.merged on the comment route) is one measure, not two
  await deliver(store, 'issue_comment', comment([{ type: 'pr.merged', occurred_at: '2026-10-30T06:01:01Z', payload: { pr: 7, sha: HEAD } }]));
  assert.equal(store.facts.merges.length, 1);
  // closed without a merge: cancels, records no merge
  await deliver(store, 'pull_request', pull('closed', 8, { state: 'closed', merged: false }), { now: T0 + 2000 });
  assert.equal(store.jobs.find((item) => item.pr === 8).state, 'cancelled');
  assert.equal(store.facts.merges.length, 1);
});

test('a runner name that is not a short non-empty string is refused and stored nowhere', async () => {
  const store = new MemoryStore();
  await deliver(store, 'pull_request', pull('synchronize'));
  const asked = (runner) => call(store, '/v1/runner/claim', { runner, kinds: ['gate'] }, 'runner');
  for (const runner of [{ name: { name: 'probe', kind: 'other' } }, { name: '' }, { name: 'x'.repeat(101) }, {}, 'box']) {
    assert.equal((await asked(runner)).status, 400, JSON.stringify(runner));
  }
  for (const runner of [{ name: 'probe' }, '', 'x'.repeat(101), 7, null]) {
    assert.equal((await call(store, '/v1/runner/heartbeat', { runner, job: null }, 'runner')).status, 400, JSON.stringify(runner));
  }
  assert.deepEqual(store.runners, {});
  assert.equal(store.jobs[0].state, 'queued');
  assert.equal((await asked({ name: 'x'.repeat(100), kind: 'vm' })).status, 200);
});

test('a runner warns after RUNNER_STALE_S of silence (it beats during a job too) and is forgotten after RUNNER_FORGET_S', async () => {
  const store = new MemoryStore();
  await claim(store, T0, 'vm');
  const check = async (now) => (await status(store, now)).health.checks.find((item) => item.name === 'runner vm');
  assert.equal((await check(T0 + CFG.runnerStaleMs - 1000)).status, 'pass');
  assert.equal((await check(T0 + CFG.runnerStaleMs + 1000)).status, 'warn');
  assert.ok(store.runners.vm);
  assert.equal(await check(T0 + CFG.runnerForgetMs + 1000), undefined);
  assert.deepEqual(store.runners, {});
});

test('a refused runner token names the runner in the health until that runner authenticates again', async () => {
  const store = new MemoryStore();
  const refused = await call(store, '/v1/runner/claim', { runner: { name: 'vm', kind: 'vm' }, kinds: ['gate'] }, 'rotated', T0);
  assert.equal(refused.status, 401);
  await call(store, '/v1/runner/heartbeat', { runner: 'box', job: null }, 'rotated', T0 + 1000);
  await call(store, '/v1/runner/result', { job: 'gate:1#x', runner: { name: 'actions' } }, null, T0 + 2000);
  await call(store, '/v1/runner/claim', { runner: { name: { bad: 1 } } }, 'rotated', T0 + 3000);  // no name: counted only
  assert.deepEqual(Object.keys(store.refused).sort(), ['actions', 'box', 'vm']);
  assert.deepEqual(store.refused.vm, { at: new Date(T0).toISOString(), path: '/v1/runner/claim' });
  assert.equal(store.counters.runner_refused_total, 4);
  const doc = await status(store, T0 + 4000);
  assert.equal(doc.health.status, 'fail');
  assert.deepEqual(doc.health.checks.find((item) => item.name === 'runner vm token'), { name: 'runner vm token', status: 'fail',
    detail: `refused at ${new Date(T0).toISOString()} on /v1/runner/claim: its OU_RUNNER_TOKEN is not the Worker's RUNNER_TOKEN (rotated?); see service.credentials` });
  assert.deepEqual(doc.refused, store.refused);
  // the store keeps it across a reload, and the runner's next authenticated request clears it
  const copy = new MemoryStore(JSON.parse(JSON.stringify(store.dump())));
  assert.deepEqual(copy.refused, store.refused);
  assert.ok(MemoryStore.KEYS.includes('refused'));
  assert.equal((await claim(store, T0 + 5000, 'vm')).status, 204);
  await call(store, '/v1/runner/heartbeat', { runner: 'box', job: null }, 'runner', T0 + 6000);
  assert.deepEqual(Object.keys(store.refused), ['actions']);
  // bounded: the newest ten names
  for (let i = 0; i < 12; i += 1) await call(store, '/v1/runner/heartbeat', { runner: `r${i}`, job: null }, 'rotated', T0 + 10000 + i);
  assert.equal(Object.keys(store.refused).length, 10);
  assert.ok(store.refused.r11 && !store.refused.actions && !store.refused.r0 && !store.refused.r1);
});

test('the status names the deployed tree, or null when the deploy did not say', async () => {
  const store = new MemoryStore();
  assert.equal((await status(store, T0)).deployed_tree, null);
  const tree = 'd'.repeat(40);
  assert.equal((await status(store, T0, { ...ENV, DEPLOYED_TREE: tree })).deployed_tree, tree);
});

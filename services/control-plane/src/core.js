// The control plane of the gate and the train (GATE-TRAIN-SERVICES, ADR-41, D-086): the one owner of the operational
// state. Pure logic over a Store, so the same code runs in the Durable Object (index.js persists the store) and under
// `node --test` (test/). The API is contracts/service/api.v1.json, jobs contracts/service/job.v2.json, results
// contracts/service/result.v1.json, the status contracts/service/status.v1.json.
//
// Webhook → jobs: a pull_request opened, synchronized, reopened or marked ready on the base is a gate job of its head; a
// forge-events comment holding pr.ready is a train job of its PR and head; a push to the wake ref is a train job of the
// record it carries; a push to the base queues a deploy and a sweep. Each delivery is verified (X-Hub-Signature-256), answered at once
// and handled once (X-GitHub-Delivery); a PR closed or merged cancels its queued jobs. Every delivery, dispatch and admin
// action is a line of the event log (/events).
//
// One budget per runner job (D-291): BUDGET_S (service.job_budget_s, sent by the deploy) from claim to result. A claim leases a queued job for BUDGET_S, including reporting, and the lease is never renewed: a heartbeat records the runner's beat and
// answers cancel, nothing more. A lease that ends with no result is a definite result, `died`, never a silent requeue.
// Every request expires first (dead leases, queued jobs past JOB_TTL_S, runners silent for RUNNER_FORGET_S), so /status
// never counts dead work. A runner whose token is refused is named in the health until it authenticates again.
//
// Origin (CANALE8) enters by the same door, POST /webhook/origin: an Ed25519 delivery instead of an HMAC one, the same
// dedupe, the same jobs and facts, and its facts on the engine's journal (/v1/events) as the port's own envelopes.
//
// The gate's verdict leaves by POST /v1/check-run (F37, D-299): checks.js posts it to Origin as the app (ORIGIN_APP_*).
import { checkRunRoute } from './checks.js';

export const KINDS = ['gate', 'train', 'sweep', 'deploy'];
const CLAIM_ORDER = ['deploy', 'train', 'gate', 'sweep'];
export const MARKER = '<!-- forge-events v1 -->';
// An event_id the journal has already turned into work, kept in the store's "handled once" ring (MemoryStore.seen).
export const ACTIONED = 'event:';
export const TRUSTED = ['OWNER', 'MEMBER', 'COLLABORATOR'];
const FENCE = '```';
const GATE_ACTIONS = ['opened', 'synchronize', 'reopened', 'ready_for_review'];

export function settings(env = {}) {
  const number = (name, fallback) => (env[name] === undefined || env[name] === '' ? fallback : Number(env[name]));
  const budgetMs = Number(env.BUDGET_S) * 1000;  // required: the deploy sends service.job_budget_s, there is no default here
  if (!env.BUDGET_S || !Number.isFinite(budgetMs) || budgetMs <= 0) throw new Error('BUDGET_S must be set (service.job_budget_s) and positive');
  return {
    repo: env.REPO || 'openuniversity-si/open-university',
    baseBranch: env.BASE_BRANCH || 'mod/roadmap-integration',
    wakeRef: env.WAKE_REF || 'train/wake',
    gateDrafts: (env.GATE_DRAFTS || 'true') === 'true',
    budgetMs,
    leaseMs: budgetMs,                      // reporting is inside the budget, never a second lease knob
    deployRetryMs: number('DEPLOY_RETRY_S', 15) * 1000,
    runnerStaleMs: number('RUNNER_STALE_S', 180) * 1000,
    runnerForgetMs: number('RUNNER_FORGET_S', 86400) * 1000,
    sweepMs: number('SWEEP_S', 900) * 1000,
    keepJobs: number('KEEP_JOBS', 200),
    jobTtlMs: number('JOB_TTL_S', 3600) * 1000,
    keepLog: number('KEEP_LOG', 300),
    keepDeliveries: number('KEEP_DELIVERIES', 1000),
    keepMerges: number('KEEP_MERGES', 100),
    keepEvents: number('KEEP_EVENTS', 50000),
    tailCache: number('TAIL_CACHE', 8000),
    rowsFlushMs: number('ROWS_FLUSH_S', 300) * 1000,
    eventsPage: number('EVENTS_PAGE', 500),
    quantiles: (env.QUANTILES || '0.5,0.95').split(',').map(Number),
  };
}

const iso = (ms) => new Date(ms).toISOString();
const RUNNER_NAME_MAX = 100;
const KEEP_REFUSED = 10;

export function runnerName(value) {
  // A runner is keyed by its name: anything but a short non-empty string would be stored as "[object Object]" (F19).
  return typeof value === 'string' && value.trim() && value.length <= RUNNER_NAME_MAX ? value : null;
}

export async function hmacHex(secret, body) {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' },
    false, ['sign']);
  const mac = await crypto.subtle.sign('HMAC', key, typeof body === 'string' ? new TextEncoder().encode(body) : body);
  return [...new Uint8Array(mac)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

export function same(left, right) {
  // constant time over the longer input: the length is not a timing oracle either
  const a = String(left || ''), b = String(right || '');
  let diff = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  return diff === 0;
}

export async function verify(secret, body, header) {
  if (!secret || !header || !header.startsWith('sha256=')) return false;
  return same(header.slice('sha256='.length), await hmacHex(secret, body));
}

export function eventsOfComment(body) {
  // The envelopes of a forge-events comment (forge_github.GitHubAdapter._render): JSON lines inside the fenced block.
  if (!body || !body.startsWith(MARKER)) return [];
  const found = [];
  let inside = false;
  for (const line of body.split('\n')) {
    if (line.startsWith(FENCE)) inside = !inside;
    else if (inside && line.trim()) {
      try { found.push(JSON.parse(line)); } catch { /* an unreadable line is not an event */ }
    }
  }
  return found;
}

export function job(kind, repo, pr, sha, reason, now, attempt = 1) {
  let id = ['sweep', 'deploy'].includes(kind) ? `${kind}:${(sha || iso(now)).toLowerCase().replace(/[^0-9a-z#.-]/g, '-')}` : `${kind}:${pr}#${sha}`;
  if (attempt > 1) id += `.${attempt}`;
  return { id, kind, repo, pr, sha: sha || null, source: 'control', reason, requested_at: iso(now), attempt };
}

export function jobsOfEnvelopes(envelopes, cfg, now) {
  // The jobs a list of forge-events envelopes asks for, and the facts it records. One rule, two doors: the GitHub
  // comment (jobsOf) and the engine's journal (POST /v1/events), so neither owns a second translation. Only pr.ready
  // makes work; pr.merged and the verdicts are facts; a type nobody names here is written down and does nothing.
  const jobs = [];
  const facts = [];
  for (const envelope of envelopes || []) {
    if (!envelope || typeof envelope !== 'object') continue;
    const body = envelope.payload || {};
    const at = envelope.occurred_at || iso(now);
    if (envelope.type === 'pr.ready' && Number.isInteger(body.pr) && body.sha) {
      jobs.push(job('train', cfg.repo, body.pr, body.sha, `pr.ready ${envelope.event_id || ''}`.trim(), now));
      facts.push({ fact: 'ready', pr: body.pr, sha: body.sha, at });
    } else if (envelope.type === 'pr.merged') {
      facts.push({ fact: 'merged', pr: body.pr, sha: body.sha, batch_id: body.batch_id || null, at });
    } else if (envelope.type === 'gate.passed' || envelope.type === 'gate.failed') {
      facts.push({ fact: 'verdict', pr: body.pr, sha: body.sha, passed: envelope.type === 'gate.passed', at });
    }
  }
  return { jobs, facts };
}

export function jobsOf(event, payload, cfg, now) {
  // The jobs a GitHub delivery asks for, the facts it records (ready, merged, verdict times), and the PRs whose queued
  // jobs it cancels: a closed PR, merged or not, has nothing left to gate or merge (F14).
  const facts = [];
  if (event === 'pull_request') {
    const pull = payload.pull_request || {};
    if (payload.action === 'closed' && Number.isInteger(pull.number)) {
      const sha = (pull.head || {}).sha || null;
      if (pull.merged === true) facts.push({ fact: 'merged', pr: pull.number, sha, batch_id: null, at: pull.merged_at || iso(now) });
      return { jobs: [], facts, cancels: [{ repo: cfg.repo, pr: pull.number }] };
    }
    const wanted = GATE_ACTIONS.includes(payload.action) && pull.state === 'open' && (pull.base || {}).ref === cfg.baseBranch
      && (cfg.gateDrafts || !pull.draft);
    if (wanted && payload.action === 'reopened') facts.push({ fact: 'reopened', repo: cfg.repo, pr: pull.number });
    if (wanted) facts.push({ fact: 'pushed', pr: pull.number, sha: pull.head.sha, at: iso(now) });
    return { jobs: wanted ? [job('gate', cfg.repo, pull.number, pull.head.sha, `pull_request ${payload.action}`, now)] : [], facts };
  }
  if (event === 'issue_comment' && payload.action === 'created') {
    const comment = payload.comment || {};
    if (!TRUSTED.includes(comment.author_association)) return { jobs: [], facts };
    return jobsOfEnvelopes(eventsOfComment(comment.body), cfg, now);
  }
  if (event === 'push') {
    if (payload.ref === `refs/heads/${cfg.wakeRef}`) {
      let record = {};
      try { record = JSON.parse(((payload.head_commit || {}).message || '').trim()); } catch { record = {}; }
      const ok = Number.isInteger(record.pr) && record.sha;
      return { jobs: ok ? [job('train', cfg.repo, record.pr, record.sha, `wake ${record.event_id || ''}`.trim(), now)] : [], facts };
    }
    if (payload.ref === `refs/heads/${cfg.baseBranch}` && payload.after) {
      return { jobs: ['deploy', 'sweep'].map((kind) => job(kind, cfg.repo, null, payload.after,
        `the base moved to ${payload.after}`, now)), facts };
    }
  }
  if (event === 'workflow_run' && payload.action === 'completed') {
    const run = payload.workflow_run || {};
    const ms = Date.parse(run.updated_at) - Date.parse(run.run_started_at || run.created_at);
    if (Number.isFinite(ms) && ms >= 0) facts.push({ fact: 'minutes', value: Math.ceil(ms / 60000), at: iso(now) });
  }
  return { jobs: [], facts };
}

// VAZÃO F34 (I-5102f4e9, SEMENTE §4 "cabe no plano gratuito, com folga"): the Free plan bills a Durable Object by the
// rows its storage reads, 5,000,000 a day, and on 03/11 the object ran out with no instrument saying so. Every storage
// read of a request goes through one metered view of the storage: a get of one key is 1 row, a get of N keys N rows, a
// list the entries it returned. handle() adds the rows to the store's per-hour meter (MemoryStore.read), and /status and
// /metrics expose them (rows_read). The caches keyed by storage (TAILS, WRITES) key on the storage under the view
// (unmetered), so a read through the view and one without it share them.
const METERS = new WeakMap();  // storage -> its metered view
const unmetered = (storage) => storage.unmetered || storage;

export function metered(given) {
  const storage = unmetered(given);
  let view = METERS.get(storage);
  if (view) return view;
  view = {
    unmetered: storage,
    pending: 0,
    drain() { const rows = this.pending; this.pending = 0; return rows; },
    async get(keys, options) {
      const found = await storage.get(keys, options);
      view.pending += Array.isArray(keys) ? keys.length : 1;
      return found;
    },
    async list(options) {
      const found = await storage.list(options);
      view.pending += found.size;
      return found;
    },
    put: (...args) => storage.put(...args),
    delete: (...args) => storage.delete(...args),
  };
  METERS.set(storage, view);
  return view;
}

const ROWS_KEEP_HOURS = 48;  // the meter keeps the per-hour rows of the last two days: today and yesterday, whole
const hourOf = (ms) => iso(ms).slice(0, 13);  // the UTC hour, 2026-11-03T18

// CANALE7 (CONTROL-CHANNEL): the engine's event log, one record per append, each under its own storage key (ev:<sequence>),
// so the store's dump stays small. A record is {seq, at, channel: {repo, pr}, events}; a read is paged by sequence; the
// oldest records past keepEvents are deleted on append. storage is the Durable Object's (get, put, list, delete).
export const EVENT_PREFIX = 'ev:';
const SEQ_KEY = 'ev_seq';
const DELETE_BATCH = 128;  // Durable Object storage deletes at most 128 keys a call

// VAZÃO F28 (I-5102f4e9): a windowed read listed `tail` rows of the Durable Object's storage every time, and the engine
// reads its config through a 2,000-record window, so the Free plan's 5,000,000 rows read a day ran out on 03/11. The newest
// records live in the object's memory as well: the first windowed read lists exactly the rows it would have anyway, every
// append extends it, and a later window no deeper than it is answered with no row read. A woken object starts empty.
const TAILS = new WeakMap();  // storage -> { records (oldest first), limit (the window it holds), whole (the entire log) }

export class EventLog {
  constructor(storage, cfg) { this.storage = storage; this.cfg = cfg; }

  static key(seq) { return EVENT_PREFIX + String(seq).padStart(12, '0'); }

  async append(channel, events, now) {
    const seq = ((await this.storage.get(SEQ_KEY)) || 0) + 1;
    const record = { seq, at: iso(now), channel, events };
    await this.storage.put({ [SEQ_KEY]: seq, [EventLog.key(seq)]: record });
    const held = TAILS.get(unmetered(this.storage));
    if (held) {
      held.records.push(structuredClone(record));
      if (held.records.length > held.limit) { held.records.shift(); held.whole = false; }
    }
    const drop = seq - this.cfg.keepEvents;
    if (drop > 0) {
      const old = await this.storage.list({ prefix: EVENT_PREFIX, end: EventLog.key(drop + 1), limit: DELETE_BATCH });
      if (old.size) await this.storage.delete([...old.keys()]);
    }
    return seq;
  }

  async read(channel, { since = 0, tail = 0 } = {}) {
    const mine = (record) => record.channel.repo === channel.repo && (record.channel.pr ?? null) === (channel.pr ?? null);
    if (tail > 0) {  // the newest `tail` records of the whole log, oldest first: the windowed read
      let held = TAILS.get(unmetered(this.storage));
      if (!held || tail > held.limit) {
        const found = await this.storage.list({ prefix: EVENT_PREFIX, reverse: true, limit: tail });
        held = { records: [...found.values()].reverse(), limit: tail, whole: found.size < tail };
        if (tail <= this.cfg.tailCache) TAILS.set(unmetered(this.storage), held);
      }
      const records = held.records.slice(-tail);
      return { records: records.filter(mine), next: records.length ? records[records.length - 1].seq : since, more: false,
        complete: held.whole && held.records.length < tail };
    }
    const found = await this.storage.list({ prefix: EVENT_PREFIX, start: EventLog.key(since + 1), limit: this.cfg.eventsPage });
    const records = [...found.values()];
    return { records: records.filter(mine), next: records.length ? records[records.length - 1].seq : since,
      more: found.size === this.cfg.eventsPage, complete: true };
  }
}

// VAZÃO F35 (I-5102f4e9, SEMENTE §4 "cabe no plano gratuito, com folga"): the engine's config overrides as ONE storage
// key per repository, {version, overrides, through, at}. A config read is one storage get (one row), never a window of
// the event log; a write is compare-and-set on `version` (a stale version gets 409 with the current snapshot), so two
// writers never lose each other's change. The config.changed events stay on the event log as history and audit. The
// get and the put run inside one request of the single Durable Object, whose input gate keeps them one step.
export const CONFIG_PREFIX = 'cfg:';
const CONFIG_EMPTY = { version: 0, overrides: {}, through: null, at: null };  // no snapshot yet: the client migrates
const CONFIG_MAX_BYTES = 131072;  // a Durable Object value holds at most 128 KiB
const WRITES = new WeakMap();  // storage -> the promise of its last config write

export class ConfigKey {
  constructor(storage) { this.storage = storage; }

  static key(repo) { return CONFIG_PREFIX + repo; }

  async read(repo) {
    return (await this.storage.get(ConfigKey.key(repo))) || CONFIG_EMPTY;
  }

  // {written: true, snapshot} with the next version, or {written: false, snapshot: the current one} when `version` is
  // stale. The writes of one storage run one after another (WRITES), so the compare and the put are one step even
  // where no input gate holds the object (a test's storage, a future runtime).
  write(repo, version, overrides, through, now) {
    const step = async () => {
      const current = await this.read(repo);
      if (current.version !== version) return { written: false, snapshot: current };
      const snapshot = { version: version + 1, overrides, through, at: iso(now) };
      await this.storage.put({ [ConfigKey.key(repo)]: snapshot });
      return { written: true, snapshot };
    };
    const done = (WRITES.get(unmetered(this.storage)) || Promise.resolve()).then(step, step);
    WRITES.set(unmetered(this.storage), done.catch(() => null));
    return done;
  }
}

async function configRoute(request, url, env, store, now, storage) {
  if (!env.EVENTS_TOKEN || !storage) return json({ error: 'the config snapshot is not configured (EVENTS_TOKEN)' }, 503);
  if (!bearer(request, env.EVENTS_TOKEN)) return json({ error: 'events token required' }, 401);
  const keyed = new ConfigKey(storage);
  if (request.method === 'GET') {
    const repo = url.searchParams.get('repo');
    if (!repo) return json({ error: 'repo required' }, 400);
    return json(await keyed.read(repo));
  }
  if (request.method !== 'POST') return json({ error: 'method not allowed' }, 405);
  const body = await request.json().catch(() => null);
  const plain = (value) => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
  if (!plain(body) || typeof body.repo !== 'string' || !body.repo || !Number.isInteger(body.version) || body.version < 0
      || !plain(body.overrides) || !(body.through === null || typeof body.through === 'string')) {
    return json({ error: 'body: {repo, version (the one read), overrides: {name: value}, through: event_id|null}' }, 400);
  }
  if (new TextEncoder().encode(JSON.stringify(body)).length > CONFIG_MAX_BYTES) return json({ error: 'overrides too large' }, 413);
  const done = await keyed.write(body.repo, body.version, body.overrides, body.through, now);
  store.count(done.written ? 'config_written_total' : 'config_conflicts_total');
  return done.written ? json(done.snapshot, 201) : json({ error: 'stale version', current: done.snapshot }, 409);
}

// ----------------------------------------------------------------------------------------------------------------
// ORIGIN (CANALE8): the forge the flow runs on now. A delivery is signed rather than shared-secret hashed: the header
// `webhook-signature` carries `v1ed,<base64>` over the lowercase hex SHA-256 digest of
// `{webhook-id}.{webhook-timestamp}.{body}`, verified against the Ed25519 keys published at /v1/origin/keys (no
// credential), cached in the isolate for the ten minutes /keys names, refreshed on a key that verifies nothing and
// kept one more window when a refresh fails. A delivery is handled once (webhook-id) and translated into the same jobs
// and facts the GitHub route makes; what it records lands on the engine's journal (/v1/events) as the port's envelopes
// (pr.opened, pr.pushed, pr.merged), on the repository channel and on the PR's -- never in a forge.
// ----------------------------------------------------------------------------------------------------------------
export const ORIGIN_KEYS_URL = 'https://api.cursor.com/v1/origin/keys';
export const ORIGIN_SKEW_S = 300;          // a delivery stamped more than five minutes from now is refused
export const ORIGIN_KEYS_TTL_MS = 600000;  // /keys answers max-age=600; a failed refresh keeps the last good keys
export const ORIGIN_PRODUCER = 'origin-webhook';

const PREMISES_LINE = /^Premises:[ \t]*(.*?)[ \t]*$/m;
const PREMISE_ID = /\bP-[0-9]{2,}\b/g;
const HEX40 = /^[0-9a-f]{40}$/;
const GATE_ORIGIN = ['pull_request.created', 'pull_request.reopened', 'pull_request.published',
  'pull_request.head_ref.pushed'];
const ORIGIN_NATURAL_KEY = {
  'pr.opened': ['repo', 'pr', 'sha'],
  'pr.pushed': ['repo', 'pr', 'sha'],
  'pr.merged': ['repo', 'pr', 'sha', 'merge_sha'],
  // One ref move is one record: the same triple from a redelivery has the same event_id (contracts/events/ref.updated).
  'ref.updated': ['repo', 'ref', 'before', 'after'],
};
const REF_NAME = /^refs\/heads\/[^\s]{1,240}$/;

export async function sha256Hex(text) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

export function premisesOf(body) {
  // The P-ids of the body's `Premises:` line (forge_events.premises_from_body): the journal carries what the PR says.
  const match = PREMISES_LINE.exec(body || '');
  return match ? [...new Set(match[1].match(PREMISE_ID) || [])] : [];
}

export async function originEnvelope(type, payload, { correlationId, occurredAt, producer = ORIGIN_PRODUCER }) {
  // contracts/events/envelope.v1.json: event_id is sha256 of producer, type and the natural key the schema names
  // (event_contracts.event_id -- json.dumps([producer, type, key], sort_keys, separators=(',', ':'))).
  const key = ORIGIN_NATURAL_KEY[type];
  if (!key) throw new Error(`no natural key for ${type}`);
  const envelope = { type, version: 1, occurred_at: occurredAt, producer, correlation_id: correlationId, payload };
  envelope.event_id = await sha256Hex(JSON.stringify([producer, type, key.map((name) => payload[name])]));
  return envelope;
}

function base64Bytes(text) {
  try { return Uint8Array.from(atob(text), (char) => char.charCodeAt(0)); } catch { return new Uint8Array(); }
}

export async function fetchOriginKeys(url = ORIGIN_KEYS_URL) {
  const response = await fetch(url, { headers: { accept: 'application/json' } });
  if (!response.ok) throw new Error(`origin keys answered ${response.status}`);
  const body = await response.json();
  return Array.isArray(body.keys) ? body.keys.filter((key) => key && key.kty === 'OKP' && key.x) : [];
}

const IMPORTED = new Map();
function importedKey(jwk) {
  // One import per published key, kept for the life of the isolate; a key the runtime refuses verifies nothing.
  if (!IMPORTED.has(jwk.x)) {
    IMPORTED.set(jwk.x, crypto.subtle.importKey('jwk', { kty: 'OKP', crv: 'Ed25519', x: jwk.x }, { name: 'Ed25519' },
      false, ['verify']).catch(() => { IMPORTED.delete(jwk.x); return null; }));
  }
  return IMPORTED.get(jwk.x);
}

export class KeyRing {
  constructor(load = fetchOriginKeys, ttl = ORIGIN_KEYS_TTL_MS) {
    this.load = load;
    this.ttl = ttl;
    this.keys = [];
    this.at = -Infinity;
    this.attempted = -Infinity;
    this.pending = null;
  }

  async reload(now) {
    // A load already in flight is shared. The five-second throttle only applies once that load has settled, so a
    // cold isolate does not refuse a second delivery that arrives while the first is still fetching /keys, and a
    // burst of bad signatures still does not hammer the endpoint.
    if (this.pending) return this.pending;
    if (now - this.attempted < 5000) return this.keys;
    this.attempted = now;
    const started = now;
    let settle;
    const done = new Promise((resolve) => { settle = resolve; });
    this.pending = done;
    try {
      const keys = (await Promise.resolve().then(() => this.load()).catch(() => [])) || [];
      if (keys.length) { this.keys = keys; this.at = started; }
    } finally {
      this.pending = null;
      settle(this.keys);
    }
    return this.keys;
  }

  async fresh(now) {
    if (this.keys.length && now - this.at <= this.ttl) return this.keys;
    return this.reload(now);
  }

  async verifies(signature, digest, now) {
    const message = new TextEncoder().encode(digest);
    for (const key of await this.fresh(now)) {
      const imported = await importedKey(key);
      if (!imported) continue;
      try {
        if (await crypto.subtle.verify({ name: 'Ed25519' }, imported, signature, message)) return true;
      } catch { /* a key this runtime cannot use verifies nothing */ }
    }
    return false;
  }
}

export const ORIGIN_RING = new KeyRing();

export async function verifyOrigin(headers, body, now, ring = ORIGIN_RING) {
  // The signature is checked on the raw body, before it is parsed, and only over the digest Origin signs.
  const id = headers.get('webhook-id') || '';
  const timestamp = Number(headers.get('webhook-timestamp') || NaN);
  const entry = (headers.get('webhook-signature') || '').split(/\s+/).find((item) => item.startsWith('v1ed,'));
  if (!id || !entry || !Number.isInteger(timestamp)) return { ok: false, id, reason: 'missing webhook headers' };
  if (Math.abs(Math.floor(now / 1000) - timestamp) > ORIGIN_SKEW_S) return { ok: false, id, reason: 'stale timestamp' };
  const signature = base64Bytes(entry.slice('v1ed,'.length));
  if (!signature.length) return { ok: false, id, reason: 'bad signature encoding' };
  const digest = await sha256Hex(`${id}.${timestamp}.${body}`);
  if (await ring.verifies(signature, digest, now)) return { ok: true, id };
  await ring.reload(now);  // a rotation retired the key that signed this: one refresh, then the keys on hand
  if (await ring.verifies(signature, digest, now)) return { ok: true, id };
  return { ok: false, id, reason: 'no published key verifies the delivery' };
}

export function originRepo(payload) {
  // The body is authoritative: owner slug and repository name, which is the name the journal's channel carries.
  const repository = payload.repository || ((payload.pullRequest || {}).repository) || {};
  const owner = (repository.owner || {}).slug;
  return owner && repository.name ? `${owner}/${repository.name}` : null;
}

export async function originOf(type, payload, event, cfg, now) {
  // The jobs, the facts, the journal envelopes and the cancels one Origin event asks for: a PR opened, republished,
  // reopened or pushed on the base is a gate job of its head; a merge is a merge fact; a PR merged or closed cancels its
  // queued jobs; a push to the base is a sweep; a push to the wake ref is a train job of the record it carries.
  const jobs = [];
  const facts = [];
  const events = [];
  const cancels = [];
  const at = Number.isFinite(Date.parse((event || {}).eventTime || '')) ? new Date(Date.parse(event.eventTime)).toISOString() : iso(now);
  const correlationId = ((event || {}).id || `${type || 'origin'}@${at}`).slice(0, 200);
  const journal = async (kind, body) => {
    const envelope = await originEnvelope(kind, body, { correlationId, occurredAt: at });
    events.push({ channel: { repo: body.repo, pr: null }, envelope });
    if (body.pr !== null) events.push({ channel: { repo: body.repo, pr: body.pr }, envelope });
  };
  const pull = (payload || {}).pullRequest || {};
  const repo = originRepo(payload || {});
  const number = Number(pull.number);
  if (repo && Number.isInteger(number) && number > 0 && String(type || '').startsWith('pull_request.')) {
    const head = pull.head || {};
    const base = pull.base || {};
    const subject = { repo, pr: number, sha: head.sha || null, unit: null, premises: premisesOf(pull.body) };
    const sha = HEX40.test(head.sha || '');
    if (type === 'pull_request.created') {
      if (sha && HEX40.test(base.sha || '')) {
        await journal('pr.opened', { ...subject, base_sha: base.sha, lane_id: null, units: [] });
      } else if (sha) {
        await journal('pr.pushed', subject);
      }
    } else if (type === 'pull_request.head_ref.pushed' || type === 'pull_request.reopened' || type === 'pull_request.published') {
      if (sha) await journal('pr.pushed', subject);
    } else if (type === 'pull_request.merged') {
      facts.push({ fact: 'merged', repo, pr: number, sha: head.sha || null, batch_id: null, at });
      if (sha && HEX40.test(pull.mergeCommitSha || '')) {
        await journal('pr.merged', { ...subject, merge_sha: pull.mergeCommitSha, batch_id: null });
      }
    }
    if (type === 'pull_request.merged' || type === 'pull_request.closed') cancels.push({ repo, pr: number });
    const wanted = GATE_ORIGIN.includes(type) && sha && pull.state === 'open' && base.ref === cfg.baseBranch
      && (cfg.gateDrafts || !pull.draft);
    if (wanted) {
      if (type === 'pull_request.reopened') facts.push({ fact: 'reopened', repo, pr: number });
      jobs.push(job('gate', repo, number, head.sha, `origin ${type}`, now));  // the repository the delivery names
      facts.push({ fact: 'pushed', pr: number, sha: head.sha, at });
    }
    return { jobs, facts, events, cancels };
  }
  if (type === 'repository.pushed' && repo) {
    const pushedAt = Number.isFinite(Date.parse(payload.pushedAt || '')) ? new Date(Date.parse(payload.pushedAt)).toISOString() : at;
    for (const update of Array.isArray(payload.refUpdates) ? payload.refUpdates : []) {
      if (!update) continue;
      if (REF_NAME.test(update.ref || '') && HEX40.test(update.before || '') && HEX40.test(update.after || '')) {
        // The ref triple, journaled at its source (ref.updated): on the repository channel only. A push that a PR head
        // also reports (pull_request.head_ref.pushed) journals pr.pushed and no ref record, so it is counted once. A
        // malformed update journals nothing, and the Origin adapter then refuses for want of a record.
        const record = { repo, ref: update.ref, before: update.before, after: update.after, created: update.created === true,
          deleted: update.deleted === true, forced: update.forced === true, pushed_at: pushedAt, pr: null, sha: update.after,
          unit: null, premises: [] };
        events.push({ channel: { repo, pr: null }, envelope: await originEnvelope('ref.updated', record, { correlationId, occurredAt: at }) });
      }
      if (update.deleted) continue;
      const after = update.after || '';
      if (update.ref === `refs/heads/${cfg.baseBranch}` && HEX40.test(after)) {
        jobs.push(job('deploy', repo, null, after, `the base moved to ${after}`, now));
        jobs.push(job('sweep', repo, null, after, `the base moved to ${after}`, now));
      }
      if (update.ref === `refs/heads/${cfg.wakeRef}`) {
        let record = {};
        try { record = JSON.parse(((update.headCommit || {}).message || '').trim()); } catch { record = {}; }
        if (Number.isInteger(record.pr) && record.sha) {
          jobs.push(job('train', repo, record.pr, record.sha, `wake ${record.event_id || ''}`.trim(), now));
        }
      }
    }
  }
  return { jobs, facts, events, cancels };
}

function channelOf(repo, pr) {
  return { repo, pr: pr === null || pr === undefined || pr === '' || pr === 'null' ? null : Number(pr) };
}

export class MemoryStore {
  // The whole state as plain data (index.js keeps it in Durable Object storage under these keys).
  static KEYS = ['jobs', 'deliveries', 'log', 'switches', 'runners', 'facts', 'counters', 'refused', 'closed', 'rows'];

  constructor(data = {}) {
    this.jobs = data.jobs || [];
    this.deliveries = data.deliveries || [];
    this.logLines = data.log || [];
    this.switches = data.switches || { paused: false };
    this.runners = data.runners || {};
    this.facts = data.facts || { pushed: {}, ready: {}, merges: [], verdicts: [], minutes: [] };
    this.counters = data.counters || {};
    this.refused = data.refused || {};  // runner name -> {at, path} of its last refused token (F17)
    this.closed = data.closed || {};    // terminal PR barrier: late ready/push events cannot resurrect its work
    // F34: storage rows read per UTC hour ({since: the first hour metered, hours: {'2026-11-03T18': rows}}). A read does
    // not make the store dirty: rewriting the whole dump on every read request would spend the rows-written limit, so
    // the meter rides on the next dump and is otherwise written alone at most once every rowsFlushMs (flush).
    this.rows = data.rows || { since: null, hours: {} };
    this.rowsPending = false;
    this.rowsSavedAt = -Infinity;
    this.dirty = false;
  }

  dump() {
    return { jobs: this.jobs, deliveries: this.deliveries, log: this.logLines, switches: this.switches,
      runners: this.runners, facts: this.facts, counters: this.counters, refused: this.refused, closed: this.closed,
      rows: this.rows };
  }

  // F34: `rows` storage rows read at `now`, on the meter's UTC hour.
  read(rows, now) {
    if (!(rows > 0)) return;
    const hour = hourOf(now);
    if (!(hour in this.rows.hours)) {
      const oldest = hourOf(now - (ROWS_KEEP_HOURS - 1) * 3600000);
      for (const held of Object.keys(this.rows.hours)) if (held < oldest) delete this.rows.hours[held];
      this.rows.hours[hour] = 0;
    }
    this.rows.hours[hour] += rows;
    this.rows.since = this.rows.since || hour;
    this.rowsPending = true;
  }

  // The storage entries to write after a request, or null: the whole dump when the state changed, else the meter alone
  // when it has rows not yet written and its last write is rowsFlushMs old (at most one row written per window).
  flush(now, cfg) {
    let entries = null;
    if (this.dirty) entries = this.dump();
    else if (this.rowsPending && !(now - this.rowsSavedAt < cfg.rowsFlushMs)) entries = { rows: this.rows };
    if (entries) { this.dirty = false; this.rowsPending = false; this.rowsSavedAt = now; }
    return entries;
  }

  // The write of flush()'s entries failed: the next request writes them again.
  unsaved(entries) {
    if ('jobs' in entries) this.dirty = true;
    this.rowsPending = true;
    this.rowsSavedAt = -Infinity;
  }

  count(name, by = 1) { this.counters[name] = (this.counters[name] || 0) + by; this.dirty = true; }

  log(kind, detail, now, cfg) {
    this.logLines.push({ at: iso(now), kind, ...detail });
    this.logLines = this.logLines.slice(-cfg.keepLog);
    this.dirty = true;
  }

  seen(delivery) { return this.deliveries.includes(delivery); }

  remember(delivery, cfg) {
    this.deliveries.push(delivery);
    this.deliveries = this.deliveries.slice(-cfg.keepDeliveries);
    this.dirty = true;
  }

  enqueue(item, cfg) {
    if (this.closed[`${item.repo}#${item.pr}`]) {
      this.count('jobs_closed_ignored_total');
      return false;
    }
    if (this.jobs.some((held) => held.id === item.id)) return false;
    if (item.kind === 'deploy') {
      this.jobs = this.jobs.filter((held) => !(held.kind === 'deploy' && held.state === 'queued'));
    }
    // Supersession: a newer head makes the older queued jobs of the same kind and PR redundant. A leased or
    // cancelling job is running (or being stopped) and is never touched.
    if (item.pr !== null && item.pr !== undefined) {
      const before = this.jobs.length;
      this.jobs = this.jobs.filter((held) => !(held.state === 'queued' && held.kind === item.kind && held.pr === item.pr
        && held.sha !== item.sha));
      if (before > this.jobs.length) this.count('jobs_superseded_total', before - this.jobs.length);
    }
    this.jobs.push({ ...item, state: 'queued', runner: null, lease_until: null, outcome: null });
    const live = this.jobs.filter((held) => ['queued', 'leased', 'cancelling'].includes(held.state));
    const done = this.jobs.filter((held) => !live.includes(held));
    // slice(-0) is slice(0), the whole array: an exhausted budget must keep no history at all.
    const room = Math.max(0, cfg.keepJobs - live.length);
    this.jobs = [...(room > 0 ? done.slice(-room) : []), ...live];
    this.dirty = true;
    return true;
  }

  // Run first on every request (handle) and on the cron tick, so nothing reads dead work (F15):
  // - a leased or cancelling job whose lease ended is done, outcome died: its runner had the whole budget and said
  //   nothing, and running it again would re-run work nobody asked for twice (F12, F13: gates of PRs merged days before);
  // - a queued job nobody claimed within jobTtlMs is discarded;
  // - a runner silent for runnerForgetMs is forgotten, so a name that left does not warn forever (F19).
  expire(now, cfg) {
    let died = 0;
    for (const item of this.jobs) {
      if (!['leased', 'cancelling'].includes(item.state) || !(item.lease_until <= now)) continue;
      this.die(item, now, cfg);
      died += 1;
    }
    let dropped = 0;
    if (cfg.jobTtlMs > 0) {
      const before = this.jobs.length;
      this.jobs = this.jobs.filter((item) => !(item.state === 'queued' && Date.parse(item.requested_at) < now - cfg.jobTtlMs));
      dropped = before - this.jobs.length;
      if (dropped) this.count('jobs_expired_total', dropped);
    }
    let forgotten = 0;
    for (const [name, runner] of Object.entries(this.runners)) {
      if (!(Date.parse(runner.heartbeat) >= now - cfg.runnerForgetMs)) { delete this.runners[name]; forgotten += 1; }
    }
    if (forgotten) this.dirty = true;
    return { died, dropped, forgotten };
  }

  die(item, now, cfg) {
    // The result the runner never sent, written the way a runner writes one (contracts/service/result.v1.json).
    const budget = cfg.budgetMs / 1000;
    const claimed = item.claimed_at ?? item.lease_until - cfg.leaseMs;
    const result = { job: item.id, outcome: 'died',
      reason: `the lease ended with no result from runner ${item.runner} (budget ${budget} s including reporting)`,
      runner: { name: item.runner, kind: (this.runners[item.runner] || {}).kind || 'other' },
      started_at: iso(claimed), finished_at: iso(item.lease_until), duration_s: (item.lease_until - claimed) / 1000,
      phases: [], exit: null, verdict_event: null, log_tail: '' };
    Object.assign(item, { state: 'done', outcome: 'died', result });
    this.count('jobs_died_total');
    this.log('died', { job: item.id, runner: item.runner, lease_until: iso(item.lease_until) }, now, cfg);
    if (this.runners[item.runner]?.job === item.id) this.runners[item.runner].job = null;
    this.retryDeploy(item, now, cfg);
  }

  retryDeploy(item, now, cfg) {
    if (item.kind !== 'deploy' || item.outcome === 'passed' ||
        this.jobs.some((held) => held.kind === 'deploy' && ['queued', 'leased'].includes(held.state))) return;
    const retry = job('deploy', item.repo, null, item.sha, `retry after ${item.outcome}`, now, (item.attempt || 1) + 1);
    this.enqueue({ ...retry, not_before: now + cfg.deployRetryMs }, cfg);
  }

  claim(runner, kinds, now, cfg) {
    // Only a queued job: an ended lease is a died result (expire), never free work.
    if (this.switches.paused) return null;
    const order = (item) => CLAIM_ORDER.indexOf(item.kind);
    const free = this.jobs.filter((item) => kinds.includes(item.kind) && item.state === 'queued' && !(item.not_before > now));
    free.sort((a, b) => order(a) - order(b) || a.requested_at.localeCompare(b.requested_at));
    const item = free[0];
    if (!item) return null;
    Object.assign(item, { state: 'leased', runner: runner.name, claimed_at: now, lease_until: now + cfg.leaseMs });
    this.beat(runner, item.id, now);
    this.dirty = true;
    return item;
  }

  beat(runner, jobId, now) {
    this.runners[runner.name] = { name: runner.name, kind: runner.kind || 'other', heartbeat: iso(now), job: jobId || null };
    this.dirty = true;
  }

  heartbeat(name, jobId, now) {
    // A beat renews nothing (D-291): the lease is the budget, and a job that needs longer is over budget, not alive.
    const item = this.jobs.find((held) => held.id === jobId && held.runner === name);
    this.beat({ name, kind: (this.runners[name] || {}).kind }, jobId, now);
    return { cancel: Boolean(item && item.state === 'cancelling') };
  }

  finish(result, now, cfg) {
    // Only a running job takes a result: one that died, was cancelled or never ran keeps the result it has.
    const item = this.jobs.find((held) => held.id === result.job);
    if (!item) return null;
    if (!['leased', 'cancelling'].includes(item.state)) return { taken: false, state: item.outcome || item.state };
    if (result.runner?.name !== item.runner) return { taken: false, state: 'held by another runner' };
    Object.assign(item, { state: 'done', outcome: result.outcome, lease_until: null, result });
    this.dirty = true;
    if (this.runners[item.runner]?.job === item.id) this.runners[item.runner].job = null;
    this.retryDeploy(item, now, cfg);
    return { taken: true };
  }

  close(repo, pr, now, cfg) {
    // A closed or merged PR: its queued jobs are cancelled; a leased one finishes within its budget.
    const cancelled = [];
    this.closed[`${repo}#${pr}`] = true;
    this.dirty = true;
    for (const item of this.jobs) {
      if (item.state === 'queued' && item.repo === repo && item.pr === pr) { item.state = 'cancelled'; cancelled.push(item.id); }
    }
    if (cancelled.length) {
      this.count('jobs_cancelled_total', cancelled.length);
      this.log('cancelled', { repo, pr, jobs: cancelled, reason: 'the PR closed' }, now, cfg);
    }
    return cancelled;
  }

  refuse(name, path, now) {
    // A runner whose token was refused (F17): the newest KEEP_REFUSED names, until that name authenticates again.
    this.count('runner_refused_total');
    if (!name) return;
    const others = Object.entries(this.refused).filter(([held]) => held !== name)
      .sort((a, b) => b[1].at.localeCompare(a[1].at));
    this.refused = Object.fromEntries([[name, { at: iso(now), path }], ...others].slice(0, KEEP_REFUSED));
  }

  accepted(name) {
    if (name && this.refused[name]) { delete this.refused[name]; this.dirty = true; }
  }

  cancel(pr) {
    let changed = 0;
    for (const item of this.jobs) {
      if (item.pr !== pr) continue;
      if (item.state === 'queued') { item.state = 'cancelled'; changed += 1; }
      if (item.state === 'leased') { item.state = 'cancelling'; changed += 1; }
    }
    this.dirty = true;
    return changed;
  }

  requeue(pr, sha, reason, now, cfg) {
    const last = [...this.jobs].reverse().find((item) => item.kind === 'gate' && item.pr === pr && (!sha || item.sha === sha));
    const head = sha || (last && last.sha);
    if (!head) return null;
    const attempts = this.jobs.filter((item) => item.kind === 'gate' && item.pr === pr && item.sha === head).length;
    const item = job('gate', cfg.repo, pr, head, `requeued: ${reason}`, now, attempts + 1);
    this.enqueue({ ...item, source: 'admin' }, cfg);
    return item;
  }

  record(fact, cfg) {
    const facts = this.facts;
    if (fact.fact === 'merged') this.close(fact.repo || cfg.repo, fact.pr, Date.parse(fact.at), cfg);
    if (fact.fact === 'reopened') delete this.closed[`${fact.repo || cfg.repo}#${fact.pr}`];
    if (fact.fact === 'pushed') facts.pushed[`${fact.pr}#${fact.sha}`] = fact.at;
    if (fact.fact === 'ready') facts.ready[`${fact.pr}#${fact.sha}`] = fact.at;
    // One merge is one measure: the pull_request closed delivery and the pr.merged envelope can both report it.
    if (fact.fact === 'merged' && !facts.merges.some((held) => held.pr === fact.pr && held.sha === fact.sha)) {
      const ready = facts.ready[`${fact.pr}#${fact.sha}`];
      const seconds = ready ? (Date.parse(fact.at) - Date.parse(ready)) / 1000 : null;
      facts.merges = [...facts.merges, { pr: fact.pr, sha: fact.sha, batch_id: fact.batch_id, occurred_at: fact.at,
        green_to_merged_s: seconds }].slice(-cfg.keepMerges);
    }
    if (fact.fact === 'verdict') {
      const pushed = facts.pushed[`${fact.pr}#${fact.sha}`];
      const seconds = pushed ? (Date.parse(fact.at) - Date.parse(pushed)) / 1000 : null;
      facts.verdicts = [...facts.verdicts, { pr: fact.pr, sha: fact.sha, passed: fact.passed, at: fact.at,
        push_to_verdict_s: seconds }].slice(-cfg.keepMerges);
    }
    if (fact.fact === 'minutes') facts.minutes = [...facts.minutes, { at: fact.at, value: fact.value }].slice(-cfg.keepMerges);
    for (const key of ['pushed', 'ready']) {
      const entries = Object.entries(facts[key]);
      if (entries.length > cfg.keepDeliveries) facts[key] = Object.fromEntries(entries.slice(-cfg.keepDeliveries));
    }
    this.dirty = true;
  }

  tick(now, cfg) {
    // The alarm (cron): expire (a request does too), and queue a sweep when none ran within sweepMs.
    this.expire(now, cfg);
    const sweeps = this.jobs.filter((item) => item.kind === 'sweep');
    const recent = sweeps.some((item) => Date.parse(item.requested_at) > now - cfg.sweepMs);
    const swept = recent ? null : job('sweep', cfg.repo, null, null, 'the safety-net sweep (cron)', now);
    if (swept) this.enqueue(swept, cfg);
    this.dirty = true;
    return { swept: swept ? swept.id : null };
  }
}

function quantiles(values, shares) {
  const sorted = values.filter((value) => typeof value === 'number').sort((a, b) => a - b);
  if (!sorted.length) return {};
  return Object.fromEntries(shares.map((share) => [String(share),
    sorted[Math.min(sorted.length, Math.max(1, Math.ceil(share * sorted.length))) - 1]]));
}

export function status(store, cfg, now, env = {}) {
  const live = store.jobs.filter((item) => ['queued', 'leased', 'cancelling'].includes(item.state));
  const missing = missingSecrets(env);
  const checks = [
    { name: 'secrets', status: missing.length ? 'fail' : 'pass', detail: missing.length ? `missing ${missing.join(', ')}` : 'all set' },
    // A runner beats between jobs too, so silence past runnerStaleMs (not the lease, which is seconds) means it is gone.
    ...Object.values(store.runners).map((runner) => {
      const age = (now - Date.parse(runner.heartbeat)) / 1000;
      return { name: `runner ${runner.name}`, status: age > cfg.runnerStaleMs / 1000 ? 'warn' : 'pass', detail: `beat ${Math.round(age)} s ago` };
    }),
    ...Object.entries(store.refused).map(([name, seen]) => ({ name: `runner ${name} token`, status: 'fail',
      detail: `refused at ${seen.at} on ${seen.path}: its OU_RUNNER_TOKEN is not the Worker's RUNNER_TOKEN (rotated?); see service.credentials` })),
  ];
  if (store.switches.paused) checks.push({ name: 'paused', status: 'warn', detail: 'runners take no new job' });
  const worst = ['pass', 'warn', 'fail'].reduce((found, level) => (checks.some((check) => check.status === level) ? level : found), 'pass');
  return {
    at: iso(now),
    switches: { paused: Boolean(store.switches.paused), transport: 'control', train_switch: null, trigger_mode: null },
    train: { lock: null, wake: null },
    queue: live.filter((item) => item.pr !== null).map((item) => ({ pr: item.pr, sha: item.sha, woken_at: item.requested_at })),
    merges: [...store.facts.merges].reverse().slice(0, 20),
    runner: null,
    runners: Object.values(store.runners),
    refused: store.refused,
    deployed_tree: env.DEPLOYED_TREE || null,  // the git tree of services/control-plane this deploy uploaded
    jobs: live,
    window: { events: store.logLines.length, complete: true },
    health: { status: worst, checks },
    metrics: numbers(store, cfg, now),
  };
}

export function numbers(store, cfg, now) {
  const found = {};
  const put = (name, value, labels = {}) => { (found[name] = found[name] || []).push([labels, value]); };
  for (const [name, value] of Object.entries(store.counters)) put(name, value);
  for (const state of ['queued', 'leased', 'cancelling']) put('jobs', store.jobs.filter((item) => item.state === state).length, { state });
  for (const [share, value] of Object.entries(quantiles(store.facts.merges.map((item) => item.green_to_merged_s), cfg.quantiles))) {
    put('green_to_merged_seconds', value, { quantile: share });
  }
  for (const [share, value] of Object.entries(quantiles(store.facts.verdicts.map((item) => item.push_to_verdict_s), cfg.quantiles))) {
    put('push_to_verdict_seconds', value, { quantile: share });
  }
  const month = iso(now).slice(0, 7);
  put('actions_minutes_month', store.facts.minutes.filter((item) => item.at.startsWith(month)).reduce((sum, item) => sum + item.value, 0));
  for (const runner of Object.values(store.runners)) {
    put('runner_heartbeat_age_seconds', (now - Date.parse(runner.heartbeat)) / 1000, { runner: runner.name });
  }
  put('paused', store.switches.paused ? 1 : 0);
  // F34: storage rows read in the current UTC day, hour and the hour before it (SEMENTE §4, the Free plan's rows read)
  const hour = hourOf(now);
  const day = hour.slice(0, 10);
  const previous = hourOf(now - 3600000);
  const since = store.rows.since || hour;
  const today = Object.entries(store.rows.hours).filter(([held]) => held.startsWith(day)).reduce((sum, [, rows]) => sum + rows, 0);
  put('rows_read', today, { window: 'day', at: day, since });
  put('rows_read', store.rows.hours[hour] || 0, { window: 'hour', at: hour, since });
  put('rows_read', store.rows.hours[previous] || 0, { window: 'previous_hour', at: previous, since });
  return found;
}

export function prometheus(found) {
  const lines = ['# TYPE tower_up gauge', 'tower_up 1'];
  for (const [name, values] of Object.entries(found)) {
    lines.push(`# TYPE tower_${name} ${name.endsWith('_total') ? 'counter' : 'gauge'}`);
    for (const [labels, value] of values) {
      const text = Object.entries(labels).map(([key, item]) => `${key}="${String(item).replaceAll('"', '')}"`).join(',');
      lines.push(text ? `tower_${name}{${text}} ${value}` : `tower_${name} ${value}`);
    }
  }
  return `${lines.join('\n')}\n`;
}

export function missingSecrets(env) {
  return ['GITHUB_WEBHOOK_SECRET', 'ADMIN_TOKEN', 'RUNNER_TOKEN'].filter((name) => !env[name]);
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body, null, 1), { status, headers: { 'content-type': 'application/json' } });
}

function bearer(request, secret) {
  const header = request.headers.get('authorization') || '';
  return Boolean(secret) && header.startsWith('Bearer ') && same(header.slice('Bearer '.length), secret);
}

function page(document) {
  const escape = (text) => String(text).replace(/[&<>]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[char]);
  return new Response(`<!doctype html><meta charset="utf-8"><title>Tower control plane</title>
<style>body{font:14px system-ui;margin:16px;max-width:960px}pre{background:#f4f4f4;padding:8px;overflow:auto}</style>
<h1>Tower control plane</h1><p>Health: <b>${escape(document.health.status)}</b> · paused: ${document.switches.paused}
· queue: ${document.queue.length} · runners: ${document.runners.length}</p>
<p>Admin: <code>curl -X POST -H "authorization: Bearer $ADMIN_TOKEN" -d '{"action":"pause","reason":"why"}' /v1/admin</code>
(actions: pause, resume, requeue, cancel). Also <a href="/status">/status</a>, <a href="/metrics">/metrics</a>,
<a href="/events">/events</a>, <a href="/healthz">/healthz</a>, <a href="/readyz">/readyz</a>.</p>
<pre>${escape(JSON.stringify(document, null, 1))}</pre>`, { headers: { 'content-type': 'text/html; charset=utf-8' } });
}

// Every request's storage reads go through the storage's metered view and land on the store's meter when it ends.
export async function handle(request, env, store, now, storage = null) {
  const view = storage && metered(storage);
  try {
    return await route(request, env, store, now, view);
  } finally {
    if (view) store.read(view.drain(), now);
  }
}

async function route(request, env, store, now, storage) {
  const cfg = settings(env);
  const url = new URL(request.url);
  const path = url.pathname;
  store.expire(now, cfg);  // every route, reads included: no answer counts a dead lease as live work (F15)
  if (path === '/v1/config') return configRoute(request, url, env, store, now, storage);
  // F37 (D-299): the gate's check run, posted with the Origin app's token; 503 until ORIGIN_APP_* are set (checks.js)
  if (path === '/v1/check-run') return checkRunRoute(request, env, now, env.ORIGIN_FETCH || ((...args) => fetch(...args)), same);
  if (path === '/v1/events') {
    // CANALE7: the engine's event log; a token reads and writes it (EVENTS_TOKEN), and without the secret the route is off
    if (!env.EVENTS_TOKEN || !storage) return json({ error: 'the event log is not configured (EVENTS_TOKEN)' }, 503);
    if (!bearer(request, env.EVENTS_TOKEN)) return json({ error: 'events token required' }, 401);
    const log = new EventLog(storage, cfg);
    if (request.method === 'GET') {
      const repo = url.searchParams.get('repo');
      if (!repo) return json({ error: 'repo required' }, 400);
      const found = await log.read(channelOf(repo, url.searchParams.get('pr')), {
        since: Number(url.searchParams.get('since') || 0), tail: Number(url.searchParams.get('tail') || 0) });
      return json(found);
    }
    if (request.method !== 'POST') return json({ error: 'method not allowed' }, 405);
    const body = await request.json().catch(() => null);
    const events = body && Array.isArray(body.events) ? body.events : null;
    if (!body || !body.channel || !body.channel.repo || !events || !events.length || events.length > cfg.eventsPage
        || !events.every((item) => item && typeof item === 'object' && item.type)) {
      return json({ error: 'body: {channel: {repo, pr}, events: [envelope, ...]}, at most EVENTS_PAGE events' }, 400);
    }
    const channel = channelOf(body.channel.repo, body.channel.pr);
    const seq = await log.append(channel, events, now);  // the write comes first: a refused trigger never loses the event
    store.count('events_appended_total', events.length);
    // The journal is a trigger, not only a shelf: its envelopes make the same jobs and facts the forge-events comment
    // makes (jobsOfEnvelopes), so pr.ready wakes the train without anyone commenting on the PR. An event_id that was
    // already asked for asks for nothing again, in this batch or a later POST; the ring is the store's own "handled
    // once" one (seen/remember), under the ACTIONED prefix so it cannot be mistaken for a delivery id. Only an
    // envelope that asks for something enters it, which leaves the webhook's dedupe its room.
    const jobs = [];
    const facts = [];
    const handled = new Set();
    for (const envelope of events) {
      const asked = jobsOfEnvelopes([envelope], cfg, now);
      if (!asked.jobs.length && !asked.facts.length) continue;  // a type nobody names is written down and nothing more
      const mark = envelope.event_id ? ACTIONED + envelope.event_id : null;
      if (mark && (handled.has(mark) || store.seen(mark))) continue;
      if (mark) { handled.add(mark); store.remember(mark, cfg); }
      jobs.push(...asked.jobs);
      facts.push(...asked.facts);
    }
    for (const fact of facts) store.record(fact, cfg);
    const queued = jobs.filter((item) => store.enqueue(item, cfg)).map((item) => item.id);
    store.count('jobs_queued_total', queued.length);
    if (facts.length || queued.length) {
      store.log('events', { seq, repo: channel.repo, pr: channel.pr, queued, facts: facts.map((fact) => fact.fact) }, now, cfg);
    }
    return json({ seq, queued }, 201);
  }
  if (request.method === 'GET') {
    if (path === '/healthz') return new Response('ok\n');
    if (path === '/readyz') {
      const missing = missingSecrets(env);
      return missing.length ? json({ ready: false, missing }, 503) : json({ ready: true });
    }
    if (path === '/status') return json(status(store, cfg, now, env));
    if (path === '/metrics') return new Response(prometheus(numbers(store, cfg, now)), { headers: { 'content-type': 'text/plain; version=0.0.4' } });
    if (path === '/events') return json({ events: [...store.logLines].reverse() });
    if (path === '/') return page(status(store, cfg, now, env));
    return json({ error: 'not found' }, 404);
  }
  if (request.method !== 'POST') return json({ error: 'method not allowed' }, 405);
  if (path === '/webhook') {
    const body = await request.text();
    const delivery = request.headers.get('x-github-delivery') || '';
    const event = request.headers.get('x-github-event') || '';
    if (!(await verify(env.GITHUB_WEBHOOK_SECRET, body, request.headers.get('x-hub-signature-256')))) {
      store.count('webhook_refused_total');
      return json({ error: 'bad signature' }, 401);
    }
    if (!delivery || store.seen(delivery)) {
      store.count('webhook_duplicate_total');
      return json({ duplicate: true });
    }
    store.remember(delivery, cfg);
    store.count('webhook_deliveries_total');
    let payload;
    try { payload = JSON.parse(body); } catch { store.count('webhook_dead_letter_total'); return json({ error: 'not json' }, 400); }
    const { jobs, facts, cancels = [] } = jobsOf(event, payload, cfg, now);
    for (const fact of facts) store.record(fact, cfg);
    for (const { repo, pr } of cancels) store.close(repo, pr, now, cfg);
    const queued = jobs.filter((item) => store.enqueue(item, cfg)).map((item) => item.id);
    store.count('jobs_queued_total', queued.length);
    store.log('delivery', { delivery, event, action: payload.action || null, queued, facts: facts.map((fact) => fact.fact) }, now, cfg);
    return json({ queued }, 202);
  }
  if (path === '/webhook/origin') {
    // CANALE8: Origin's signed delivery. Verified on the raw body against the published Ed25519 keys, handled once per
    // webhook-id, then translated into the same jobs and facts the GitHub route makes -- and written to the journal.
    const body = await request.text();
    const checked = await verifyOrigin(request.headers, body, now, env.ORIGIN_RING || ORIGIN_RING);
    if (!checked.ok) {
      store.count('webhook_refused_total');
      store.log('refused', { source: 'origin', delivery: checked.id || '', reason: checked.reason }, now, cfg);
      return json({ error: 'bad signature' }, 401);
    }
    if (store.seen(checked.id)) {
      store.count('webhook_duplicate_total');
      return json({ duplicate: true });
    }
    let delivery;
    try { delivery = JSON.parse(body); } catch {
      store.count('webhook_dead_letter_total');
      return json({ error: 'not json' }, 400);
    }
    store.remember(checked.id, cfg);
    store.count('webhook_deliveries_total');
    const event = delivery.event || {};
    const type = request.headers.get('webhook-event-type') || event.type || '';
    const { jobs, facts, events, cancels } = await originOf(type, event.payload || {}, event, cfg, now);
    if (events.length && storage) {
      const log = new EventLog(storage, cfg);
      for (const { channel, envelope } of events) await log.append(channel, [envelope], now);
      store.count('events_appended_total', events.length);
    } else if (events.length) {
      store.count('webhook_dead_letter_total');  // without the storage the journal cannot be written: say so, not silently
      store.log('origin_journal_lost', { delivery: checked.id, type, events: events.length }, now, cfg);
    }
    for (const fact of facts) store.record(fact, cfg);
    for (const { repo, pr } of cancels) store.close(repo, pr, now, cfg);
    const queued = jobs.filter((item) => store.enqueue(item, cfg)).map((item) => item.id);
    store.count('jobs_queued_total', queued.length);
    store.log('delivery', { source: 'origin', delivery: checked.id, event: type, queued, facts: facts.map((item) => item.fact),
      recorded: events.length }, now, cfg);
    return json({ queued, recorded: events.length }, 202);
  }
  if (path.startsWith('/v1/runner/')) {
    const body = (await request.json().catch(() => null)) || {};
    // The name the body gives: a string on the heartbeat, runner.name on the claim and the result.
    const named = runnerName(typeof body.runner === 'string' ? body.runner : (body.runner || {}).name);
    if (!bearer(request, env.RUNNER_TOKEN)) {
      // A refused token has a voice (F17): the health names the runner until it authenticates again.
      store.refuse(named, path, now);
      store.log('runner_refused', { runner: named, path }, now, cfg);
      return json({ error: 'runner token required' }, 401);
    }
    store.accepted(named);
    if (path === '/v1/runner/claim') {
      const runner = body.runner || {};
      if (!runnerName(runner.name)) return json({ error: `runner.name must be a non-empty string of at most ${RUNNER_NAME_MAX} characters` }, 400);
      const kinds = (body.kinds || KINDS).filter((kind) => KINDS.includes(kind));
      const item = store.claim(runner, kinds, now, cfg);
      store.beat(runner, item ? item.id : null, now);
      if (!item) return new Response(null, { status: 204 });
      store.count('jobs_claimed_total');
      store.log('claimed', { job: item.id, runner: runner.name }, now, cfg);
      const { state, runner: holder, claimed_at: claimed, lease_until: lease, outcome, result, not_before: readyAt, ...document } = item;
      return json(document);
    }
    if (path === '/v1/runner/heartbeat') {
      if (!runnerName(body.runner)) return json({ error: `runner must be a non-empty string of at most ${RUNNER_NAME_MAX} characters` }, 400);
      return json(store.heartbeat(body.runner, body.job, now));
    }
    if (path === '/v1/runner/result') {
      const finished = store.finish(body, now, cfg);
      if (!finished) return json({ error: 'unknown job' }, 404);
      if (!finished.taken) {
        // Late: the lease ended first (died), or the job was cancelled. The definite result stands.
        store.count('results_late_total');
        store.log('late_result', { job: body.job, outcome: body.outcome, state: finished.state }, now, cfg);
        return json({ error: `job ${body.job} is already ${finished.state}` }, 409);
      }
      store.count(`jobs_${body.outcome}_total`);
      store.log('result', { job: body.job, outcome: body.outcome, duration_s: body.duration_s,
        reason: body.reason || '', phases: body.phases || [], started_at: body.started_at, finished_at: body.finished_at,
        verdict: body.verdict_event || null }, now, cfg);
      return json({ done: body.job });
    }
    return json({ error: 'not found' }, 404);
  }
  if (path === '/v1/admin') {
    if (!bearer(request, env.ADMIN_TOKEN)) return json({ error: 'admin token required' }, 401);
    const body = await request.json().catch(() => ({}));
    if (!body.reason) return json({ error: 'reason required' }, 400);
    let done;
    if (body.action === 'pause' || body.action === 'resume') {
      store.switches.paused = body.action === 'pause';
      done = `paused=${store.switches.paused}`;
    } else if (body.action === 'cancel' && Number.isInteger(body.pr)) {
      done = `cancelled ${store.cancel(body.pr)} job(s) of #${body.pr}`;
    } else if (body.action === 'requeue' && Number.isInteger(body.pr)) {
      const item = store.requeue(body.pr, body.sha || null, body.reason, now, cfg);
      done = item ? `queued ${item.id}` : `no head known for #${body.pr}`;
    } else {
      return json({ error: 'action must be pause, resume, requeue or cancel (requeue and cancel need pr)' }, 400);
    }
    store.count('admin_actions_total');
    store.log('admin', { action: body.action, pr: body.pr || null, reason: body.reason, done }, now, cfg);
    return json({ done });
  }
  if (path === '/internal/tick') {
    if (!bearer(request, env.ADMIN_TOKEN)) return json({ error: 'admin token required' }, 401);
    return json(store.tick(now, cfg));
  }
  return json({ error: 'not found' }, 404);
}

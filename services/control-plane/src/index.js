// The Cloudflare Worker `forge-webhook` (GATE-TRAIN-SERVICES, ADR-41, D-086): every request goes to the one Durable
// Object `Control`, the single writer of the queue, the leases, the switches and the event log (core.js). Every request
// expires first (a lease past the budget is a died result, D-291); the cron trigger (wrangler.toml) ticks it so the same
// expiry runs with no request and the safety-net sweep is queued. Every storage row read is metered (F34): the load
// here, and each request's reads through handle(); the meter is written with the state, or alone at most every
// ROWS_FLUSH_S, never on every read (the rows-written limit).
import { MemoryStore, handle, settings } from './core.js';

const NAME = 'control';

function control(env) {
  return env.CONTROL.get(env.CONTROL.idFromName(NAME));
}

export default {
  async fetch(request, env) {
    return control(env).fetch(request);
  },
  async scheduled(controller, env, ctx) {
    const tick = new Request('https://control.internal/internal/tick', {
      method: 'POST', headers: { authorization: `Bearer ${env.ADMIN_TOKEN || ''}` },
    });
    ctx.waitUntil(control(env).fetch(tick));
  },
};

export class Control {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
    this.store = null;
    ctx.blockConcurrencyWhile(async () => {
      const held = await ctx.storage.get(MemoryStore.KEYS);
      this.store = new MemoryStore(Object.fromEntries(held));
      this.store.read(MemoryStore.KEYS.length, Date.now());  // a get of N keys reads N rows
    });
  }

  async fetch(request) {
    const now = Date.now();
    const response = await handle(request, this.env, this.store, now, this.ctx.storage);
    const entries = this.store.flush(now, settings(this.env));
    if (entries) {
      try {
        await this.ctx.storage.put(entries);
      } catch (error) {
        this.store.unsaved(entries);
        throw error;
      }
    }
    return response;
  }
}

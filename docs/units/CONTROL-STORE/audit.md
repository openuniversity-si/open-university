# CONTROL-STORE audit

Measured 02/11 11:34 BRT on the live Worker `/status`: 1,058 jobs, all `queued`, none with a runner or outcome; 780 queue entries over 233 PRs (PR 1058 x21, PR 1081 x13).

## Findings (read from `services/control-plane/src/core.js` at base fab6e204d)
1. `Store.enqueue` retention: `done.slice(-Math.max(0, cfg.keepJobs - live.length))`. With live > keepJobs the argument is `-0`, `slice(-0)` is `slice(0)`: the whole history survives. Isolated: `[1,2,3,4,5].slice(-0).length === 5`.
2. No supersession: `enqueue` only dedupes on the exact id (`kind:pr#sha`), so each new head of a PR leaves the older queued job in place.
3. No TTL: `claim` and `tick` never look at `requested_at` of a queued job.
4. Existing test `events.test.mjs` "two pr.ready of different heads are two train jobs" encoded the no-supersession behavior; it contradicts finding 2's fix and is updated (the older train job of the same PR is stale by definition).
5. Out of scope, noted only: nothing consumes the queue (route swap is CONTROL-ROUTE). `service_runner.py` / `service_status.py` untouched.

## Causas raiz
### R1 retention inverted (bug local)
1. The queue grew far beyond keepJobs, so retention should have capped history at zero.
2. The budget expression is clamped to 0, and `slice(-0)` returns everything instead of nothing.
3. The code treats "negative index from the end" as correct for 0, an off-by-JS-semantics no test covered: the only retention case tested was under budget.
### R2 no job lifecycle beyond lease (mecanismo faltando)
1. 1,058 queued jobs sat unclaimed, 233 PRs behind 780 entries.
2. Nothing removes a queued job that is redundant (newer head) or old (nobody claimed it).
3. The store was designed around "a runner will claim promptly"; with no consumer there is no mechanism that bounds the queue by relevance or age, only by count (and the count path was broken, R1).

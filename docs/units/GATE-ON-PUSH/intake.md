# GATE-ON-PUSH — intake

Mini-program. Stages 1–2 of the unit flow (D-077, Padrão v6); the audit and the plan are separate products.

## Pedido
Daniel (CEO), 29/10/2026, via A Torre (paraphrased by the launcher, three points in his order):
1. The merge train must stop polling. When the gate posts a green verdict, that event directly enqueues the PR and
   triggers the train to merge it. The train acts on demand; polling stays only as a safety net. This is the core
   requirement.
2. Architecture principle: sessions only read and write text. Base updates, gate runs, verdicts and merges belong to a
   central service, not to AI sessions.
3. Merges take seconds, not tens of minutes.

## Intenção
A PR that the gate already judged green should land without anyone (a session, a loop, a person) having to notice it.
The flow should cost the forge a handful of calls per merge, not a scan of every open PR per minute, so the shared
quota stops being the thing that decides whether anything merges. Behind it is the program goal of
[reach-1000-prs-per-day](../../programs/reach-1000-prs-per-day/audit.md): at that rate a poller that re-reads the
world every minute cannot exist, and AI sessions spending turns on base merges and conflict resolution do not scale.

## Contexto
State on 29/10/2026, base `mod/roadmap-integration` at `cf6e8b42` (#808):

- **The train today.** One long Claude Code cloud session holds the train role and loops `scripts/train run` about
  once a minute (train.md, "The train-role session"). `train.trigger_mode` is
  `emit_only` (`config/registry/train.json`): the gate's `pr.ready` wakes nobody; the loop finds it. `scripts/train`
  is a new process each iteration, and a new process rebuilds the queue by full replay: `1 + 2 × open PRs` reads
  (`scripts/lib/train_queue.py` docstring; the incremental `events_since` path only helps inside one process). With
  67 open PRs (REST `pulls?state=open`, 29/10 ~22:10Z) that is ≥ 135 reads per iteration before comment pagination,
  ≈ 8,100 reads/h at one per minute, against a 5,000/h user-token budget shared with every gate and session.
- **Quota exhaustion, twice.** Reported by Daniel at 16:55 and 18:30 BRT (19:55Z, 21:30Z): the train kept its git lock
  (`train/lock`, forge_git_ref) but could
  not admit anything, and once the session exited, stalling the flow. No forge event records either exhaustion: there
  is no event type for it in `contracts/events/`.
- **#808, green to merged in 16m51s.** Forge events on the PR: `gate.passed` v4 on `0e7c178b` at 21:19:14Z (18:19 BRT;
  [comment](https://github.com/openuniversity-si/open-university/pull/808#issuecomment-6508581867)), `pr.ready` at 21:19:32Z,
  `train.batch.started` `b-61606d63c492` at 21:21:56Z on #548, `pr.merged` at 21:36:07Z (merged_at 21:36:05Z, 18:36
  BRT; [comment](https://github.com/openuniversity-si/open-university/pull/808#issuecomment-6508888854)). The 17 minutes are mostly not
  polling: the verdict was refused on toolchain (D-072 nº 2, the gate attests without the shared store's overrides, the
  train with them), the PR took `train.verdict_fallback=tier2`, a full tier-2 gate ran on the combined head, and the
  run first failed reading #548 (2,008 comments, over `forge-events.github_max_pages` 20;
  [note](https://github.com/openuniversity-si/open-university/issues/548#issuecomment-6508742753)). Score of the day per the train
  session: 5 merges (#802, #806, #805, #663, #808), all by tier-2 batch, none by verdict (`v-…`)
  ([note](https://github.com/openuniversity-si/open-university/issues/548#issuecomment-6509003127)).
- **Other stalls the same day on #548.** 19:40Z the train container restarted
  ([note](https://github.com/openuniversity-si/open-university/issues/548#issuecomment-6506810932)); 21:16–21:17Z the config store
  could not be read (no `config.snapshot` in the newest 20-page window;
  [note](https://github.com/openuniversity-si/open-university/issues/548#issuecomment-6508558797)).
- **Textual conflicts after every merge.** `docs/domain/DECISIONS.md` changed in 110 commits since 22/10; 57 merge
  commits of the base into a PR head in the same window. After #808, #809 and #810 conflict only in `DECISIONS.md`
  (#811 body). The train's resync merges the tip into a head and regenerates generated files
  (`.gitattributes`: `CODEOWNERS` and `apps/web/tsconfig.paths.json` use `merge=regenerate`); any other textual conflict
  goes back to the owner session as `pr.conflicted` cause `textual`, and an AI session resolves it.
- **Transport.** Events are PR comments and comments on the repository channel issue #548 (`forge-events.github_log_issue`),
  read through `scripts/lib/forge_events.py`; the config shared store is `config.changed`/`config.snapshot` on the same
  issue, read at most once per `config.store_cache_ttl_s` (60 s) per checkout. [EVENTS.md "Scale"](../../process/EVENTS.md#scale)
  already names the 10x transport as "webhook receiver with a queue" and "one identity per role".
- **Constraints of the cloud session** (train.md):
  the egress proxy refuses REST git-data, `statuses`, `check-runs` and `merges` writes; it permits
  `PUT pulls/<n>/merge`, issue comments and ref create/fast-forward over git. No GitHub Actions or third-party CI
  (AGENTS.md).
- Related open work: #811 (DOCS-API, intake and research on repo-resident state such as `DECISIONS.md`), #807
  (TRAIN-RESYNC-TOOLCHAIN, D-078).

## Regras
- Padrão v6: [intake-and-research](../../padrao/v6/intake-and-research.md) (D-077; stages decoupled, this file does not
  dictate the research or the audit), `gate-verdict`, `effort`, `retro-before-merge`, `decide-then-report`.
- D-065 (events, never a clock; the train is the only merger, V3), D-069 item 5 (switches through the shared store,
  never a local override), D-054 (production frozen; the train merges only into `mod/roadmap-integration`), D-055 (no
  review step), D-025 (commit plan; a gate change cites an approved D-NNN).
- Admission: D-075 (verdict admission, strict and shard), D-079 (dual verdict for a toolchain-changing PR), D-072
  (blocking evaluation and fallback). Premises P-53 (tested tree is the merged tree), P-43 (cold, no box-local
  markers), P-46 (the pinned gate judges).
- Contracts: the forge-events envelope and schemas in `contracts/events/` (`gate.passed` v4, `pr.ready` v1,
  `pr.merged` v1, `pr.conflicted` v2, `train.*`), changed only additively (EVENTS.md "Scale"); the config shared store
  (`config.store_adapter` `github`, D-068).
- train.md: only the train-role cloud session runs `scripts/train run`; nobody else does,
  and never from the box.

## Problema real
A green verdict does not cause a merge: the only path from `gate.passed` to `pr.merged` is a session that re-reads every
open PR once a minute on a shared user token, so latency is the poll plus whatever that loop meets (fallback tier 2, a
full channel read, a lost session), and the quota it burns stops the flow.

Resolved when, measured from forge events over a working day:
- p50 time from `gate.passed` to `pr.merged` for a strictly admissible PR ≤ 60 s, p95 ≤ 5 min (today #808: 16m51s;
  every merge of 29/10 went through tier 2);
- forge API calls attributable to the train ≤ 20 per merged PR, and none while the queue is empty (today ≥ 135 per
  iteration, one iteration per minute, whether or not anything is queued);
- zero stalls caused by quota (no admissible PR waits because a budget is spent) and zero merges that need an AI
  session to start a loop or resolve a mechanical conflict;
- the polling path still exists and catches a lost event, and the audit can count how often it was the one that merged.

## Lacunas
- **Identity.** Whether a GitHub App installation token (separate budget) is available for the train/gate: the user
  token's limit is 5,000/h, while a call from this session reported `limit 15000` on `rate_limit`, so the identity in
  use differs between surfaces. Depends on Daniel (App install and secret), and on what the Claude Code proxy injects.
- **Where a central service runs.** No GitHub Actions, no third-party CI, production frozen; whether a small always-on
  host (or Cursor Origin, the destination forge) may receive webhooks is Daniel's call.
- **Quota evidence.** The two exhaustions are known from Daniel's report, not from a forge event; the exact reset
  times and which caller spent the budget are not recorded anywhere I can read.
- **"Seconds".** Whether "seconds" means the merge call after admission, or green-verdict-to-merge including a needed
  re-verdict on a moved tip. The metric above assumes the first for a strictly admissible PR; only Daniel can confirm.
- **Conflict scope.** Whether `DECISIONS.md` conflicts belong to this unit or to DOCS-API (#811).

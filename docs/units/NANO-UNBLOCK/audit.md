# NANO-UNBLOCK audit (base fbc09f28)

Goal: no PR gate goes red for a reason that is not the PR's own. Inventory of that class on every open PR from
2026-10-28 00:40Z (GX-22 #722 merged 00:43:41Z) to 02:17:30Z: 59 open PRs, 34 with gate runs in the window (46 runs,
29 red), 3 whose gate could not start. Sources: gate-status and forge-events comments, session STATUS comments, the #548
channel (about 90 REST GETs, nothing posted). No commit statuses or check runs exist on this repository. Line numbers
are fbc09f28's.

## Inventory, ranked by PRs blocked

| Rank | Item | Signature (verbatim) | Cause (file:line) | PRs blocked | Count | Decision | Cost |
|---|---|---|---|---|---|---|---|
| 1 | Base-red site test after GX-22 | `AssertionError: expected '#!env bash\n# scripts/merge-…' to contain 'local gate'` | `apps/web/src/site/domain/no-github-actions.test.ts:19-20` pins prose that GX-22 `0be5b650` removed from `scripts/merge-phase` | gates #586 #592 #596 #610 #615 #618 #620 #622 #625 #626 #632 #633 #635 #641 #643 #644 #645 #649 #659 #662 #663 #724; train batch b-4ecc9f0e5c55 #580 #605 #607 #671 #726 | 22 + 5 = 27 | fixed at the cause in #730 (site-lane, one line), gated, MERGE-READY 66aa7477 | done |
| 2 | gate-graph order race | `AssertionError: ['a', 'b', 'c', 'd', 'e'] == ['a', 'b', 'c', 'd', 'e']` | `scripts/tests/test_gate_graph.py:130-143`: a Timer releases all five jobs at once and the test asserts they finish out of declaration order; a loaded scheduler wakes them in order | #592 #622 #635 #662 | 4 | fix now at the cause (9aff4127): each job finishes after the next-declared one, order asserted exactly; 16 parallel runs green | 1 test |
| 3 | Vitest 5 s timeouts under gate load | `Error: Test timed out in N0ms.` | `scripts/lib/catalog-cli/sync.test.ts` (MEDIA_BYTE_BUDGETS), `scripts/lib/absolute-literals.test.ts` (D-063 scope), `src/identity/server/handler.test.ts`; each passes alone | #622 #626 #633 | 3 | defer (other lanes; the existing route cannot excuse a vitest stage, see "Route"); backlog | owners' tests |
| 4 | Config-store read refused by the session's own limit block | `config.StoreError: ... rate-limited; ... wait 183 s, more than github-client.max_wait_s (120 s)` (#734), `wait 976 s` (#730), `wait 502 s` (#732) | `scripts/lib/forge_rate.py:71-79` (`wait_hint` takes `x-ratelimit-reset` for a secondary limit with quota left), `:108` (a block stops reads too), `:133-135` (raise past the cap); `scripts/lib/config.py:302-320` (`_cached` drops the last good read) | gates #730 #734; sessions #731 #732 | 2 (4 sessions) | fix now at the cause: f6f78f0f (GitHub's documented wait), 3f304886 (bootstrap keys skip the store, stale-while-error) | ~70 lines + tests |
| 5 | SessionStart setup dies at its first registry read | `FAIL env: missing toolchain: python/node/pnpm/gh/gitleaks/vercel/postgres` (#733 preflight), `missing host tool: python3` (#732) | `scripts/cloud/setup.sh:27-41` `python_ok` reads `cloud.bootstrap_python_minimum` through the shared store; `:45` evals an empty answer, `:51` dies on `_ou_cloud_setup_log_path` | gates #730 #733; sessions #731 #732 | 2 (4 sessions) | fix now at the cause: bootstrap owners never read the store (3f304886); classified line (plan item 3) | in 3 and 4 |
| 6 | Cloud env unbound variable | `scripts/cloud/env.sh: line 114: _ou_cloud_postgres_host[0]: unbound variable` | `scripts/cloud/env.sh:113` and `:123` ignore `_ou_cloud_load`'s failure (`:77` checks it); the parser at `:53-60` adds a JSONDecodeError traceback | #730 #734 | 2 | fix now: one classified `FAIL env:` line (plan item 3) | ~20 lines + tests |
| 7 | Head behind its base under pinned base tooling | `bash: scripts/tests/planner-role.test.sh: No such file or directory` (#724) | the base added the test (2251c5a6); the head was 43 behind; #726 ran 2 s after the base moved | #724 #726 | 2 | not in class (the PR merges its base, merge loop rule); backlog: the gate should name it "behind base" | - |
| 8 | gate-local.test.sh stage record missing | `FileNotFoundError: [Errno N] No such file or directory: 'runner_started_at.stage.json'` | shared-tmp race suspected (TMPDIR class, GX-30); passed 86/86 elsewhere | #626 | 1 | defer; already published class env; backlog (engine-gate-run) | - |
| 9 | Pinned tooling lacks a renderer the PR adds | `eslint-config: no renderer scripts/lib/generate_eslint_config.py` | gate-pin design (GA-PG1): base tooling judges a head that adds a generate target | #662 | 1 | defer; contract class; backlog (engine-gate-pin) | design |
| 10 | Spurious "ran past stage_timeout" label | `labelled env 'past gate-gc.stage_timeout_s (600s)' although it ran 148 s` | `scripts/lib/gate-runner.sh:81-85` prints it whenever `$log.timedout` exists | #635 (no extra red) | 0 | defer; backlog (engine-gate-run) | - |
| - | Named in the brief, not seen in the window | claude-session, root-identity (sudo/uid 65534), config with no token, uid-65534 fs-encoding, script-test TMPDIR, KD-335a14a4 KD-71c8e5fe KD-27b768cb KD-a3870679 KD-41f822d3 | the four KD-* script tests pass on fbc09f28 (fixed by #716/#721); KD-41f822d3 was a load flake excused by a loaded base re-run; no in-window event carries `known_defects` (#727, #729 RETROs say none appeared) | none in the window | 0 | not in class tonight; backlog (stale KDs to close, env tests to adjudicate) | - |

Own reds, counted apart: #724 #726 #731 #732 (literal census, structure check, gate-pin, push-guard), 6 runs.

## Item 6 (cloud env), evidence (fbc09f28, worktree of the base, no token)

```
$ env -u GH_TOKEN -u GITHUB_TOKEN -u TEST_DATABASE_URL OU_CREDENTIALS=env bash -c 'set -u; source scripts/cloud/env.sh'
... config.StoreError traceback, then a json.decoder.JSONDecodeError traceback from the parsing helper ...
scripts/cloud/env.sh: line 114: _ou_cloud_postgres_host[0]: unbound variable
```

## Item 4 (config-store limit), evidence and cause

- Coordinator repro, confirmed on fbc09f28 without a token: `config.py get cloud.setup_lock_path` raises
  `config.StoreError: config: the change store cannot be read (missing GH_TOKEN); ...`; `OU_CONFIG_STORE=file` answers.
- This session, 02:07Z: `curl -sI https://api.github.com/rate_limit` with no header of ours answers
  `X-Ratelimit-Limit: 15000`, `X-Ratelimit-Remaining: 14172`, `X-Ratelimit-Resource: core`: the egress proxy injects an
  installation credential (anonymous is 60/h). `GH_TOKEN` present (value not printed), `OU_CREDENTIALS=network`;
  `github_api._request` (`github_api.py:90-94`) sends a present token as Bearer. The failing sessions were therefore not
  anonymous and their primary bucket was not empty: the refusal was a secondary limit, turned into a long block by us.
- #730's own record: the same head passed `gate-dev --pr 730` at 02:04Z once the window passed (MERGEABLE, 5m39s,
  14 writes, 33 reads; gate.passed e271f8dae23b at 02:09:30Z); #734 re-ran green at 02:05Z. The defect is the hard fail
  on a transient window plus the unchecked env.sh load, not a permanently broken environment.
- 4a, the long wait: `wait_hint` returned `x-ratelimit-reset - now` whenever the header was present. GitHub sends that
  header (the PRIMARY hourly reset) on every answer; its documented rule for a secondary limit is Retry-After when
  present, the reset only when `x-ratelimit-remaining` is 0, otherwise at least one minute (docs.github.com, REST
  "Rate limits", "Exceeding the rate limit"). So a secondary refusal with quota left blocked the whole session, reads
  included, until the next hourly reset (976 s, 183 s, 502 s fit those distances), above `max_wait_s` (120 s), and
  `acquire` raised at once. Base fbc09f28 fails the new test: `978.0 != 62.0`.
- 4b, no stale fallback: `config._cached` served a read only while fresh (`config.store_cache_ttl_s`, 60 s).
- 4c, bootstrap keys read the shared store: `cloud.*` and `toolchain.*` configure the machine; the store holds no
  override of either owner (read 02:20Z: `coordinator.max_sessions`, `train.enabled` only). Measured 02:44Z with the
  forge count file (`github-client.count_file_env`), cold cache: ONE `config.py get cloud.setup_lock_path` costs 18
  GitHub requests on fbc09f28 (a paginated read of the change log) and 0 on this head; the fixed `setup.sh` ran in
  3.7 s and `env.sh` sourced cleanly with 0 requests, through the real store path (no `OU_CONFIG_STORE=file`). Every
  session start paid those reads on the base, which is how a burst of sessions reaches GitHub's secondary limit.
- 4d, the CLI printed a traceback: `config.py:680-687` caught `ConfigError` only.
- Unchanged and correct: `gate-local:253` exports `OU_CONFIG_STORE=file` for the run, `gate-hooks/pin.sh:13` for the pin,
  `train_trigger.py:41` strips it on purpose. The reads that broke ran before gate-local.

## Route for what is deferred (the existing mechanism, verified)

- The only verdict-changing route is KD1's base re-run (`docs/operations/known-defects.md`; `defect_detect.py:72-127`):
  tier 1 (`gate-dev`) only, `script tests` stage only (`config/registry/defects.json:10-23`, `defects.stages`). A
  failing script test that fails on the base with the same normalized signature is a known defect: the stage passes,
  the report keeps it visible (`stages.json`, the verdict's `known_defects`, `defect.detected` on #548, the status
  comment's "known base defect" column). Records under `docs/process/defects/` (`scripts/defects record`) track and
  route only; they excuse nothing.
- The env class (D-027, `gate_classify.py:45-50`) is a label: an env-class stage still fails the gate; the train halts
  instead of ejecting a culprit (`train.py:215-227`). A code marker in the same log wins.
- Premise of the brief that broke: "route it through the known-defect/env classification so it stops turning innocent
  PRs red". That holds only for a script test the base re-run reproduces. A load flake passes the re-run, and vitest
  stages are outside `defects.stages`, so rows 3, 8 and the GX-ENV tests cannot be excused by the existing route
  without changing the route (a gate change for the perfection pass) or loosening something (forbidden). They stay
  visible in the report exactly as today and are listed in `backlog.md` with owner lanes.
- What the env route can still do correctly and cheaply: label a GitHub rate-limit line env (it is never the PR's code;
  today `gh: exit 429 (rate-limited)` in a stage log is classed code). Done in plan item 5.

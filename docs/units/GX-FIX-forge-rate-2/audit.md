# GX-FIX-forge-rate-2 — audit

Unit: GX-FIX-forge-rate-2 (owner engine-events, approval A Torre 20:05 BRT 27/10, Decision D-070).
Base: mod/roadmap-integration at e7d8bfdb (merge of #718). All file:line references below are to e7d8bfdb.

## 1. Root cause of the 39 post-#718 per-test comments

### Evidence (read-only GETs, 2026-10-27 23:0xZ)

- `GET /issues/548/comments?since=22:29Z` returned 73 comments. Each is one envelope (`engine.step.measured`, producer
  `gate_test_cache`, correlation `gate-script-tests`): 39 on `8cf5c40c`, 26 on `59224def`, 4 on `4ee8d17a`
  (#718's own pre-merge head), 3 on `457aabda`.
- On 8cf5c40c the first envelope is `occurred_at 22:40:08.693Z`, posted `22:40:17Z`
  (`gate:script-test:scripts/tests/battery.test.sh`). The second is `occurred_at 22:40:17.587Z`, posted `22:40:25Z`
  (`claude-session.test.sh`). The last is `occurred_at 22:45:29.606Z`, posted `22:45:38Z` (`gate-status.test.sh`).
  The steps come in alphabetical order (the order of `timed`), each built right after the previous POST ended. That is
  the pre-#718 loop at `gate_test_cache.py` (5930e814^):
  `for script, ms, ok in timed: port.emit(...)`. Each emit reads the #548 window (1 issue GET + up to 20 page GETs,
  `forge_github.py:103-120`) and then POSTs one comment (`forge_github.py:89-93`). The loop stopped after 39 of ~80
  tests: the next POST was refused (secondary limit), and `record_durations` swallows every exception
  (`gate_test_cache.py:116-117`).
- The #718 code cannot produce this. `record_durations` (`gate_test_cache.py:107-117`) builds all envelopes in one
  list comprehension, so they all carry the same instant, and publishes them in one `port.publish`.
  `adapter_from_config` (`forge_events.py:188-196`) routes `engine.step.measured` (`forge-events.file_kinds`,
  `config/registry/forge-events.json:85-98`) to the FileAdapter. Both e7d8bfdb and 8cf5c40c carry that code:
  `git merge-base --is-ancestor e7d8bfdb 8cf5c40c` holds, and `git show 8cf5c40c:scripts/lib/gate_test_cache.py`
  shows the batched version. Conclusion: a gate run on head 8cf5c40c executed PRE-#718 tooling (a base before
  e7d8bfdb) as its pinned tool root.

### Mechanism (H1, proven): the pin trusts GitHub's `base.sha`, which lags the base tip

- `gate_pin.pr_identity` (`gate_pin.py:90-102`) takes the pinned base from `baseRefOid`. `github_api.py:212-213` maps
  that to the REST pull's `base.sha`. `resolve` (`gate_pin.py:125-129`) pins the tooling to that sha.
- `base.sha` of a pull is not the tip of its base branch. GitHub stores the base commit as of the PR's last
  synchronization and recomputes it asynchronously after a push. Live GETs at 23:1xZ, with base tip `e7d8bfdb`:
  `#714 base.sha=ebab9368`, `#705 base.sha=ebab9368`, `#718 base.sha=fc08c162`. Two of the open PRs are still pinned to
  an older base.
- Timeline of #716: GX-29 merged e7d8bfdb into its branch at ~22:35Z and pushed 8cf5c40c. The per-test emissions started
  at 22:40:08Z, from a run started before the "running now" comment (22:40:54Z). While GitHub had not yet recomputed
  #716's base, `pr_identity` returned head `8cf5c40c` with the previous base (`fc08c162`, pre-#718). The pinned tool
  worktree `<slot_dir>/gate-pin/<clone>/fc08c162` therefore ran the old `gate_test_cache.py`, with `--source 8cf5c40c`
  (gate-local:347). `#716 base.sha` reads `e7d8bfdb` today, after GitHub caught up. The `gate: pinned to` line of
  that run is requested from GX-29 (one comment on #716) to close this last link.
- The same class exists on the pin's `--sha` path. `batch_base` (`gate_pin.py:116-122`) fetches with `check=False`
  and silently falls back to the local, possibly stale, `origin/mod/roadmap-integration` ref.
- Second door of the same class: the advisory `--report-only` run of the head's own tooling (`gate_pin.head_tooling`
  `:252-262`). Its `gate_test_cache main` (`:257-259`) always calls `measure=True`. A head that has not merged #718 runs
  the old per-test loop, whatever the pin does.

### Hypotheses not retained as the cause of these 39

- H2 (a test reached the real forge): GX-29 is repairing the hermetic network denial (`hermetic.py`). The 429 errors in
  `credentials.test.sh` / `github-cli.test.sh` on that run are explained by the identity being blocked at that time:
  the old loop had exhausted the secondary limit for `the-owner`, and a test that reaches the API, hermetic or not, gets
  429. No test emits `engine.step.measured` with producer `gate_test_cache` (`rg record_durations` finds only
  `gate_test_cache.py` and the two unit tests, which use fakes). Left with GX-29 (it owns `hermetic.py`).
- H3 (config override of `forge-events.file_kinds`): the gate exports `OU_CONFIG_STORE=file` (`gate-local:253`,
  `pin.sh:13`). A store override does not make the per-test serial `occurred_at` pattern: new code builds all envelopes
  at once. Not the cause.

## 2. Every GitHub call of a cold pinned `scripts/gate-dev --pr N` run (e7d8bfdb tooling), before

C = comments on the channel, P = forge-events.github_page_size (100), M = forge-events.github_max_pages (20),
F = gate.status_find_pages (5), S = stage boundary events that pass the 15 s throttle.

| # | Call site | Kind | Per run (before) | Must it touch GitHub during the run? |
|---|---|---|---|---|
| 1 | `gate_pin.pr_identity` `gate_pin.py:90-102` → `github_api.pr_view` | GET pull | 1 | Yes (head identity), but its base must be the fetched tip of the base REF, never `base.sha` |
| 2 | `gate_status.begin` `:255-269` → `upsert_comment` `forge_github.py:227-251` | GET issue + ≤F GET pages + 1 POST/PATCH | ≤ 1+F reads, 1 write | Yes: the panel contract (begin) |
| 3 | `gate_status.set_status pending` `:204-218` | POST status | 1 write | Yes (commit status contract, GX-17) |
| 4 | `gate_status.stage_event` `:271-283` (gate-runner.sh:9-12) | PATCH (comment id kept) | ≤ S writes, best effort (`max_wait_s 0`) | Yes, throttled per the panel contract; never per test |
| 5 | `gate_test_cache.measured_durations` `:98-104` → `RoutingAdapter.read` `forge_events.py:170` → `forge_github._comments` `:93-101` | GET pages of #548 | ⌈C₅₄₈/P⌉ ≤ M (≈17 today) reads | **No**: the kind lives in the local file log |
| 6 | `gate_test_cache.record_durations` `:107-117` → `ForgeEvents.publish` `:257-268` → `RoutingAdapter.recent` → `_window_comments` | GET issue + ≤M GET pages | ≈18 reads, 0 writes (routed to file) | **No**: the dedupe window of a file-routed kind is the file |
| 6' | same on pre-#718 tooling (the incident) | per test: window read + POST | ~80 × (≈18 reads + 1 write) | **No** |
| 7 | `gate_report.emit_evidence` `:137-150` → publish on the PR channel | GET issue + ≤M pages + 1 POST | ≤ 1+M reads, 1 write | Yes: once at the end (the verdict) |
| 8 | `gate_report.ready_hook` `:154-174` (pass + valid body) | reads of the PR channel + body + 1 POST | ≤ 2+M reads, ≤ 1 write | Yes: once at the end |
| 9 | `gate_status.final` `:286-299` | PATCH + POST status | 2 writes | Yes (panel and status contract) |
| 10 | advisory `--report-only` head run (`gate_pin.py` step 4) | items 5-6 again, plus one advisory comment | ≈35 reads, 1 write | Only the advisory comment |
| 11 | config store (`config.store`, `config.py:250-262`) | none: the gate exports `OU_CONFIG_STORE=file` (`gate-local:253`, `pin.sh:13`) | 0 | No (already local) |
| 12 | `gh` CLI subprocesses | none: `github_cli.py` is REST through `github_api.run_http`; `rg 'gh (api\|pr\|issue)'` over gate-local, scripts/lib/*.sh and gate-hooks finds none | 0 | — |

Total before (e7d8bfdb tooling, cold): about 1 + (1+F) + 17 + 18 + (1+M) + (2+M) + 35 ≈ 120 reads. Writes: 1 + 1 + S +
1 + 1 + 2 + 1 = 7 + S. On pre-#718 tooling (the incident), add ~80 writes and ~1 400 reads in the script-tests stage.

### Rate-limit handling (item 3 of the brief)

- Every Python call goes through `github_api._request` (`github_api.py:78-133`). A limit refusal records a block
  (`forge_rate.Limiter.refused`, Retry-After / x-ratelimit-reset, floor `secondary_wait_min_s`, jitter), and the call
  waits it out. Reads wait on a recorded block too (`acquire` checks `blocked_until` for any method).
- Gap: exactly one wait per call (`waited` flag, `github_api.py:113-118`). A second refusal raises at once. The bound
  must be a registry key (`github-client.limit_retries`), and the cap error must be classified.
- Gap: the limiter applies only to the production origin or when the state env is set (`_limiter :59-64`). Tests cover
  it through `write_state_env`, and production calls are always covered.

## 3. After (this unit): see plan.md and the PR body for the measured counts.

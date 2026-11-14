# GX-FIX-forge-rate — audit

Base `mod/roadmap-integration` at `ebab9368`. Decision D-070. Owner units/engine-events (the limiter itself sits in
units/engine-github next to its only caller, see plan.md). Reads only; no probe writes against the real forge.

## 0. Incident (27/10 ~18:16 BRT)
GitHub's secondary content-creation limit (~80/min, ~500/h per identity) refuses every comment and PR creation for
`the-owner`, the identity every engine cloud session writes as. This session's own `POST /pulls` at 21:34:30 UTC got
`403 "You have exceeded a secondary rate limit and have been temporarily blocked from content creation."`
(request id C0E4:62EAE:26E5F18:8017F66:6AE118E4). ~496 comments in the hour before, ~83 % `engine.step.measured` on #548.

## 1. The single choke point
Every engine GitHub REST call ends in `github_api._request` (`scripts/lib/github_api.py:55` on the base). Above it:
`github_api.rest()` (:99, used only by `forge_github.py`) and `github_api.run_http()` (:262, gh-shaped argv; wrapped
by `github_cli.run_gh` :26 and `delivery.run` :35). No engine code under `scripts/lib` or `scripts/*` uses `requests`,
`curl`, the real `gh` binary or `urlopen` against GitHub (the only other `urlopen` writes go to Neon, `neon_pr.py:120,154`).
`git push` (not REST) has one caller: `push_guard.py:98` (one commit per push; its heartbeat goes to the file adapter).

## 2. Every engine GitHub write (base ebab9368)

| # | file:line | verb + path | reached from | writes today |
|---|---|---|---|---|
| 1 | forge_github.py:76 `append` | POST issues/{n}/comments | every `ForgeEvents.publish`/`emit` | one per emit (see §3), one per 65k chunk for a publish |
| 2 | forge_github.py:199 `open_change` | POST pulls | replay_branch.py:131 | 0–1 per replay |
| 3 | forge_github.py:203 `close_change` | PATCH pulls/{n} | replay_branch.py:134 | 0–1 per replay |
| 4 | forge_github.py:207 `comment` | POST issues/{n}/comments | replay_branch.py:133 | 0–1 per replay |
| 5 | forge_github.py:224 `upsert_comment` edit | PATCH issues/comments/{id} | gate_status `push()` ← begin (forced), stage_event (every 15 s, `gate.status_min_interval_s`), final (forced) | ~2 + min(2×stages, wall/15 s) per PR gate run |
| 6 | forge_github.py:228 `upsert_comment` create | POST issues/{n}/comments | same; and gate_pin.py:317 advisory | 1 per (sha, mode); **also 1 whenever the PATCH fails** (`except Exception: pass` then POST) |
| 7 | forge_github.py:237 `set_status` | POST statuses/{sha} | gate_status begin/final | 2 per PR gate run |
| 8–12 | forge_github.py:258,261,283,290,302 lock | POST git/trees, git/commits, git/refs; PATCH/DELETE git/refs | engine_role run/renew/judge | 3 per judged run (GX-FIX-train-lock owns these; proxy refuses git-data writes) |
| 13 | forge_github.py:147 → github_api.py:292 | PUT pulls/{n}/merge | train.py:295 | 1 per PR per green batch |
| 14–15 | github_api.py:292,299 | PUT merge, DELETE head ref | merge-phase:179 | 1–2 per ship (frozen) |
| 16 | github_api.py:302 | PATCH pulls/{n} (pr close) | no caller | 0 |
| 17 | github_api.py:257 `_api` | PATCH git/refs/heads/preview | merge-phase:34 | 1 per ship (frozen) |
| 18 | github_api.py:277 `pr comment` | POST issues/{n}/comments | ship_tail.note :81 | 5–10+ per ship (frozen) |
| 19 | github_api.py:277 | POST issues/{n}/comments | preview-deploy:182 | 1 per deploy (frozen) |

## 3. Per-item emit loops (each emit = 1 window read of up to 21 GETs + 1 POST with the github adapter)

| file:line | kind | count per run |
|---|---|---|
| gate_test_cache.py:113→114 `record_durations` | engine.step.measured (repo channel #548) | **one per uncached script test, ~80 per gated commit** — the incident |
| quarantine.py:113→116,119 `report` | test.flaked, test.quarantined | 1–2 per flake + 1 measured |
| quarantine.py:136→139 `release` | test.unquarantined | 1 per stabilised test + 1 measured |
| slo.py:167→169 | slo.breached | 1 per breached SLO + 1 measured |
| stall_report.py:68→72 | engine.session.stalled (PR channel) | 1 per stalled PR |
| defect_router.py:93→98,105 | work.assigned, defect.routed | 2 per routed defect |
| defects.py:278→281 `sync` | defect.reopened / defect.registered | 1 per new detection |
| coordinator.py:158→169 | work.assigned | 1 per launch action |
| train.py:182-185, 293-309, drain loop | pr.refused, pr.conflicted, pr.merged, queue events | 1 per PR per batch — **follow-up for GX-30 (train.py not touched here)** |
| battery.py:124 drain, engine_role.judge :116 | battery.*, engine.step.measured | 2–3 per tip, 1 per judged run |
| forge_events.py:226→229 `evaluate_branch_age` | branch.stale | ≤1 per PR-channel trigger |

Already one publish per run: gate_report.py:150 (stage step events + verdict, one PR-channel comment), unit_battery.py:205,
unit_map.py:380, unit_addresses.py:239, plan_triage.py:406.

**Writes per PR gate run, before:** ~80 (record_durations) + 1 verdict append + 1 status comment create + ~10 status
edits + 2 statuses ≈ **94 writes**, of which ~82 POST comments.

## 4. gate-status: reposts or one per new (sha, mode)? (read-only GETs, 21:40 UTC)
`gate-status v1` comments per PR, grouped by the marker's (sha, mode):

| PR | comments | distinct (sha, mode) |
|---|---|---|
| 671 | 15 | 15 |
| 698 | 12 | 12 |
| 706 | 14 | 14 |
| 705 | 11 | 11 |
| 714 | 6 | 6 |
| 712, 713 | 4, 4 | 4, 4 |
| 717 | 1 | 1 |
| 695 | 8 | **7** |

Finding: almost every comment is **one per new (sha, mode)**, the contract (a commit per push, each gated). The one
repost: #695 `sha=a94be3e0… mode=dev` has two comments both created `2026-10-27T18:46:38Z` (updated 18:48:30 and 18:48:44):
two processes (the pinned run and the head's report-only run, GX-05) did find-or-create at the same second, both found
nothing and both POSTed. Second repost class, from the code: `upsert_comment` POSTs a new comment whenever the PATCH
raises (`forge_github.py:224-228`), so a PATCH refused by a rate limit becomes a new comment. 143 gate-status comments in
the incident hour are therefore ~1 per gated head plus these; the edits (PATCH every 15 s) are the larger write volume.

## 5. MERGE-READY readers
No reader in `scripts/` keys on the literal `MERGE-READY` (`rg -n "MERGE-READY" scripts` finds nothing); `pr_ready.py`
emits `pr.ready` through the port and the train reads events, not that text. The merge routine is the coordinator
session (outside `scripts/`), which reads the PR's comments. This unit keeps one new "MERGE-READY <full sha>" comment
per new gated sha (never one per run), changes nothing in how it is posted, and does not touch train.py.

## 6. Engine-side STATUS posting
None in scripts/lib: STATUS comments are posted by sessions by hand. Documented in docs/operations (edit the newest
STATUS in place).

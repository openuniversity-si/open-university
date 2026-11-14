# TR2 audit (base efc7f3b4, mod/roadmap-integration)

Read-only audit of the train path after TR1 (#550). Evidence from the base and the coordinator's notes of 2026-10-27.

## Findings

| # | Finding | Evidence |
|---|---|---|
| F1 | Nobody emits `pr.ready` automatically. `gate_report.emit_evidence` publishes `gate.passed`/`gate.failed` only. | `scripts/lib/gate_report.py` `emit_evidence`; EVENTS.md row `gate.passed` says "A pass with a valid body emits `pr.ready`". 0 `pr.ready` over 30 open PRs. |
| F2 | `pr_ready.emit_ready` hardcodes `lane_id=None`. | `scripts/lib/pr_ready.py:32`. |
| F3 | Manifests have no `lane` field; the lane is `owner` (`engine-lane`, `admin-lane`, ...). 105 manifests under `units/*/unit.json`. `refusals()` compares `manifest.get('lane', owner)` with `lane_id`, so `None` makes every touched unit foreign. | `units/engine-config/unit.json`; `scripts/lib/train_ownership.py:40`. Batch b-ae8150ea8056: #580, #586 `pr.refused` (ownership). |
| F4 | Approvals can never match: `ForgeEvents.approvals` returns GitHub reviewer logins, the check compares them with lane ids. No recorded approval fact exists. | `scripts/lib/forge_github.py` `approvals`; `train_ownership.refusals` last line. |
| F5 | A refused head never re-enters: `pr.ready` natural key is repo/pr/sha and `queue_entry` drops any head with a `pr.refused`. | `contracts/events/pr.ready.v1.json`; `train.OUT_OF_QUEUE`. |
| F6 | Nobody runs the train: `pr_ready.main` only appends the event; Transport v0 says the producer tries the lock and runs the role. | EVENTS.md "Transport v0"; `pr_ready.py` `main`. |
| F7 | `config.get` re-reads and json-parses every `config/registry/*.json` per call; `config.overrides` replays the store per call (called per event through `event_contracts.validate`). `drain()` computes `queue()` after `pending()` already did. 8m12s for the queue over 24 PRs (py-spy ~90% in config). | `scripts/lib/config.py` `_load`, `overrides`; `train.py` `pending`/`drain`. |
| F8 | Tier 2 is `scripts/gate-dev --sha <combined>`; the combined head is a local ref kept per batch (`train.combined_ref_prefix`); refs and the gate's worktree/cache are never cleaned per batch. Box at 94% inodes. | `train.json` `train.tier2_command`, `train.combined_ref_prefix`; `train_git.py`. |

Program PRs legitimately cross lanes (#605 playback-lane only, #607 admin-lane only, #615 kernel-lane only per the coordinator's check; U3b/B1 cross several), so the lane must be derived and cross-lane approval must be a recordable fact.

## Fences

- BD1 (gate lane): `scripts/lib/defect_detect.py`, defects registry, max-behind-base check in `gate_status`. Not touched.
- MQ1: merge-on-pass/priority around `train.py`. TR2 keeps `train.py` edits to queue entry, ownership call and one queue per drain iteration.
- Branch: the session is bound to `claude/merge-train-pr-ready-f7mxzt` (harness rule: never push elsewhere), not `mod/tr2`.

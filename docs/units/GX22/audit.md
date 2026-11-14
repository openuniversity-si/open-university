# GX-22 audit (read-only)

Base `d101b73c` (mod/roadmap-integration, GX-37 #706 merged). Sources: plan-v2 §3.3/§4/§5.2 (origin/mod/ga4 bce2cd94), plan.md (GA3).

## Findings
- `scripts/lib/commit_check.py:95-107` `rebase_errors(base, commits, branch)`: refuses any head behind its base that has no
  PR commit merging the merge base (today's rule, FP1 wording). No registry read, no "limit" in the message.
- `scripts/merge-phase` (184 lines): exact-head proof is a local file (`$GATE_RECORD_DIR/<sha>.{pass,dev.pass,db.pass,noite.pass}`,
  `:95-121`), never the event log; mergeable `:93` and `--match-head-commit` `:173` are hard-coded; no behind-base check at all.
- GX-37 (#706, on base): `forge_events.gate_evidence(replay(port.read(repo, pr)), pr, sha, plan)` (`forge_events.py:509`) is
  "what replaces `.dev.pass` as evidence"; verdicts are per PR channel and per plan (gate-local modes `pr|nightly|dev|noite|db|tier3`,
  `gate-local:92-97`). pr_ready.py already reads it this way.
- `config/registry/merge.json` does not exist on base. BD1 #667 has `merge.max_behind_base` (20), `merge.regate_on_overlap`,
  `merge.compare_page_size`, `merge.compare_max_pages`, `merge.paths_shown` and `scripts/lib/merge_behind.py` (decide/measure over
  the REST compare via `github_cli.py api`); reviewed: sound, read-only, raises when a compare is too long (no silent pass).
  MQ1 #680's merge.json is a different domain (merge-on-pass claims, freeze window): idea only (one owner `merge`, one file).
- `scripts/tests/rest_fake.py` has no `/compare/` route; it stores issue comments, so the forge_events GitHub adapter
  round-trips through it (the event log of a merge-phase fixture).
- `scripts/lib/train.py` reads no merge.* key; GX-30 (#717) codes against the four key names. Not edited here.
- Script tests: `commit-check` (test_commit_check.py), `merge-phase.test.sh`; new `merge-behind` registers a covers sidecar.

## Premises
- P-47 (GA-PG3) CRITICAL, decided: switch `merge.tier1_requires_base_merge`, default true = today's rule.
- P-18 train sole merger (medium): merge-phase stays the current-rule merger; this PR does not merge.
- P-46 (GA-PG1) medium: verdict of record is the pinned gate.

## Known defects (not mine)
KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3; env tests claude-session, root-identity, config (GX-ENV).

# LR1 audit: where the lessons system hooks in

Read-only findings with evidence (D-069 items 4, 9). Base `79045314` (#574 merged).

## What exists and must be reused
- **Registry pattern (KD1)**: `scripts/lib/defects.py` keeps one strict-YAML record per defect plus an append-only,
  hash-chained `<slug>.audit.jsonl` (`append_entry`, `chain_errors`, `entry_digest`; settings under `defects.*`). Shapes are
  `contracts/defects/{defect,audit}.v1.json`. One file per record, no common file (D-064 a). LR1 follows it.
  The chain helpers read `defects.*` settings, so LR1 gets its own parametrized helper rather than editing KD1's module.
- **Events**: new type = `contracts/events/<type>.v1.json` (`x-natural-key`, subject fields `repo, pr, sha, unit, premises`
  via `defs.v1.json`), `event_contracts.py lock`, a row in `docs/process/EVENTS.md` (test_event_contracts compares names),
  `scripts/generate python-types`. `forge_events.ForgeEvents.emit` validates against the newest version; `port.read(repo)`
  returns the deduplicated log with `occurred_at`, enough for before/after counts (`read_window` is not).
- **Gate failure data**: `gate.failed` v3 carries per-stage `class` (D-027: code|env|contract), `duration_ms`,
  `failing_tests[{id,stage,signature}]`, `known_defects`. There is no finer root-cause class: lessons carry their own class
  vocabulary (registry-defined), mapped onto D-027 only as a coarse parent.
- **Commit check**: `scripts/lib/commit_check.py` is PR-side (REST): `plan_errors`, `fixup_errors`, `push_errors`,
  `gate_errors`, `decision_wait.errors`; `--pr` or `--fixture`. Tests: `test_commit_check.py` (fixture driven).
  No pre-push hook exists; `.githooks/` has post-commit and post-merge (push guard X1 pushes each commit alone, but a manual
  or API push can still batch, which is what GV1 hit). `core.hooksPath` is already set by `scripts/cloud/env.sh`.
- **Structure check**: `structure.py main` is monolithic (20-34 s whole); a fast subset must call the cheap sub-checks
  directly (`check_decisions`, `postmortem_check.check`, `plan_errors`, ...). Secret scan: `gitleaks dir` on a copied file set
  (`gate-runner.sh secret_tree`). Literal check: `config_check.python_findings/text_findings` work per file; the file set is
  chosen in `engine_files`.
- **Cost measurement**: `forge_events.measured` / `step_payload` emit `engine.step.measured`; a local file adapter exists
  (`push_guard.heartbeat`). Reuse for per-check cost.
- **Retros to ingest**: `docs/units/KD1/retro.md` (tables with F1..F11 and numbered lessons) and `docs/units/GV1/retro.md`
  (bullets, table, numbered lessons). Section 5 "Lessons" in both is a numbered list ending with `Owner: ...`.

## What does not exist (no duplication)
No lessons registry, ingestion, aggregator, effect measurement, brief query, or registry-driven local check. `docs/process/
postmortems` is per incident and hand-written; lessons link to it, they do not replace it.

## Constraints found
- Config: each `config/registry/<owner>.json` key needs `x-readers` files that exist; literals for registered names are
  refused by `config_check` (use `config.get`, no fallbacks). Generated python `config_registry_lessons.py` via
  `scripts/generate python-types`.
- Committed generated docs: a target owns its whole output folder (`generate.write` deletes strays), so
  `docs/process/lessons.md` is a dedicated committed target with its own output path rule, not a folder target.
  Check `generate.py` for single-file outputs before choosing; fallback: the aggregator writes the file and a test pins it.
- Wiring per new script: `gate-script-tests.json` entry, `docs/structure/assets.json` `script` entry, unit manifest
  (`units/engine-lessons/unit.json`, CODEOWNERS regenerated), shellcheck list in `gate-local`.
- Gate file rule (D-025): `commit_check.py` and `scripts/commit-check` are gate files; the PR body cites D-069.
- Ownership: GS1/KD1/GV1 code is only called through ports (`forge_events`, `defects.load`), never edited.

## Evidence of the class to catch
GV1 retro lessons 1-2: audit+plan pushed together (D-022) and no D-NNN in the body (D-025). Both are detectable at commit time
from local git state and the PR body.

# TH1 retro: thresholds only tighten; hermetic carve-outs listed

PR #598, branch `claude/th1-thresholds-tighten-litkfp`, base `mod/roadmap-integration` (a2c09043 at launch).

## 1. Brief quality

- **Contradiction:** "every `without_harness` call site must be listed in `tests.unhermetic_sites`", but that list only
  shrinks against the base, so listing the two existing sites was refused by the very check being extended. The
  brief did not say how to reconcile them. Resolved by admitting a gained site only when the base file already
  offended that rule (disclosed debt), which keeps the shrink rule for new carve-outs.
- **Ambiguous:** "unless the PR body and the commit cite a D-NNN that authorizes it". Every gate-file PR already cites
  D-025/D-069, so a bare citation would authorize every loosening by accident. Made explicit: `Loosens: <name> D-NNN`.
- **Missing:** "with a reason" for each listed site had no place in the format (path:RULE strings, meta-schema
  `additionalProperties: false`); the reason went into the entry's description.
- **Branch name:** the brief names `mod/motor-th1-thresholds-tighten`; the session harness pins
  `claude/th1-thresholds-tighten-litkfp`. Used the harness branch (PR comment).

## 2. Audit and plan

- Premises held: P-41 (all tunables in the registry); `config.diff_ref` and the forge_events port were reusable as is.
- The plan placed `threshold_check.py` in unit `engine-config` (next to config_check). That broke: the module imports
  commit_check, units and forge_events, which engine-config does not declare (U2 import check), and engine-config went
  above its 1500-line ceiling. Moved to `engine-structure` (with structure.py and visual_guard.py) in an extra commit
  under plan item 4; the test moved to the structure-check battery with it.

## 3. Execution (timeline, UTC)

| Time | Commit | Note |
|---|---|---|
| 06:46 | 98dbaf9b audit | |
| 06:49 | 9bd8d88a plan | draft PR #598 opened |
| 06:53 | cdc71f10 threshold check | written in parallel with the hermetic sub-agent (disjoint files) |
| 06:57 | da2546ad config.changed report | pushed before test_structure finished: its self-check was red |
| 07:03 | 65c2df92 unit move | fixes the undeclared imports; clears the oversize warning |
| 07:06 | 1ff429dd hermetic carve-outs | sub-agent's change, reviewed; stale `:random` site removed |
| 07:10 | 9b49cc66 merge of the base | conflict in tests.json: both sides removed the stale site |

Failure classes:
- **Undeclared unit import (class: placement of a new module).** Root cause: the per-commit targeted tests ran the new
  module's own tests and structure-check, but not `test_structure.py`'s repository self-check, which runs the U2
  architecture rules; the push guard's `structure_fast` does not include them either. It was pushed (cdc71f10,
  da2546ad) red for that one test and fixed in the next commit. Searched for the same pattern: no other new module in
  this PR.
- No dead ends; one wait (the gate, about 10 min).

## 4. Gate

- Run 1 on 9b49cc66: **PASSED**, 575 s wall on 4 vCPU (script tests 455 s, structure check 44 s, secret scan history
  6 s, schema compat 2 s, tree scan 2 s, generated drift 1 s). The only failure, `scripts/tests/generate.test.sh`
  (`intents-doc.ts` ERR_MODULE_NOT_FOUND on `@ou/kernel-tables`), is the open known base defect KD-024bbecb (owner
  engine-lane, unit engine-generate): the U3b address rewrite of `apps/web/src/release/domain/intents.ts` made it
  unresolvable to plain `node`. No PR fixes it yet. This PR selected it because it touches `config/registry/**` and
  `contracts/**`.
- The ceiling warning (575 s > 180 s, D-064 f) is report-only.

## 5. Lessons

| Problem | Change that prevents it | Owner |
|---|---|---|
| New module placed in a unit whose `requires` lack its imports | add the U2 architecture-rule check (unit imports) to the `structure_fast` local check, or to `local-checks.json`, so the push guard refuses it in seconds | engine-lane (LR1 local checks) |
| Brief asked to list sites in a shrink-only list | brief template: when extending a shrink-only allowlist with a new rule, say whether pre-existing sites are admitted (now: they are, by base judgement) | A Torre (brief template) |
| "cite a D-NNN" is not a parameter-specific authorization | keep the `Loosens: <name> D-NNN` line as the one form; reference it from D-069 item 14 | A Torre (DECISIONS.md) |
| The gate printed `class: code — fix this PR's change` for a failure that is a known base defect, before `GATE: PASSED` | `gate_classify` should print `class: known defect KD-…` when defect_detect matches | engine-lane (gate classify) |
| KD-024bbecb stays red on the base and is only seen by PRs whose diff selects generate.test.sh | a resolver for `@ou/*` in plain-node renderers (tsconfig paths hook) or run the renderer through the web toolchain | engine-lane / U3b owners |

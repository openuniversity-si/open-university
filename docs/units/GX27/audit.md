# GX-27 audit (base eaeeb29d)

## Readers of `merge.tier1_requires_base_merge`
- `scripts/lib/commit_check.py:110` — `limit = 0 if config.get('merge.tier1_requires_base_merge') else config.get('merge.max_behind_base')` (the only runtime reader; `rebase_errors`). Docstrings at `:12`, `:101` describe "on (default)".
- `scripts/lib/train.py:63` — comment only (the train re-proves the batch on the tip).
- `scripts/lib/generated/config_registry_merge.py:8,19` — generated name list and type.
- `config/registry/merge.json:44-55` — declaration (default true, `x-readers` commit_check).
- Tests: `scripts/tests/test_commit_check.py:100-116` (`self.refused(within, 'rebase')` at line 105 pins the OLD default, so it must change to set the switch ON explicitly); `scripts/tests/test_train.py:718` only checks the key equals the shared registry value (default-agnostic).
- Docs: GX22 plan/retro/audit, GX30 plan, program plan (history, not edited).

## "0 behind" wording in `docs/padrao/v1/*`
`rg -i "behind|0 behind|merge loop|MERGE-READY|rebase|catch" docs/padrao` finds nothing relevant: none of the ten padrão v1 files (agent-tree, audit-and-plan, decide-then-report, fix-the-class, no-probe-prs, padrao.json, parallelize, retro-before-merge, save-often, think-before-acting) states the requirement. The "MERGE LOOP / 0 behind" text lives in the launch brief template outside `docs/padrao/v1`, not in this repo. So there is no padrão line to remove; the brief says "that line only" and no line exists, so no padrão file is edited (editing others would exceed scope). Flagged for the brief owner.
The repo-level statement is AGENTS.md (FP1 "a head behind its base with no merge commit") enforced by commit_check; it follows the switch and needs no text change.

## Plan implication
Flip default to false; update the description in merge.json (it says "On (default)"); regenerate; fix the one test pinning the old default.

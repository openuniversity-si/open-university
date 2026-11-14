# RETRO-API retro

Unit: RETRO-API, PR #798, branch `mod/retro-api`, base `mod/roadmap-integration` at `069145b9` (0 behind at the gate).
Times are UTC (BRT = UTC-3). All facts come from the commits, the PR comments and the audit.

## 1. Brief quality

- **Missing: where the logs are.** The brief asked to ingest "the Claude session transcript under ~/.claude/projects/**"
  and "the unit's motor records" for three units, two of them running tonight. A cloud session is one container, so it
  holds only its own transcript, and the motor (`/workspace/torre/motor`) is on A Torre's box. The brief could not be
  met as written from a cloud session. It said what to do when a transcript is unreachable ("say so plainly"), which
  was enough to proceed. Cost: none in rework, but the acceptance shows one stored unit, not three.
- **Ambiguous: "a central store".** A directory in an ephemeral container is not central. The brief named the path
  `retro/logs/...` but not where it persists. The decision (gitignored local store, central copy as future unit 1) was
  taken and recorded (audit, store decision).
- **Wrong: the targeted test command.** `python3 -m pytest scripts/tests -k "retro" -q` fails here (no pytest on the
  box or in `.toolchain`). The repo runs script tests as `python3 <test>.py` via `scripts/tests/<name>.test.sh`.
- **Wrong: the branch.** The harness launched the session on `claude/retro-api-skeleton-oqvm72`, the brief named
  `mod/retro-api`. The brief's name was used (PR comment 1).
- **Missing: the repo's admission rules for a new engine file.** The literal census (no bare numbers but 0, 1, -1), a
  registry entry per parameter, a unit manifest, a covers file, an `assets.json` entry, the generated config types and
  CODEOWNERS. Each was found by the pre-push hook, one push at a time.
- **Missing: the effort block.** The plan and PR body need `## Cheapest useful effort`; found by structure-check only
  when the gate was about to run.

## 2. Audit and plan

| Premise | Held? | Evidence |
|---|---|---|
| A transcript is JSONL with a string `type` on every line | held | 123/123 lines, then 2 real files stored |
| One log is far under 50 MiB | held | 603,492 then 1,350,871 bytes |
| Not committing the store is safe and reversible | held | the store moved as a directory in tests (`TOWER_RETRO_STORE`) |
| gitleaks comes from `scripts/cloud/setup.sh` | held only after a rerun: setup failed first (the config store, 429) | audit A9 |
| The repo's secret patterns can be used as they are | **broke**: every real transcript trips `generic-api-key` on `turnAttributionKey` | audit A11 |
| Other units' transcripts are unreachable | held | `no transcript for REQUESTS-REGISTER / ui-playback` |

Plan changes: one extra commit on item 2 (the retro-only scan exception), one on item 5 (refusal printed the source
twice), one on item 1 (effort block). The plan stayed sequential; no sub-agents were launched, because the code is
one module under 300 lines and every edge between commits was real or a collision on that file (plan.md).

## 3. Execution

Timeline (UTC, commit times):

| Time | Commit | Plan |
|---|---|---|
| 23:08 | `6d9f1157` audit skeleton, draft PR #798, STATUS | 1 |
| 23:11 | `0299bcd4` audit findings, store decision, plan | 1 |
| 23:14 | `df09240f` the store | 2 |
| 23:17 | `ef1d2c8b` the index | 3 |
| 23:19 | `9efde5b1` the ingest | 4 |
| 23:22 | `769b5d4b` the door | 5 |
| 23:25 | `899819fe` the scan exception for `turnAttributionKey` | 2 |
| 23:27 | `c39d109c` refusal names its source once | 5 |
| 23:29 | `7a34e376` future consumers and the proof on real data | 6 |
| 23:32 | `0d65f7e2` effort block and plan changes | 1 |

Failures and their root-cause class:

1. **External block, the GitHub write-budget state (class: shared session state outlives its cause).**
   `scripts/lib/forge_rate.py` held one recorded refusal with ~2,500 s of block while `/rate_limit` showed core
   13,774/15,000 left. Every `config.get` that reads the forge change store failed with 429. Setup failed, then the
   pre-push guard, then `gate-dev --pr` (it reads the PR through the same client). Worked within the rules with the
   documented `OU_CONFIG_STORE=file` for setup and pushes. The gate waited for the block to clear (~20 min).
2. **Literal census (class: new engine file meets an admission rule the brief did not list).** 8 bare numbers refused
   (`parents[2]`, `50 * 1024 * 1024`, `[:12]`, `hits[:10]`, test seeds). Fixed in one pass by the class: a registry
   entry for the one real parameter, the full digest instead of a prefix, `parent.parent.parent`, a hash-built
   fixture. A second census refusal (`/workspace/torre/motor`, a test `index[2]`) came from code written after the
   first fix; the same class fix (registry entry, `index[-1]`) covered it.
3. **Generated files and assets (same class as 2).** `config_registry_retro.py` missing, CODEOWNERS stale, then
   `scripts/retro` without an `assets.json` entry: three pre-push refusals, each fixed by the repo's own generator or
   one declaring entry.
4. **Secret scan on real data (class: a vendor field named like a credential).** Found by the first real run, not by
   the fixtures. Fixed by a retro-only allowlist with a test proving the same value under any other key is still
   refused.
5. **Test bug (my own):** a sorted key list in the wrong order; and an f-string that built a literal `\n`. Both caught
   by the targeted run before commit.

Where time went: about 25 minutes of code and docs. About 10 minutes on admission refusals (census, generated files,
assets). About 5 minutes on the scan finding. About 20 minutes waiting for the GitHub block before the gate.

## 4. Gate

- **Run 1** (23:30 UTC, head `7a34e376`): `gate-dev --pr 798` exit 2 at the pin stage: `FAIL cannot read PR #798
  head/base (exit 1)`, class `gate pin`. Cause: the session's GitHub write-budget block (failure 1 above), not the code.
  Structure-check run by hand at the same time found the missing effort block (fixed in `0d65f7e2`).
- **Run 2, the verdict of record**: once the block cleared, on the final head, which is this commit. Its numbers are
  quoted in the PR's RETRO and MERGE-READY comments, not here: writing them into this file would change the gated
  head and force a re-gate (the RETRO-after-green class of #629, #627 and #691).
- Known base defects hit: none.

## 5. Lessons

| Problem | Concrete change that would have prevented it | Owner |
|---|---|---|
| The brief asked for logs a cloud session cannot reach | Brief template: say which logs are reachable from the session's own container; for a store unit, ship the hand-in (future unit 2) before asking for multi-unit proof | A Torre (brief template) |
| The targeted test command named pytest, which is not installed | Brief template: name `bash scripts/tests/<name>.test.sh`, the repo's runner, never `pytest -k` | A Torre (brief template) |
| New engine file admission found push by push | One command, `scripts/units new <id> --script <name>`, that writes the manifest, covers file, test wrapper, registry file, assets entry and regenerates CODEOWNERS and types | engine-lane (engine-retro / units) |
| One stale GitHub refusal blocked setup, pushes and the gate for ~40 min while the real limit was far from exhausted | `forge_rate` should re-probe `/rate_limit` (one cheap read) before honoring a long recorded block, and print the block's origin | engine-lane (GX-FIX-forge-rate owner) |
| Every Claude transcript trips the repo's generic secret rule | Done here: `retro.scan_allowlist`; any future consumer that scans transcripts reuses `retro.secret_findings` | engine-lane (engine-retro) |
| The effort block was found at gate time | `scripts/commit-check --local` (pre-push) could run the plan.md effort check that structure-check already has | engine-lane (engine-commit-plan) |

## 6. The step that should have descended

| Repeated work done by an AI this time | Should descend to | Cost this time | Owner of the descent |
|---|---|---|---|
| Discovering the admission rules for a new engine script (manifest, covers, test wrapper, registry, assets, generators) by pushing and reading refusals | a deterministic script (`scripts/units new`), as in lesson 3 | ~10 min, 5 pushes of ~22 s each, ~8 turns | engine-lane |
| Deciding the branch name when the harness and the brief disagree (same decision as earlier units: the brief wins) | a rule in the engine: the launcher sets the harness branch to the brief's `mod/<unit>` | 1 turn, 1 PR comment | A Torre (launcher) |
| Deciding to work around the stale forge block with `OU_CONFIG_STORE=file` (the same decision other units took on rate limits) | a rule in the engine: `config.get` falls back to the registry value plus the local log when the forge store is rate-blocked, and says so on stderr | ~5 min, 3 turns, 1 STATUS | engine-lane (engine-config) |
| Writing the PR-comment and PR-body REST calls by hand (`curl` with a Content-Type header, JSON escaping) | a deterministic script (`scripts/pr comment --pr N --file F`, `scripts/pr body --pr N --file F`) | 1 failed call, ~3 turns | engine-lane (engine-github) |
| Measuring a transcript and classifying a gitleaks hit without printing the value | a deterministic script: `scripts/retro scan <file>` printing rule, offset and the 40 characters before the match | ~3 turns | engine-lane (engine-retro) |
| Waiting for the GitHub block by reading the block status by hand | an event: the forge client emits `forge.unblocked` and the gate starts on it | ~20 min wall | engine-lane (GX-FIX-forge-rate owner) |

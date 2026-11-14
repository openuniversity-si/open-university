# GX-15 audit (read-only, base `mod/roadmap-integration` at `fbc09f28`)

Brief: GX-15 "Structure tree part cached; `pr metadata` stage; `pr.checked`; local checks" (plan §3 GX-15, plan-v2 §4 row, D-070).
Every cited source was checked on the base: `scripts/lib/structure.py`, `scripts/lib/gate-stages.json`,
`scripts/lib/gate-hooks/prereq.sh` (GX-38 no-op), `config/registry/local-checks.json`, `scripts/lib/local_checks.py`,
`scripts/tests/test_structure.py`, `scripts/tests/test_local_checks.py`, `contracts/events/pr.checked.v1.json` (GX-37),
D-070 in `docs/domain/DECISIONS.md`, P-42 (GA-P01) and P-46 (GA-PG1) in the premise register. `config/registry/structure.json`
already exists (owner `structure`), so `structure.tree_cache_enabled` goes there (no new registry file).

## Findings

| # | Where (base) | Finding |
|---|---|---|
| A1 | `scripts/lib/structure.py:473-515` | The 24 modules run in one `main()`: capabilities, decisions (C5 age uses `--today`), links, assets, queue, migrations, absolute baseline, perf_tests, shared literals, config_check, literal_census, hermetic, text, toolchain, supply chain, vendor, production guard, premise register, defects, postmortems, decision_premises, unit_check; plus threshold (`:555-563`) and size (`:564-569`). |
| A2 | `structure.py:517-553` | PR metadata: `--pr-body` (B5 trailers, D-022 plan, `Premises:` line, visual_guard on the body), `--pr` (commit_check over REST judged on the gated sha (GX-14, done), visual_guard on the PR's body/files, the `Premises:` line), `--review`. |
| A3 | `structure.py:555-563` | **Correction to GA2 Q2**: `threshold_check` reads the PR body and the PR commit messages (`fetched['body']`, `commit['message']`), or `git log` messages without `--pr`. Commit messages are not in the head tree: two heads with one tree can differ. It is not tree-deterministic; it stays outside the cached part (0.14 s). The size warning is tree-only. |
| A4 | measured here (4 vCPU, `OU_CONFIG_STORE=file`, `--base origin/mod/roadmap-integration`) | Whole tree part **8.26 s** over 24 modules: config_check 2.74, literal_census 1.63, vendor 1.51, unit_check 0.82, perf_tests 0.70, hermetic 0.39, threshold 0.14, assets 0.10, abs baseline 0.08, the other 15 < 0.05 each. `scripts/structure-check --base …` wall 8.5 s. |
| A5 | `structure.py:438-441`, `decision_premises` | `changed_files(root, base)` diffs `base...HEAD`, i.e. from the **merge base**: the cache key needs the merge-base tree next to the head and base trees, or a head with the same trees but another merge base could reuse a wrong result. |
| A6 | `scripts/gate-local:365` (closed file) | The gate launches `structure check` with `--base "$base" --pr "$pr"`; nothing else calls `structure-check --pr` (`rg`). The call site cannot change: the split must come from `prereq.sh`, which `gate-local:44` sources before any launch and `:370` calls after the prerequisites are launched. |
| A7 | `scripts/lib/gate-runner.sh:104-124`, `gate_result_cache.py:89-97` | The generic stage cache (`step_cached`, `gate_stage_key`) keys on declared `inputs` without the base tree; `structure check` runs through plain `step` (`gate-local:365`), so a `deterministic` declaration alone caches nothing. The tree cache lives in `structure.py` and keys on (head tree, base tree, merge-base tree, gate_version, tool registry, config overrides, today). `gate_graph.validate:62` requires a deterministic stage to declare `inputs` and an integer `version`. |
| A8 | `scripts/lib/gate_policy.py:16-17`, `gate-areas.json` (`order`, `always`, `subjectInstallUnless`), `gate_graph.check:159-166` | A new stage name must be known to the plans (`PREREQUISITES`), or `gate_graph check` refuses its declaration and `gate_report.apply_coverage:144-165` cannot expect it. Declaring `pr metadata` there is a consequence of this unit's own stage (own-dependency rule). Every plan then expects it, so the hook launches it on every run; without `--pr` it judges nothing and passes. |
| A9 | `gate_suite.verify_stages:56-71` | Stage names are discovered from `gate-local`/`gate-fixed.sh`/`gate-db.sh` source only; a plan stage launched from a hook is not "unassigned". |
| A10 | `contracts/events/pr.checked.v1.json` (GX-37, on the base) | Payload `{repo, pr, sha, unit, premises, base_sha, result, errors[]}`; natural key `(repo, pr, sha, base_sha)`, so the event id excludes `result`: a second run on the same head and base after a comment that flips the verdict is deduplicated as the same event. Contract is closed for this unit: CANDIDATE comment (v2 key with a result digest). |
| A11 | `scripts/lib/gate_report.py:86-100` | Pattern for publishing: `forge_events.ForgeEvents(adapter_from_config(), clock_from_config(), producer, correlation)`, premises from the body, one `publish`. Producer names are registry values (`forge-events.gate_producer`, `plan-tick.event_producer`): `structure.event_producer` is new. |
| A12 | `config/registry/local-checks.json`, `local_checks.py:181-210` | Six checks today (`structure_fast` covers decisions, queue, links, postmortems, premises, plan). Total budget `local-checks.total_budget_ms` 30000. The GA2 Q2 base-relative modules (config_check, literal_census, vendor, unit_check, perf_tests) are missing (F-15). Each handler needs the base: `Context.base()` exists. |
| A13 | Environment (this container) | The shared config store read hit `gh: exit 429 (rate-limited) … wait 502 s` at 01:56 UTC; `scripts/cloud/setup.sh` exited 2 ("missing host tool: python3", the config read in `python_ok`). `OU_CONFIG_STORE=file` (named in the error) installed the toolchain. Env class (GX-ENV), recorded, not changed here. |

## Already done by merged units (not redone)
- GX-14 #702: metadata judged on the gated sha, REST cut, `gated_fetch` (`structure.py:448-452`), comment cut-off (`commit_check.gated_push_time`).
- GX-37 #706: `pr.checked.v1` contract, lock, generated modules, `EVENTS.md` section (used, not edited).
- GX-38 #700: `gate-hooks/prereq.sh` seam (body replaced only).
- GX-FIX-forge-rate #718/#720: batched publish, `forge-events.file_kinds` (pr.checked is a verdict, it stays on the main log).
- GX-17 #699, GX-03, GX-39 #705: not touched by this unit.

## Tests that cover the diff
`structure-check.test.sh` (`test_structure.py`), `local-checks.test.sh` (`test_local_checks.py`), `event-contracts.test.sh`
(`test_event_contracts.py`, already has a `pr.checked` sample), `gate-graph` (`gate-stages.json`), `config.test.sh` (registry).
Covers sidecars exist; new inputs (`config/registry/structure.json`, `gate-hooks/prereq.sh`) are added to `covers/structure-check.json`.

## Known defects / collisions
Base env failures: `claude-session.test.sh`, `root-identity.test.sh`, `config.test.sh`; KD-335a14a4, KD-71c8e5fe, KD-27b768cb,
KD-a3870679, KD-41f822d3 (not touched). Overlaps: #683 GS2 (`gate-stages.json`), #662 N1 (`structure.py`): catch-up by merge commit.

## Branch
The harness named `claude/gx15-structure-tree-cached-3my41n`; the brief names `mod/gx15` (brief standard v2 rule 1, as GX-14). Decision: `mod/gx15`.

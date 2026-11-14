# TH1 audit: thresholds only tighten; hermetic carve-outs listed

Brief: enforcement audit 26/10 rule 5 "never loosen thresholds or timeouts" (fixes R1 and R8), D-069 item 14.
Base: `origin/mod/roadmap-integration` at a2c09043 (includes LR1 #575 and CO1 #576). Read-only evidence below.

## Findings

1. **No check compares a registry threshold with the base (R1).** `scripts/lib/config_check.py` validates the
   registry's shape and refuses literals; its only base comparison is that `x-literal-sites` shrinks
   (`check_sites_shrink`). `scripts/lib/config.py` already has `diff_ref(ref)`, the registry defaults added, removed
   or changed since a git ref, but nothing in the gate calls it. Evidence: H1 raised `tests.script_timeout_ms` from
   60000 to 600000 inside one PR (#517 -> #519) and the gate passed.
2. **A registry default edited in a PR leaves no audit event.** `scripts/config set` records `config.changed`
   (`config._record`); a direct edit of `config/registry/<owner>.json` writes nothing. The payload contract
   `contracts/events/config.changed.v1.json` (name, old, new, actor, reason, at, plus the subject fields) fits the edit.
3. **`hermetic.without_harness(env)` call sites are not listed (R8).** `scripts/lib/hermetic_check.py` judges
   wall_clock, random and socket only. The two call sites, `scripts/tests/test_claude_session.py:152` and
   `scripts/tests/test_root_identity.py:67`, drop the network guard for the child that runs `scripts/cloud/setup.sh`,
   and nothing names them in `tests.unhermetic_sites`.
4. **The allowlist only shrinks, so listing pre-existing sites is refused today.** `hermetic_check.check` refuses
   every site the base list did not hold. Listing a carve-out that already exists at the base is disclosure, not new
   debt; the shrink rule has to tell the two apart (judge the base file with the same rules) without loosening it.
5. **The registry meta-schema has no direction key.** `contracts/config/registry.v1.json` `$defs/parameter` is
   `additionalProperties: false`; `x-monotonic` must be added there (additive, expand).
6. **Wiring.** structure-check (`scripts/lib/structure.py` `main`) runs config_check and hermetic_check with
   `--base`; the gate passes `--base` and `--pr` (`scripts/gate-local:280`). With `--pr` the body and the commits come
   from `commit_check.fetch`; with `--pr-body` the body is a file and the commits are `git log base..HEAD`.
7. **Ownership and test mapping.** `scripts/lib/config_check.py` is unit `engine-config`, `hermetic_check.py` is
   `engine-hermetic-tests` (both lane `engine-lane`); a new module needs a manifest path (`unit_check`) and a
   `scripts/lib/gate-script-tests.json` cover. `scripts/lessons for-area` returns no lesson for these paths.
8. **Authorizing decisions.** D-069 item 14 (never loosen thresholds) and D-025 (gate changes cite a decision);
   `scripts/lib/structure.py` is a gate file (`commit_check.GATE_FILE`).

## What exists and is reused (no second mechanism)

- `config.diff_ref` for base vs head defaults; `config.get` for the new `config.monotonic_patterns`.
- `forge_events.ForgeEvents.build` with a `MemoryAdapter` to build a valid `config.changed` envelope without writing
  the store (a report, not a change).
- `commit_check.decisions(root)` and `commit_check.DECISION` for the D-NNN citation.
- `hermetic_check.python_rules` for the new `harness` rule and for judging the base file.

## Known base defects

Timing-sensitive web tests on 4 vCPU (tower-catalog cover concurrency, read-latency 10,000 courses): owner web lanes;
never changed here.

# GX-11 plan

Goal: the gate tier is derived from the invocation (D-B5: `--tier3` → 3, `--pr` → 1, `--sha` without `--pr` → 2, working tree → 1) and every cache and the KD1 switch key on it; tier 2 and 3 neither read nor write box-local markers (D-065 (5), GA-P02 strict).

## Design
- `gate-hooks/tier.sh`: `gate_hook_tier` exports `OU_GATE_TIER` from `tier3`, `pr`, `sha` (the only channel into the Python stages without editing `gate-local`).
- `gate_tier.py` (one place): `explicit()` reads `OU_GATE_TIER`; `current`, `cacheable`, `adjudicated` keep their `(mode, tier1_modes)` signatures (GX-23 #728, GX-10, GX-13 #729 call them unchanged). With an explicit tier: `current` = the tier, `cacheable` = tier in `gate-tier.cacheable_tiers` **and** the mode in the caller's modes (the result cache stays dev-only: never looser than today), `adjudicated` = tier in `forge-events.adjudicated_tiers`. Without one (a caller outside gate-local, a unit test): today's mode behaviour, reading the modes passed in (the deprecated `forge-events.tier1_gate_modes` from gate_report) — the reader shim, so GX-13's reads never break. New `script_tests_cacheable()` for the per-test cache.
- `gate_test_cache.key()`: '' unless `gate_tier.script_tests_cacheable()` (no read, no write at tier 2/3); key routed through `gate_keys.key_parts()` (empty today, keys unchanged); `run` clears `OU_GATE_TIER` for the tests it runs (no env leak into nested unit tests).
- Registry: new `config/registry/gate-tier.json` `gate-tier.cacheable_tiers` [1] (D-B8 namespace; rollback `[1,2]` only with a D-NNN, it breaks D-065 (5)); `forge-events.adjudicated_tiers` [1, 2] (x-readers `gate_tier.py`); `forge-events.tier1_gate_modes` kept, marked deprecated (fallback only; gate_report still reads it; GX-26 retires it).

## Commits (Plan: N trailers)
1. audit.md — done.
2. plan.md (this file).
3. `gate_tier.py` derivation + `gate-tier.json` + `forge-events.json` keys + generated modules (`scripts/generate`) + new `scripts/tests/gate-tier.test.sh`/`test_gate_tier.py` + sidecar `scripts/tests/covers/gate-tier.json` + manifest line. Inert alone (nothing exports the tier yet). Tests: `scripts/run test gate-tier`, `config`-check via `scripts/commit-check --local`.
4. `gate-hooks/tier.sh` exports the derived tier + `gate-local.test.sh` no-op loop drops `tier` (consequence) + hook cases in `test_gate_tier`. Tests: `gate-tier`, `gate-local`.
5. `gate_test_cache.py` tier guard, `key_parts`, child env clear + `test_gate_test_cache.py` cases + covers sidecar names `gate_tier.py`/`gate-tier.json`. Tests: `gate-test-cache`, `gate-result-cache`, `train`, `battery`; observable warm-container tier-2 vs tier-1 run.
6. retro.md.

## Dependency graph / critical path
1 → 2 → 3 → {4, 5} → gate → 6. 4 and 5 share no file (4: tier.sh, gate-local.test.sh; 5: gate_test_cache.py, its test, its sidecar); both need 3's `gate_tier` API (real edge). Small enough that one writer does them in sequence (≈ 15 min each); sub-agents would cost more context than they save. Critical path ≈ 10 (3) + 15 (4) + 15 (5) + gate (~6) + retro 10 ≈ 60 min.

## Premises
- P-43 (GA-P02 strict, CRITICAL, decided): tier 2/3 reuse no box-local marker.
- D-B5 derivation (low): a hand `--sha` run becomes uncached tier 2 — slower, never less safe.
- Own decision (low, reversible): working tree → tier 1 (not a recorded proof; keeps today's caching for gate-quiet). `--noite --sha --pr` derives 1 (literal D-B5); posted as CANDIDATE.
- Own decision (low): the result cache keeps its dev-only mode set in addition to the tier, so no mode gains caching.

## Tests and gate
Targeted per commit (above); one pinned `scripts/gate-dev --pr 733` at the end.

## Known base defects expected
Env: `claude-session`, `root-identity`, `config` tests (GX-ENV); KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3.

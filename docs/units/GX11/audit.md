# GX-11 audit (read-only findings)

Base `mod/roadmap-integration` fbc09f28. Branch `claude/gx11-tier-explicit-4nhdog` (the session's designated branch; the brief's `mod/gx11` is not used, one branch only; same precedent as GX-39). PR #733.

## Cited sources, verified on the base
- `scripts/lib/gate_tier.py` (GX-39 seam, 19 lines): `current`, `cacheable`, `adjudicated`, all `(mode, tier1_modes)`, mode-based, read no config. Exists.
- `scripts/lib/gate-hooks/tier.sh:5` `gate_hook_tier() { :; }`; called once by `scripts/gate-local:78`, after argument parsing (`:58-77`), before the mode is resolved (`:92-97`). In scope at the call: `pr`, `sha`, `tier3`, `dev`, `noite`, `dbgate`. Exists.
- `config/registry/forge-events.json:206-215` `forge-events.tier1_gate_modes` (["dev"], x-readers `scripts/lib/gate_report.py`). Exists.
- `scripts/lib/gate_test_cache.py` `key()` `:129-166` has no tier guard at all: every mode, including `--tier3` and the train's `--dev --sha`, reads and writes box-local `script-tests/<key>` markers. GX-03 sizing (`script_tests_workers`, `gate_slots`) is on the base: done, not redone.
- `scripts/lib/gate_keys.py` `key_parts()` returns `[]` (GX-39 stub; GX-28 owns it). Already used by `gate_result_cache.py:80,96`; not by `gate_test_cache.key()`.
- `config/registry/gate-tier.json` does not exist; it is pre-claimed in `units/engine-gate-report/unit.json:10` (GX-38). `gate_tier.py` and `gate_test_cache.py` are claimed there too.
- `config/registry/train.json:143-159` `train.tier2_command` = `scripts/gate-batch --tier 2`; `scripts/gate-batch:31` runs `gate-local --dev --sha <combined>` (no `--pr`). `config/registry/battery.json:148-165` `battery.tier3_command` = `scripts/gate-local --tier3 --sha`. Both stay as they are (D-B5): the derivation gives 2 and 3.

## Readers of the tier (all through the seam; none edited here)
- `scripts/lib/gate_result_cache.py:34,41-43,76,92` (GX-23 #728 owns it): `gate_tier.cacheable(mode, TIER1_MODES={'dev'})`. With the seam deriving the tier, no edit is needed in this file.
- `scripts/lib/gate_proof.py:32` (GX-10): `tier=gate_tier.current(mode, tier1_modes)`; verdict contract v4 (`contracts/events/gate.passed.v4.json:56-61`) requires an integer 1..3 "never derived from the mode": today non-dev modes give `None`.
- `scripts/lib/gate_adjudicate.py:14,36` (GX-13 #729): `gate_tier.adjudicated(mode, tier1_modes)` = the KD1 switch.
- `scripts/lib/gate_report.py:65,78,85` (closed file) reads `forge-events.tier1_gate_modes` and passes it in. So the old key must stay registered and readable (a removed key would make `config.get` raise in gate_report); it becomes the fallback only (reader shim), deprecated.
- Consumers of `tier == 1`: `slo.py:63`, `forge_events.py:493` (`gate_slow`), `gate_status.py:194` (text only).

## Derivation (D-B5) on the real invocations
| Invocation | Today (mode) | Derived tier |
|---|---|---|
| `gate-dev --pr N` | dev, tier 1, cached | 1 |
| `gate-db --pr N` / legacy `gate-local --pr N` | tier null, not cached | 1 (result cache stays dev-only, see plan) |
| `gate-batch --tier 2` (train) → `gate-local --dev --sha` | dev, tier 1, cached (only a fresh `GATE_TEST_CACHE_DIR` from `engine_role.py:190-208` avoids reuse) | 2 |
| `gate-local --tier3 --sha` (battery) | tier null; script tests cached | 3 |
| `gate_noite.py:120` `--noite --sha H --pr N` | tier null | 1 (`--pr` present; see CANDIDATE) |
| working tree (`gate-quiet`) | pr mode | 1 (not a recorded proof; keeps today's caching) |

## Collisions found
- `scripts/tests/gate-local.test.sh:160-163` asserts `gate_hook_tier` is a no-op (`for h in tier proof prereq plan`). A real hook body makes it red: the minimal consequence of this unit is removing `tier` from that loop and asserting the derivation (GX-05 did the same for `pin`).
- Env leak: a tier exported by the hook reaches every script test (`gate_graph.run_commands` overlays env on `os.environ`, `gate_graph.py:147-148`); a train (tier 2) run would make unit tests of the result cache see tier 2. `gate_test_cache.run` must clear it for its children.
- No covers sidecar names `gate_tier.py` or `gate-hooks/tier.sh` today (`rg gate_tier scripts/tests/covers` empty): a change to them reruns no script test. Fixed by this unit's new test + sidecar.

## Already done by merged units (not redone)
GX-03 sizing, GX-17 forge-events keys, GX-38 hook call site and manifest pre-claims, GX-39 seams, GX-14/GX-37/GX-FIX-forge-rate (forge budget, contracts): nothing of GX-11 is in them.

## Out of scope (fenced)
`train.json`, `battery.json`, `docs/operations/train.md` (GX-06 runbook line → GX-26), `gate-local`, `gate_report.py`, `gate_keys.py`, `gate_proof.py`, `gate_publish.py`, `gate_adjudicate.py`, `gate_result_cache.py`.

## Known base defects (not this unit)
Env: `claude-session.test.sh`, `root-identity.test.sh`, `config.test.sh`; KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3 (GX-ENV, GX-FIX-modules).

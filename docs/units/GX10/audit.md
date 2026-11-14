# GX-10 audit

Base `mod/roadmap-integration` eaeeb29d (GX-37 #706, GX-38, GX-39 #705, GX-09 #723 merged). Cited sources verified present on the base: `contracts/events/gate.{passed,failed}.v4.json`, `scripts/lib/gate_digest.py`, `scripts/lib/gate_proof.py`, `scripts/lib/gate-hooks/proof.sh`, `config/registry/gate-contracts.json`, `scripts/tests/test_gate_v4_readers.py`, `toolchain_manifest.install_id()`, `pr_ready.lane_of()` (GX-04's lane function). `config/registry/gate-proof.json`, `scripts/lib/gate_proof.py` and `scripts/tests/test_gate_report_v4.py` are pre-claimed in `units/engine-gate-report/unit.json:9,20,42`; `scripts/lib/gate-hooks/**` in `units/engine-gate-run/unit.json:23`.

## Where the gate builds or records its verdict (base eaeeb29d)

| Place | file:line | What it does today |
|---|---|---|
| Base sha known | `scripts/gate-local:169-187` | `base` = batch plan base (`:171-172`) or the PR's `baseRefOid` (pin hand-off or one REST read, `:179-183`); empty for a plain `--sha` or working tree |
| Proof hook | `scripts/gate-local:188-191` | `export OU_GATE_BASE_SHA="$base"`, `OU_GATE_PASS_EXTRA=""`, `gate_hook proof`; the hook is a no-op (`gate-hooks/proof.sh:5`). Runs after the lock and the slot (`:152-168`), before `tmp`/`logs` exist (`:193`) and before classification writes `logs/selection.json` (`:380-392`) |
| Gate version | `scripts/lib/gate_pin.py:159-161,290` | `gate_version` = tree id of `scripts/` at the tooling commit; passed as `OU_GATE_VERSION` but **unset** by `gate_pin_handoff` (`gate-hooks/pin.sh:34`) before the proof hook runs, so the hook recomputes it from `tool_root` with the same recipe |
| Stage start | `scripts/lib/gate-runner.sh:66-67` | `<stage>.stage.json` carries `started_at` (epoch seconds, GX-38) and `seconds`; `cached` when the stage cache served it (`gate_report.py:197`) |
| Verdict payload | `scripts/lib/gate_proof.py:30-44` | `verdict_payload` builds the v3 payload: subject, `tier` (`gate_tier.current`, 1 or None), `plan`, `stages` (`stage_records:12-17`), `missing_stages`, `input_hash`, `cached_tests`, `known_defects`, `failing_tests` |
| Envelope | `scripts/lib/gate_report.py:69-71` | `port.build(kind, verdict)` with **no version**: `forge_events.default_version` (`forge_events.py:219-225`) takes the registry default of `gate-contracts.gate_{passed,failed}_version` = 3 |
| `.pass` record | `scripts/gate-local:503-509` | `sha`, `date`, `nightly`, `host`, `kind`, `db`, then `OU_GATE_PASS_EXTRA` verbatim (`:507`), then `pr`, `neon` |
| REST count | `scripts/lib/gate_report.py:233-243` | `forge_cost(logs)`: reads/writes from the `github-client.count_file_env` file of this run |

## v4 field → who can know it, and from where

| v4 field | Known at | Source |
|---|---|---|
| `head_tree` | proof hook | `git -C src_root rev-parse <sha>^{tree}` |
| `base_sha` | proof hook | `OU_GATE_BASE_SHA` (recorded: `baseRefOid` or batch base; never a local ref) |
| `base_tree` | proof hook | `git rev-parse <base>^{tree}` |
| `gate_version` | proof hook | `git -C tool_root rev-parse HEAD:scripts` (gate_pin's recipe; the base tip's tooling under the pin) |
| `toolchain_id` | proof hook | `toolchain_manifest.install_id()` |
| `selection` | kind/units/tests at report (`logs/selection.json`); digest at proof hook | the digest is over the selection **request** (plan + batch selection), which together with head/base/gate fixes the scoped plan; see Finding 2 |
| `input_digest` | proof hook | `gate_digest.input_digest(head_tree, base_sha, plan, selection_digest, toolchain_id, gate_version)` |
| `lane_id` | proof hook | `pr_ready.lane_of(src_root, base, sha)` (GX-04), None when several lanes or no unit |
| stage `started_at` | report | `<stage>.stage.json` `started_at` → RFC 3339 |
| stage `cached` | report | `<stage>.stage.json` `cached` |
| stage `inputs_digest` | report | conservative: sha256 over (input_digest, stage name) until GX-23 declares per-stage inputs |
| `cost.wall_s` | report | now − gate start (`gate_started`, passed by the hook) |
| `cost.cpu_s` | report | `/proc/<gate-local pid>/stat` utime+stime+cutime+cstime delta from the hook (gate_report is the driver's direct child) |
| `cost.rest_calls` | report | the run's count file (`forge_rate.counts`), reads + writes; 0 when the run counts nothing (the contract says integer, not null) |
| `cost.queue_wait_s` | proof hook | hook moment − gate start (preflight, lock and slot wait) |
| `cost.cache_hits/misses` | report | cached stages + cached script tests / stages that ran |
| `tier` | report | v4 requires 1..3; `gate_tier.current` gives None for non-tier-1 modes (GX-11 makes it explicit) |

## Findings

1. **The envelope version has no seam.** `gate_report.py:71` builds the verdict with no version, so even a v4 payload from `gate_proof` would be wrapped as v3 and refused by `event_contracts.validate`. The only rule-compliant registry route is moving `gate-contracts.gate_*_version` (GX-37's file, read as a registry default, not through the store), which breaks the one-key rollback the brief asks for (`gate-proof.event_version=3`). Decision: the one-line minimal edit in `gate_report.py:71` passing the version `gate_proof` chose (`gate_proof.version_of(verdict)`); all logic stays in `gate_proof.py`. Reported in the PR as a decision.
2. **The `.pass` extras are fixed at the proof hook**, before classification writes the scoped plan. `input_digest` is therefore defined over the selection *request* (`{plan, batch selection}`), known at the hook: for a tier-1 run the scoped plan is a pure function of head tree, base sha and gate version, all in the digest, so the binding is complete and the `.pass` and the event carry the same digest without a `gate-local` edit.
3. **`tier` is None for non-tier-1 modes** (db, noite, tier3); v4 requires 1..3. A run with no tier, no base or no sha keeps the v3 payload (byte-identical) and says why on stderr; v4 needs a full binding.
4. `cost.rest_calls` is an integer in the contract (`gate.passed.v4.json` `cost.rest_calls`), so the brief's "else null" is 0 when nothing was counted.
5. Readers: `test_gate_v4_readers.py` (GX-09) already accepts a v4 payload of this shape; nothing to change there.

## Not in scope (owners)

`gate-local` (GX-38), `gate-runner.sh`, contracts/lock/EVENTS.md/`gate_digest.py` (GX-37), readers (GX-09), `gate_keys.py`/`observed_versions` (GX-28), `carried_from` (GX-20), explicit tier (GX-11), per-stage inputs (GX-23). Known base defects KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3 and env tests claude-session/root-identity/config (GX-ENV).

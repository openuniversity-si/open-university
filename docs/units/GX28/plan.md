# GX-28 plan

Premises: P-43 (GA-P02, CRITICAL, decided: attestation is the precondition of tier-2 reuse). Blast radius of this unit: medium (keys and proof only; one-time cache churn; rollback = revert of the merge commit).

## Items (one commit each, `Plan: N`)

1. `audit.md` (done).
2. `plan.md` (this file).
3. **Attested toolchain id** — `scripts/lib/toolchain_manifest.py`, `config/registry/toolchain.json` (`toolchain.observed_tools`, list, default `[python, node, pnpm, gh, gitleaks, vercel, postgres, chromium]`), generated config module, `scripts/tests/test_toolchain_pins.py`.
   `attestation()` returns `{toolchain_id, observed_versions, registry_digest}`:
   - `observed_versions`: each listed tool's version as run from `.toolchain/bin` (`observed_version`), `absent` when the binary is missing or fails; chromium = Playwright's `browserVersion` when its revision directory is installed, else `absent`. Memo in `.toolchain/attest.json` keyed by the binary's stat identity (realpath, size, mtime_ns, inode), never by `install.stamp`.
   - `registry_digest`: sha256 of every registered name's effective value (`config.get`: defaults + the change store, local log included).
   - `toolchain_id` = sha256 of canonical JSON `{install: install_id(), machine, observed_versions, registry: registry_digest}`.
   Tests: a fixture `.toolchain` (fake bin scripts) whose one stale binary changes the id; a registry override changes the id; a stale stamp never changes the result.
4. **Cache keys** — `scripts/lib/gate_keys.py`: `key_parts()` = `['toolchain', attestation()['toolchain_id']]`, memoized per process; an attestation that fails gives a unique part (fail closed: every cache misses). `scripts/lib/preflight.py`: `missing_tools()` no longer trusts the stamp alone (it observes; the memo keeps it cheap). Tests: `test_gate_result_cache.py` (step and stage key differ for a stale toolchain), `test_preflight.py`. Seam for GX-11: `gate_test_cache.key` should append `*gate_keys.key_parts()` (not edited here).
5. **v4 proof** — `scripts/lib/gate_proof.py`: `bind()` takes the attested id and records `observed_versions`; `proof_payload()` carries it. Tests: `test_gate_report_v4.py`.
6. **Vercel tree pinned** — `scripts/cloud/toolchain.json` gets `vercel.lock[<version>]` (the npm lockfile v3 `packages` of the installed tree); `scripts/cloud/toolchain.py` installs with that lockfile (`npm ci`) and `vercel_deps_ready` checks the installed tree equals the pin. Tests: `test_toolchain_pins.py` (every lock entry has `integrity`, resolved from registry.npmjs.org, the root is the pinned version). No Vercel command is run.
7. RETRO `retro.md`.

## Graph and critical path

3 → 4 → 5 are a real chain (4 and 5 call `attestation()`); 6 is independent (own files: `toolchain.py`, `toolchain.json`, the Vercel part of `toolchain_manifest.py` — shared with 3, so 6 runs after 3 is pushed). Critical path: 3 (20 min) → 4 (10) → 5 (10) → gate (≈15) → retro (10) ≈ 65 min; 6 (15) runs beside 4–5. Sole writer of the branch: this session; sub-agents not used (the files chain).

## Tests per commit, then one gate

3: `scripts/run test toolchain-pins`, `toolchain-check`; 4: `preflight`, `gate-result-cache`, `gate-test-cache`; 5: `gate-report-skips`; 6: `toolchain-pins`, `cloud`. Final: pinned `scripts/gate-dev --pr 738`.

## Known base defects expected

claude-session, root-identity, config (GX-ENV); KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3.

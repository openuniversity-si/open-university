# GX-28 audit

Base `mod/roadmap-integration` 3cae824a (GX-10 #727, GX-23 #728, GX-13 merged). Cited sources verified present on the base: `scripts/lib/gate_keys.py` (GX-39 stub), `scripts/lib/gate_proof.py` (GX-10 v4 builder), `scripts/lib/toolchain_manifest.py`, `scripts/lib/preflight.py`, `scripts/cloud/toolchain.py`, `scripts/cloud/toolchain.json`, `contracts/events/gate.{passed,failed}.v4.json` (`observed_versions` already declared, optional). Not present: the `toolchain.observed_tools` registry key (this unit adds it).

## How `toolchain_id` is made today

| Place | file:line | Behaviour |
|---|---|---|
| Recipe | `scripts/lib/toolchain_manifest.py:79-83` | `install_id()` = sha256 of the **pinned** specs (`load()`: registry versions + manifest checksums) and `machine()`. Nothing installed is looked at |
| Proof | `scripts/lib/gate_proof.py:135-148` | `bind()` takes `toolchain_manifest.install_id()` when no id is passed; it goes into `input_digest` and the `.pass` extras (`:67`) and the v4 payload (`:235`) |
| v4 payload | `scripts/lib/gate_proof.py:231-239` | no `observed_versions` (the contract field `gate.passed.v4.json:153`, `gate.failed.v4.json:165` stays absent) |
| Cache keys | `scripts/lib/gate_result_cache.py:118-126,135-144` | tier-1 step and stage keys end with `*gate_keys.key_parts()`; `gate_keys.key_parts()` returns `[]` (`gate_keys.py:6-7`), so the keys carry only the registry **pins** (`TOOLCHAIN_PINS :42`) and `node -v` from PATH (`gate_speed.py:43-49`) |
| Test cache | `scripts/lib/gate_test_cache.py:168-172` | key = pins + `node -v`; does not call `gate_keys` (GX-11 #733 owns the file: seam, not edited here) |
| Preflight stamp | `scripts/lib/preflight.py:50-56` | `_stamp_ready()` trusts `install.stamp == install_id()` and the binaries existing; when true no version is observed. The stamp is written by `scripts/cloud/toolchain.py:219` |
| Setup ready | `scripts/cloud/toolchain.py:181-190` | same stamp shortcut |
| Effective registry | `scripts/lib/config.py:133-150,185-205,356-385` | `_params()` (defaults) + `overrides()` (the change store, file log or remote) give the effective values; nothing digests them today |

Finding 1 (F-17): a container whose `.toolchain/` holds other binaries than the pins (stale stamp, a hand-replaced binary, a partial reinstall) gets the **same** `install_id`, the same proof `toolchain_id` and the same cache keys, so a result proven on one toolchain is reused on another.

Finding 2: a machine-local change of any registry value (e.g. a stage timeout, a test-cache TTL) changes what the gate does but not the id.

## Observed versions available

`toolchain_manifest.observed_version(tool, root)` (`:151-170`) runs each binary in `.toolchain/bin`. Measured on this container: node 0.008 s, postgres 0.011 s, gh 0.08 s, vercel 0.10 s, pnpm 0.43 s, gitleaks 0.45 s, python 10.2 s cold (first compile) / <1 s warm. The probes cost ~1 s warm, and `gate_keys.key_parts()` is called for every key, so the attestation needs a memo keyed by what it attests (the binary's stat identity), never by the stamp.

Chromium: the e2e browser is Playwright's (`apps/web` `@playwright/test` 1.64.0, `playwright-core/browsers.json`: chromium revision 1248, `browserVersion` 156.0.8078.4); installed under `PLAYWRIGHT_BROWSERS_PATH` or `~/.cache/ms-playwright/chromium-<revision>` (`scripts/cloud/setup.sh:152-153`). Observable without a subprocess: the revision directory present or not.

## Vercel CLI dependency tree

`scripts/cloud/toolchain.py:150-176`: `npm install --omit=dev --no-package-lock <vercel.tgz>`. Only the top tarball is pinned (`toolchain.json:42-46`, `integrity`); its ~296 transitive packages (`.toolchain/vercel/node_modules/.package-lock.json`, `luxon: ^3.4.0` etc.) resolve to whatever the registry serves that day. `vercel_deps_ready()` (`toolchain_manifest.py:146-148`) checks one file.

## Tests in scope (covers)

`preflight.test.sh` (`test_preflight.py`), `toolchain-pins.test.sh` (`test_toolchain_pins.py`), `toolchain-check.test.sh`, `gate-test-cache.test.sh`, `gate-result-cache.test.sh` (`test_gate_result_cache.py`), `gate-report-skips.test.sh` (runs `test_gate_report_v4.py`, which recomputes `input_digest` with `install_id()` at `:112-117`).

## Known base defects (not this unit)

claude-session / root-identity / config env tests (GX-ENV), KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3.

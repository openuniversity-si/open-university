# TX12 audit — env premises labelled env, not code

Base: `mod/roadmap-integration` 891b835ae. Line numbers are on that base. Every brief citation was re-verified; the
two that no longer hold as written are marked.

## How a red stage is classified

`scripts/lib/gate_classify.py:47-48`: a stage is env when the log matches `ENV` (`:30-35`, which includes `FAIL env: `
at `:34` and `No module named 'encodings'` at `:30`) and does not match `CODE` (`:38-40`, which starts with
`AssertionError`). So a premise the test raises as `AssertionError` is code even when its own text is env evidence.

## Findings

| # | Where | Finding | Class today |
|---|---|---|---|
| F1 | `scripts/tests/test_root_identity.py:30-32` | `run_unprivileged` raises `AssertionError` when `setpriv` is missing: a host tool, i.e. env | code |
| F2 | `test_root_identity.py:35-41` | The uid 65534 child re-runs `sys.executable` on this file. An interpreter or checkout that uid cannot read (a toolchain under a 0700 home, HD1 retro:43, `init_fs_encoding`) crashes the child; `:41` wraps the crash in `AssertionError` | code |
| F3 | `scripts/lib/gate-isolation.sh:124` | For uid 0 the slot checkout defaults under `$HOME/.cache` = `/root` (0700) unless `GATE_CHECKOUT_ROOT` is set (`scripts/cloud/env.sh:137-139`); a checkout there is not traversable by uid 65534, same crash as F2 | code |
| F4 | `test_root_identity.py:62-71` | `ensure_toolchain` runs `setup.sh` (network, up to 600 s) when `.toolchain/bin/initdb` is absent, and wraps its failure in `AssertionError`: a missing toolchain is env. The gate's slot checkout has no `.toolchain`, so this run is how a slot gets one (found by gate run 1) | code |
| F5 | `test_root_identity.py:94-98` | Not root: `sudo -n env K=V… python3 root_probe.py`; `sudo` resets the environment, so `OU_CONFIG_STORE` (the test's local store, `hermetic.store_env()`) is lost and the uid 0 probe reads the shared store. A missing `sudo -n` raises `FileNotFoundError`/a sudo prompt failure wrapped at `:100-101`; `:102-108` assert the report | code |
| F6 | `test_root_identity.py:208-216` → `scripts/lib/session_identity.py:133` | `add_system_user` reads `env.session_id_floor/ceiling` through `config.get`, which replays the change store (`scripts/lib/config.py:197-209`). `env` is not a bootstrap owner (`config/registry/config.json:189-194`: `cloud`, `toolchain`), so with an empty `.tower/config-cache` and no token the read fails (`StoreUnavailable`, rate-limited); the test passes only on a fresh cache (masked failure) | code |
| F7 | `scripts/tests/test_claude_session.py:115-116`, `:205-206` | Deletes the real `.toolchain/preflight.stamp` (path from `scripts/lib/credentials.py:72-73`, `toolchain_dir()`), and the preflight run it starts writes the real stamp: every other checkout user of `.toolchain` loses or inherits a fixture probe | shared state |
| F8 | `test_claude_session.py:156-159` | `setUpClass` runs `setup.sh` (network on a cold toolchain, up to 600 s). With no installed toolchain that is a machine premise, reported as `RuntimeError('setup failed')` | code/unclear |
| F9 | `scripts/cloud/env.sh:26` | `OU_SHIM_GUARD` is honored only under `/tmp/*`; the test's guard is a `tempfile` directory, which follows `$TMPDIR`. With `TMPDIR` elsewhere the tripwire is silently ignored and the assertions about host tools fail as code | code |
| F10 | `scripts/cloud/env.sh:128-129` | Brief: `_ou_cloud_postgres_host[0]: unbound variable`. **No longer reproduces**: every `_ou_cloud_load` call ends in `|| return 1` (`:92`, `:128`, `:138`; `:113`) and the loader prints `FAIL env:` (`:55-58`), already env. No change. | env |

## Not changed (fences)

- `scripts/lib/gate_classify.py` (TX11): the existing `FAIL env: ` pattern is used as is.
- `scripts/lib/gate_test_cache.py`, `scripts/lib/gate-runner.sh`, `scripts/run` (TX10).
- `test_non_root_chromium_keeps_the_sandbox` keeps its existing `skipTest` (`:319-320`); no skip is added.

## Outside the brief's OWN list, inside engine-lane

- F6 needs `env.session_id_*` to be a bootstrap read: the keys move to a new owner `env-premises`
  (`config/registry/env-premises.json`, unowned registry path) and `config.bootstrap_owners` gains it
  (`config/registry/config.json`, unowned). No other TX unit lists either file (plan revision 2 §units).
- F7 needs a per-test stamp path: `scripts/lib/credentials.py` (unit engine-github, engine-lane) honors
  `OU_PREFLIGHT_STAMP`. No other TX unit lists it.

## Baseline

`test_root_identity.py`: 8 tests, 77 assertion sites (`self.assert*` + `raise AssertionError`).
`test_claude_session.py`: 12 tests, 70 assertion sites.

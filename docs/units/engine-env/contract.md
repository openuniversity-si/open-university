# engine-env contract (v1.0.0, documented)

The manifest `contract` slot needs a TypeScript address (`unit_battery.plan`), which no Python unit has, so the surface is recorded here until an address form exists (P-07: adding the slot later is additive). Computed from the importers under `scripts/`:

| Module | Public surface (imported by other units) | Importers |
|---|---|---|
| `scripts/env-check`, `scripts/env-update` | command lines (unchanged paths and behaviour) | idea-to-prod, gate_classify |
| `preflight.py` | `require` | `ship_tail` |
| `session_identity.py` | `exclusive_lock`, `open_lock`, the identity exports of `root-session.sh` | `gate_suite`, `gate_noite`, `ship_verify`, `neon_pr`, `cloud/toolchain`, `cloud/postgres` |
| `toolchain_manifest.py` | `toolchain_dir`, `load`, `versions`, `artifact(name, data=None)`, `install_id`, `machine` | `credentials`, `test_db`, `cloud/toolchain`, `cloud/postgres` |
| `toolchain_check.py` | `check` | `structure` |
| `env_manifest.py` | command lines only | none |

`artifact`'s `data` argument is an expansion (optional, default unchanged). Anything not listed is internal.

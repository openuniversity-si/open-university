# engine-neon contract (1.0.0)

The unit is logical (S1, P-03) and has no `@ou/` address, so the manifest `contract` slot stays empty (a filled slot is red in `scripts/unit-battery`: the contract step needs an address, see the audit). The published surface is the executables and the module functions other units call today:

| Surface | Behaviour |
|---|---|
| `scripts/neon-migrate <preview\|prod> [--dry-run]` | forward migrations of the Neon preview or production branch (frozen, D-054) |
| `scripts/neon-pr <action> <pr> …` | lifecycle of the disposable `pr-<n>` branch |
| `migration_order.py merge-ready [--pr N]` | called by `scripts/merge-phase`; exit 0 when the commit may merge |
| `neon_pr.{eligibility,hook_plan,hooks,branch_env,Neon}`, `neon_migrate.{main,migrate}` | imported by `scripts/tests/test_invoker_tooling.py` and the delivery tail |

A breaking change goes expand->contract (P-07, D-029): add the new form, move callers, then remove the old. No consumer file is edited here.

Literals: every tunable is a `neon.*` entry of `config/registry/neon.json` (20 entries), read through `config.get`. The protocol identifiers `TARGETS` and `VARIABLES` (the `db:migrate --target` ids and their environment variable names) stay in code because they name the app's database targets, not tunables. No `x-literal-sites` entry names the unit. Battery: `scripts/unit-battery engine-neon`, limit `battery.unit_time_limit`. Generated outputs: `scripts/generate --check` shows no drift.

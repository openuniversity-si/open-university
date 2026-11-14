# engine-production contract (1.0.0)

The unit is logical (S1, P-03) and has no `@ou/` address, so the manifest `contract` slot stays empty (a filled slot is red in `scripts/unit-battery`). The published surface is the two executables, which keep their paths and behaviour:

| Command | Behaviour |
|---|---|
| `scripts/production-check …` | the production hard check on a merge commit (ADR-32); frozen for sessions (D-054) |
| `scripts/preview-deploy …` | the on-demand preview of a release head, governed by `scripts/preview-policy.json`; frozen for sessions (D-054) |

Libraries (`production_check.py`, `production_guard.py`, `site_health.py`, `html_normalize.py`) are internal to the unit; other units reach production only through the executables. A breaking change goes expand->contract (P-07, D-029). No consumer file is edited here.

Literals: none (the no-literals check finds zero and no `x-literal-sites` entry names the unit); tunables live in `config/registry/production.json`. Battery: `scripts/unit-battery engine-production`, limit `battery.unit_time_limit`. Generated outputs: `scripts/generate` shows no drift for this unit.

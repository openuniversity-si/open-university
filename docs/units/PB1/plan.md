# PB1 plan

1. Docs: audit and plan (this folder). Owns docs/units/PB1/audit.md, plan.md.
2. Code: `premises.unquoted/standing`, check_line treats an unquoted confirmed premise as unsettled (radius decides); `answer` refuses confirmed without `--quote`. Registry: `premises.quote_required_statuses`, `premises.unquoted_grandfathered` (shrink-only, P-27..P-40). Owns scripts/lib/premises.py, config/registry/premises.json, scripts/tests/test_premises.py.
3. Retro. Owns docs/units/PB1/retro.md.

Commits 2 and 3 are sequential (3 needs the gate). Premises: P-41 (high, no literals: both tunables are registry entries); grandfathering is the reversible choice, so no existing PR citing P-27..P-40 breaks. Gate: one gate-dev at the end; targeted: `scripts/tests/premises.test.sh`.
Base defect fixed in passing: test_repository_register_is_valid expected P-03 answered by A Torre; it is validated by measurement:S1.

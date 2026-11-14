# TOOLCHAIN-ATTEST-STORE: plan

Base `mod/roadmap-integration` at `798ce595`. Class `code` (D-027). See audit.md.

## Commits
1. Intake and research.
2. Audit and plan.
3. `registry_digest()` hashes `config.files()` defaults only; tests in `test_toolchain_pins.py` (file vs shared store, committed tooling change) and `test_toolchain_attest_admit.py` (strict admission admits).
4. D-080.
5. Retro.
6. Gate round 1 (`structure check`): the audit's Padrão v6 sections and the PR body's effort block.

## Cheapest useful effort
Action: the targeted unittest modules, then `scripts/gate-dev --pr 809` on the final head.
Cost: one gate run.
Requirement: Daniel needs every PR to leave the tier-2 slow path now.
Cheaper rejected: only unit tests (they prove the id, not that the gate stays green).

Premises: none

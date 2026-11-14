# PB1 retro

1. Brief: clear. Missing: the old branch name was already taken by the closed PR, so the first push was refused; I used `-v2`. "Confirmed with a quote or blast declared" is ambiguous because every record declares a radius; I read it as: no quote means the radius decides.
2. Audit and plan: the premise that settled premises have quotes broke: 14 Daniel-confirmed records (P-27..P-40) carry only a `where` link. Plan changed to a shrink-only grandfather list in the registry.
3. Execution: one class failure, test fixtures and the generated types. A record without an `answer` key (decision_premises fixture) raised KeyError, and the registry change left generated Python types stale. Fixed in one commit with `get()` and `scripts/generate`. Base defect: test_repository_register_is_valid expected P-03 answered by A Torre (it is validated by measurement:S1); corrected.
4. Gate: 2 runs, 527 s and 408 s. Run 1 failed on drift and the KeyError. Run 2 passed; generate.test.sh's intents test errors on this machine (node cannot run apps/web/scripts/intents-doc.ts) and did not block the gate.
5. Lessons: a registry change should regenerate types in the same step (owner G1: a pre-commit hint); brief templates should state the exact branch name policy for restarts (owner CO1).

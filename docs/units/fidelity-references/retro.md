# fidelity-references retro (U4)

1. **Brief.** It asked to move the unit into `units/fidelity-references/`; S1 (P-03) keeps units logical, so nothing moved and no old path needed deleting. It named branch `mod/u4-fidelity-references`; the session's branch is `claude/u4-fidelity-references-gmuyx8`.
2. **Audit and plan.** The unit was already clean: zero literals, battery green in 6.0 s, `@ou/fidelity-references` already generated into tsconfig. No code change was needed; the deliverables are the audit, the contract document and this retro.
3. **Gate.** The first gate-dev (62 s) failed on `tests.unhermetic_sites gains scripts/tests/test_claude_session.py:random`, a base defect in a file this PR does not touch. After merging the updated base, gate-dev passed in 66.7 s (ceiling 180 s).
4. **Lessons.** (a) The contract slot stays empty for units whose surface spans several modules without an entry file; an entry file would be a shim (owner: lane). (b) Most importers still use relative paths to the unit; moving them to the address belongs to the importers' owners.

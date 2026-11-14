# engine-production retro (U4)

1. **Brief.** It named a branch (`mod/u4-engine-production`) that differs from the session's designated branch (used the latter). It assumed a physical move and a filled contract slot; for executables under `scripts/` neither applies (no `@ou/` address). It did not say the unit's battery was already over its limit.
2. **Audit and plan.** P-03, P-05 (zero literals already), P-07 held. Not oversize (1773 lines, under the ceiling by the production-lines measure).
3. **Execution.** One failure class: battery over limit (12.12 s vs 10 s) from a registry read per environment variable inside a comprehension in `test_production_guard.py`; fixed by hoisting the lookup (7.9 s, limit untouched). Cost found with cProfile, not guessing. Commits: 12905a66 audit, 77240863 plan, f990b4ad test, 039c6f17 contract. No dead ends.
4. **Gate.** `gate-dev --pr 614` green on d2280fb3 in 73 s wall (ceiling 180 s); the retro commit is docs only and is regated.
5. **Lessons.** (a) Brief template: state the unit's battery status and whether it has an address (owner: CO1). (b) `config.get` inside a loop or comprehension is a class worth a lint (owner: engine-config): each call re-reads overrides (about 36 ms).

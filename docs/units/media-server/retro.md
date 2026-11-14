# media-server retro (U4)

1. **Brief.** It named branch `mod/u4-media-server`; the session's designated branch is `claude/u4-media-server-4a5mer`, and the push guard pushed only there. The brief asked to move files into `units/media-server/`; S1 (P-03) keeps units logical, so nothing moved.
2. **Audit and plan.** P-03 held, P-05 held (literals already zero), P-07 held (contract is additive). The unit is 1,472 lines, close to `units.size_ceiling` (1,500): no `unit.oversize` yet.
3. **Execution.** One hermetic debt (`admin.test.ts:random`) fixed with the seeded source; contract slot filled, which made `scripts/generate addresses` add the bare `@ou/media-server` path. No dead ends.
4. **Gate.** gate-dev green in 625 s wall on 3c50e316 (ceiling 180 s, the whole gate is over it on this 4 vCPU box; script tests 373 s, lint 192 s are not this unit's). The retro commit is docs only and is regated.
5. **Lessons.** (a) Filling a contract slot changes generated `tsconfig` paths: regenerate in the same commit. (b) The gate wall time is far above the ceiling (owner: engine-gate-run).

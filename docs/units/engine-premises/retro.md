# engine-premises retro (U4)

1. **Brief.** It named branch `mod/u4-engine-premises`; the session's designated branch is `claude/u4-engine-premises-ibu44g`. The push guard pushed commits to the former, so both carry the same commits. The brief did not say the unit's battery was red (60.7 s, one failing test, KD-4db6e693).
2. **Audit and plan.** P-03 held (logical unit, no address for scripts), P-05 held (zero literals already), P-07 held (paths and behaviour unchanged).
3. **Execution.** Two causes: `premises.setting` called `config.get` per read, and each call replays the config store (12 s per register load); and a stale assertion on P-03's answerer. Both fixed inside the unit; battery 1.6 s. No dead ends.
4. **Gate.** gate-dev green in 134 s wall (ceiling 180 s) on 14fb5dc3; the retro commit is docs only and is regated.
5. **Lessons.** (a) `config.get` cost is per call; a shared memoized settings reader in engine-config would remove the class from every unit (owner: engine-config). (b) KD-4db6e693 is resolved by `scripts/defects resolve` with the merge sha after merge (owner: lane).

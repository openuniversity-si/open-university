# U4 tooling-literals: retro

- Delivered: contract 1.0.0 (`@ou/tooling-literals`, 29 names from the import graph) with its test, manifest entry, generated address and CODEOWNERS. Files did not move (P-03, S1).
- Battery: `scripts/unit-battery tooling-literals` green in 4.5 s.
- Gate 1 on 610a88bb: red only on `read-latency.perf.int` (1025 ms vs 1000 ms, known timing-sensitive on 4 vCPU); no other stage failed. Not changed.
- Not delivered: the 223 census-vocabulary literals (see audit.md); needs a TypeScript config reader, owner tooling-lane.
- Found: `domain-literals.*.test.ts` and `absolute-literals.heavy.test.ts` have no unit owner; U0 follow-up should assign them to this unit.
- Class fix: `generate all` fails on the on-demand `intents` target without node deps; use the committed targets (`addresses`, `codeowners`).

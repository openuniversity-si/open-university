# U4 fidelity-runner: audit and plan

Base `mod/roadmap-integration` at `bb8fb9b4`. Premises: P-03 (high: units stay logical, S1; if wrong the move is a later mechanical PR),
P-04, P-05 (see Literals), P-07 (the contract is new, so nothing breaks).

- **Physical form.** S1 answered P-03: logical units, the address `@ou/fidelity-runner` -> `apps/web/fidelity/*` is the seam. No file moves; the
  manifest paths stay valid and no old path is left behind (D-029).
- **Consumers.** `apps/web/e2e/fidelity.spec.ts` (owned by `testing-e2e`) is the only other unit that imports from the runner, by relative path:
  `FIDELITY_FRAMES`, `VIEWPORT_HEIGHTS` (frames), `type GeometryBox` (compare), `MEDIA_ART_MANIFEST`, `mediaArtKey`, `referenceMediaLayers` (media),
  `framesForPhase` (resolve). The `pnpm fidelity*` scripts run the Node entry points (`run.ts`, `selftest-run.ts`, `summary.ts`, `references-fetch.ts`,
  `media-fetch.ts`) directly; they are executables, not contract. The consumer file is not edited (not this unit's).
- **Contract.** `contract.ts`, version 1.0.0, exports exactly those names; `runner.contract.test.ts` fails when one is added or removed.
- **Battery.** `scripts/unit-battery fidelity-runner`: contract, types (19 files) and unit tests (4 files) green in 4.7 s of `battery.unit_time_limit`.
- **Literals (not delivered here).** The census list `scripts/lib/absolute-literals-baseline/fidelity.json` lists 2,062 occurrences in this unit's
  files (frames.ts 1,436: Figma node ids, routes and region ids; perceptual.ts 192; compare.ts 82; selftest.ts 78; the rest under 60 each). Zeroing them
  needs hundreds of documented D-063 catalog keys whose values must stay pixel-identical, and the thresholds of compare/perceptual have no TypeScript
  reader of the config registry (`config.get` is Python; shell and .mjs call `config.py`). Inventing a second reader here would be a parallel mechanism
  (D-069 item 1), so the list is left as is: it only shrinks (D-063 ratchet) and this PR adds no literal. Owner of the follow-up: fidelity-lane with the
  TypeScript config reader of the CW/L1 line.
- **Size.** 1,383 lines, below `units.size_ceiling` (1500): not oversize.

Commit plan: 1 contract entry + test + manifest + generated addresses/CODEOWNERS; 2 this document; 3 retro after the gate.
D-069 items: 5 (addresses and CODEOWNERS generated), 8 (ownership by manifest), 14 (battery 4.7 s, limit untouched), 3 (no literal added; remaining count recorded).

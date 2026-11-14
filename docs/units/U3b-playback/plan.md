# U3b playback: plan (lane playback-lane)

Mechanical PR (plan v3.1 §4, U3b is a Haiku lane). No file moves, no renames, no behaviour change.

## Commits (dependency graph)

1. **Audit and plan** (docs only): `docs/units/U3b-playback/audit.md`, this file. Owns only `docs/units/U3b-playback/`.
2. **playback-domain** imports (depends on 1): every cross-unit specifier of the `playback-domain` files that Node
   does not load gets its `@ou/<unit>/<path>` address (the address is taken from `scripts/units addresses`, the file
   is re-checked with `scripts/units owner`). Owns: `apps/web/src/playback/domain/**` (only the files this commit
   changes, none of which another commit touches).
3. **playback-client** imports (depends on 2 only through the shared `playback-domain` addresses, which are now stable
   addresses; it can be applied before 2 with no conflict since they touch disjoint files). Owns:
   `apps/web/src/playback/{application,client,ports,server,testing}/**`.

2 and 3 do not share a file, so they could run in parallel; they are sequential here to keep each commit's gate
evidence separate. Both are one-PR, one-merge.

## Rules applied to each specifier

- Same unit: unchanged (D-067 (1)).
- Cross unit, target has an address whose home holds the file and the file is owned by the target: `@ou/<target>/<path>`
  with the same extension style as the original (`.ts` kept when written, dropped when absent).
- Node-loaded file (the relative-import closure of `apps/web/scripts/**`, `apps/web/fidelity/**`, `apps/web/*.ts|mjs`):
  every specifier stays relative (D-069 item 7, as `3c0ffb84` and `2d7d70e2`). Recorded as a contract gap.
- Unowned target or a target without an address: stays relative and is recorded as a contract gap; the other unit is not
  edited.

## Tests per commit

- Targeted: `pnpm exec tsc --noEmit -p apps/web/tsconfig.json` (must print nothing, as the baseline) and
  `pnpm exec vitest list --project unit src/playback` / `--project int src/playback` against the census baseline.
- `scripts/units check` and `scripts/units addresses` after each commit.
- `scripts/unit-battery playback-domain` and `scripts/unit-battery playback-client` on the final head (tier 1).
- Final: `scripts/gate-dev --pr <n>` once, on the exact head.

## Premises and blast radius

- P-03 (stable addresses): HIGH. If an address resolved to the wrong file, imports would bind to another unit. Mitigated:
  each target is resolved and its owner checked before the rewrite; `scripts/units check` and tsc catch a wrong name.
- P-13 (exclusive ownership per lane): HIGH. Only the two units' files change; `scripts/units owner` is checked for every
  touched path.
- Node loader does not read tsconfig `paths` (observed on the base, owner: tooling): MEDIUM. Mitigated by keeping
  Node-loaded files relative; if the closure missed a Node-loaded file, the `scripts/tower-catalog`/`bundle:check` runs
  in the gate fail and the file is added to the list.
- No CRITICAL premise: no production, no secret, no source of truth, no spend.

## Expected base defects and owners

- `apps/web/next.config.ts` relative import into playback server code (site/web-build owner).
- `platform/db/testing/uow-contract.ts` has no owner (platform owner).
- Existing domain-to-client layering in two test files (playback-lane, follow-up).

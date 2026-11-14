# web-build contract (none published yet)

The manifest holds no `contract` slot, on purpose. `scripts/lib/unit_addresses.py` addresses a unit only when its home is a directory of its own inside the TypeScript project; `web-build`'s home is the project root `apps/web`, so it has no `@ou/web-build`, and a manifest contract without an address makes `scripts/unit-battery web-build` red (contract step).

What other units read today, by path (not edited here; they belong to other units):

| File | Readers |
|---|---|
| `next.config.ts` | `src/media/domain/direct-delivery.test.ts`, `src/site/domain/hosts.test.ts`, `test/site/noindex.test.ts` |
| `design/figma-tokens.snapshot.json` | `e2e/specimen.spec.ts`, `src/app/(test)/_specimen/TowerSpecimen.tsx` |
| `tsconfig.json`, `vitest.config.ts`, `eslint.config.mjs`, `stylelint.config.mjs`, `playwright*.config.ts`, `drizzle.config.ts`, `vercel.json`, `package.json` | the tools themselves, found by name at `apps/web/` |

Expand->contract path (P-07, D-029) when the generator can address a root-level unit: add `contract {entry: next.config.ts, version: 1.0.0}`, run `scripts/generate addresses`, move the five path importers to `@ou/web-build` in their own units' PRs, then drop nothing (no shim exists). Until then the table above is the published surface and any change to those two files' exports is breaking.

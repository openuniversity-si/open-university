# U4 ui-identity audit (read-only)

Brief: migrate unit `ui-identity` (plan v3 §9.2 row U4, v3.1 §3). Base `mod/roadmap-integration` after #598/#648.

| Area | Evidence | Consequence |
|---|---|---|
| Physical form | S1 (P-03): units stay logical (manifest + `@ou/<id>` address + checked boundary). `apps/web/src/ui/identity/**` holds 4 components, 3 CSS modules, 1 test; every merged U4 PR so far moved nothing. | No file moves, no old path, no shim (D-029). |
| Size | 4 production `.tsx` files, about 115 lines; far under `units.size_ceiling`. | Not oversize; no `unit.oversize`. |
| Importers | `rg "@ou/ui-identity"`: `TopNav.tsx` (AccountMenuOverlay), `layout.tsx` (AuthShell), `AccountFixture.tsx` (AccountMenuOverlay, SignInFeedback). `AccountMenu` and `ContinuingWithGoogle` are unit-internal. | Published surface: `AccountMenuOverlay`, `AuthShell`, `SignInFeedback`. |
| Self-import | `AuthShell.tsx` imported its siblings by `@/ui/identity/...`. | Relative imports inside the unit. |
| Contract slot | `contracts/units/unit.v1.json` `contract {entry, version}`; none set for this unit. | Add `contract.ts` as the entry, version 1.0.0. |
| Literals | No `x-literal-sites` entry names a file of this unit; copy comes from `site-domain/reader-copy`, class names are CSS modules. | Allowlist already zero. |
| UI text | The four `.tsx` files hold no visible string (L1 check clean). | They join `l10n.scoped_files` so the gate keeps them at zero. |
| Battery | `scripts/unit-battery ui-identity`: types 2.3 s, unit-tests 0.8 s. | Stays green with the contract step. |
| Generated | `scripts/generate` fails on the known `intents-doc.ts` defect (`docs/operations/known-defects.md`); `codeowners` and `addresses` targets run alone and drift only in `apps/web/tsconfig.json`. | Commit that drift. |

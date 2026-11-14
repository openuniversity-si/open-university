# ui-showcase contract (1.0.0)

The unit is logical (S1, P-03). Entry: `apps/web/src/ui/showcase/contract.ts`; importers keep `@ou/ui-showcase/<folder>/<file>`.

| Module | Exports other units import |
|---|---|
| `CreditsList/CreditsList.tsx` | `CreditsList` |
| `LegalPage/LegalPage.tsx` | `LegalPage`, `LegalEmailCard` |
| `showcase/AreaGrid.tsx` | `AreaGrid` |
| `showcase/course-opening.ts` | `courseOpening`, type `CourseOpeningEdition` |
| `showcase/home-shelves.ts` | `homeShelves`, type `HomeShelf` |
| `showcase/shelf-sentences.ts` | `CREDITS_NOTE`, `countryMeta`, `plural`, `universityHero` |

Every other export is internal. A name is added to the entry before a consumer uses it (expand); a removal waits until no consumer imports it (contract) and goes through P-07 and D-029. No consumer file is edited here.

Literals: none (allowlist zero). UI text: none moved (the one string in `LegalPage.tsx` is blocked by the D-006 visual guard; follow-up). Battery: `scripts/unit-battery ui-showcase`, limit `battery.unit_time_limit`.

# ui-tokens contract (1.0.0)

The unit is logical (S1, P-03). Its surface is what other units import today; no `index.ts` re-export is added (D-029), so the manifest `contract` slot stays empty. Importers keep `@ou/ui-tokens/<file>`.

| Module | Used by other units |
|---|---|
| `layout.ts` | `TOWER_THEME_COLOR` (`app/layout.tsx`, `app/manifest.ts`) |
| `tokens.css`, `shell.css`, `home.css`, `course.css`, `player.css`, `glass.css`, `auth.css`, `progress.css`, `edition.css`, `legal.css`, `universities.css`, `credits.css`, `not-found.css` | the 13 stylesheets `app/globals.css` imports; `tokens.css` is also read by tests of ui-foundation, ui-identity and config-documents |

Every other export (`TOWER_LAYOUT`, `towerPlayerMainWidth`, `towerCourseLecturesWidth`, `towerSilverCtaAngle`, `vocabulary.ts`) is internal to the unit. A removed custom property or export is breaking and goes expand->contract (P-07, D-029): move callers, then remove. No consumer file is edited here.

Literals: the layout measures, gradient constants and parser spelling live in the D-063 catalog `vocabulary.ts`; the baseline entry for `layout.ts` is gone. UI text: none. Battery: `scripts/unit-battery ui-tokens`, limit `battery.unit_time_limit`.

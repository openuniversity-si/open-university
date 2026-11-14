# GX-FIX-merge-phase-test: audit (skeleton)

Defect: `apps/web/src/site/domain/no-github-actions.test.ts` asserts `scripts/merge-phase` contains "local gate".
GX-22 (#722, 0be5b650) reworded merge-phase to read the proof from the PR's event log, so the phrase is gone on the base.

Evidence: base fbc09f28, `scripts/merge-phase` lines 6, 105, 124 contain "event log"; no "local gate".
Fix: pin "event log" instead, keep `.not.toMatch(/check-runs/)`, keep the test title (gate-suite-baseline.json lists it).

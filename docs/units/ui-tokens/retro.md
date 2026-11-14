# ui-tokens retro (U4)

1. **Brief.** It asked to move the unit into `units/ui-tokens/`; S1 (P-03) keeps units logical, `app/globals.css` imports the sheets by path and no `.css` may be edited, so nothing moved and no old path was deleted (D-029).
2. **Result.** Audit, contract (`TOWER_THEME_COLOR` and the 13 sheets), the manifest `battery.command`, and `layout.ts` literals moved to the D-063 catalog `vocabulary.ts` (absolute baseline 1368 -> 1338). The CSS sheets keep their baseline entries (no .css edits). No UI text.
3. **Gate.** Run 1 red on engine baseline drift on the base (fixed by #647). With #647 merged, structure check passes; the remaining red was script tests only: generate.test.sh (KF2), gate-heavy-db (KF3), then claude-session and test-db, where `drop database ... with (force)` stalled in Postgres `CheckpointStart` past the 30 s limit on this container. Unit, integration, lint, typecheck, builds, e2e and performance passed. Battery 2.5 s.
4. **Lessons.** Nested catalog keys each need a doc comment; a catalog holds no function, so error text is split into start and end keys.

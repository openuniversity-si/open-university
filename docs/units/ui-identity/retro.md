# U4 ui-identity retro

1. **Brief.** It asked to move files into `units/ui-identity/`; S1/P-03 keeps units logical and `src/ui/identity` is imported through `@ou/ui-identity/*`, so nothing moved. The branch name differed from the designated one; the designated branch was used.
2. **Audit and plan.** P-05 held: no literal or visible string in the unit. The three exported names came from the import graph, as planned.
3. **Execution.** Two own mistakes: the first contract test scanned only the unit's folder (found no consumers) and the battery's contract step reads git-tracked files, so a new entry must be `git add`ed first. `scripts/generate` with no target stops on the known `intents-doc.ts` defect; single targets work.
4. **Gate.** See the PR comment.
5. **Lessons.** (a) `unit-battery` could say "untracked" instead of "not a file of the unit" (owner: units/U3a). (b) The contract-test template should take the source root from one place (owner: units/U1).

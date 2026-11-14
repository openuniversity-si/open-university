# U4 tooling-catalog-cli-content: retro

1. **Brief.** #621 shipped the contract and left two DoD items open (the 1073 D-063 literals and this retro); the follow-up brief named exactly those. Missing: it did not say
   where the prose should live. The `text` registry feeds the web app through a generated catalog, so the CLI prose went to documented D-063 catalogs in the scripts
   manifest (English only), recorded in a PR comment. Wrong: the brief's branch name (`mod/u4-...`) differed from the session's designated branch; the designated one was used.
2. **Audit and plan.** P-05 held: the census listed 1073 offenders in the six files (courses 293, lessons 198, reference 193, imports 152, texts 134, editions 103). The plan
   (3 commits: register catalogs, rewire and shrink, retro) did not change. The unit's files are still under `apps/web/scripts/lib/catalog-cli/commands/` (P-03), so the
   catalogs sit beside them and the manifest lists them.
3. **Execution.** A one-off codemod (kept out of the repo) walked each file's census literals and replaced them with a key of a per-file catalog, deduplicated by value and
   role; typed `typeof` checks lost their narrowing, so they became `isString`/`isNumber` guards over `JS_TYPE`, and empty/first/floor use `EXTENT` (so the unit now requires
   `kernel-limits`; the structure check named it). Four type errors remained, fixed by hand. The census for the six files went 1073 to 0 and the scripts exception list lost
   571 entries. Unit battery green; the existing core-unit tests that pin the help text passed unchanged, which is the proof that no text changed. One tool misstep: a
   `pkill -f` pattern matched my own shell and ended the command; the gate was restarted.
4. **Gate.** See the RETRO comment on the PR for the stage table and wall time on this 4 vCPU cloud.
5. **Lessons.** (a) Generated key names carry the role and command, not an editor's judgment of meaning; a human pass over the catalogs would improve them (owner: tooling-lane).
   (b) A literal that guards a type (`typeof x === "string"`) cannot become a catalog value without a guard helper; a shared `isString` in the kernel would avoid a copy per file
   (owner: kernel-lane). (c) A move into `units/` would be a path rewrite only, since the catalogs already sit beside their consumers.

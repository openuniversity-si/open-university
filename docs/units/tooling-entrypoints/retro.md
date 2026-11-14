# U4 tooling-entrypoints: retro

1. **Brief.** It asked to move files into `units/tooling-entrypoints/` and zero the literals; S1 (P-03) keeps units logical, so nothing moved, and the 187 literals were left on the shrink-only census list (see the audit for why). The designated branch name was used.
2. **Execution.** `scripts/generate` as a whole exits 1 here because the on-demand `intents` target cannot resolve a module in this environment (base too); running the committed targets one by one was enough.
3. **Lessons.** The unit battery sits at 9.5 s against a 10 s limit, so a slower runner turns it red (owner: tooling-lane). `scripts/generate` should skip or name an on-demand target that fails to run instead of failing the committed ones (owner: engine-generate).

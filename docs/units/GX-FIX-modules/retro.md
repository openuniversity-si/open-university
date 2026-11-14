# RETRO GX-FIX-modules

1. Brief: clear and right; its pre-scan list (10 suspects) was all false positives, which is why the instruction to decide by running was the useful part.
2. Plan: premise held. Audit method: run all 80 script tests with `apps/web/node_modules` absent. Result: only `generate.test.sh` fails for that reason (plus the already-true tower-media pair and the known env test claude-session).
3. Dead end: moving `apps/web/node_modules` away is not enough, a test in the suite recreated it and the first run was invalid (all green). A regular file placeholder at that path made the second run valid.
4. The suspects mentioning node (`prune-inherited`, `engine-capture`) only run `node --test` on repo-local `.mjs` files, so they need no modules. The guard therefore matches `scripts/generate` only, not generic node tooling (a generic rule would false-flag them).
5. Base moved 21 commits while working; merged (merge commit), no conflicts, new `gate-pin.test.sh` has no node tooling.
6. Gate: see PR comment for runs. A fresh worktree of the base has no `.toolchain`; symlink it from the main checkout (setup.sh not needed).
7. Lesson: a helper that runs a script test with the modules directory hidden would make this audit one command (owner: GX-08 sidecar migration).

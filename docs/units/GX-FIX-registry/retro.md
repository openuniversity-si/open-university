# GX-FIX-registry retro

1. Brief: precise and verified (the reproduction held). The branch name in the launcher (claude/...) differed from the brief's mod/gx-fix-registry; pushed to the latter.
2. Plan held: drop-and-pin in sitecustomize, no config.py change needed; the pin is module state so an import hook re-applies it to the head's own config.
3. Rework: the first guard test tripped the registered-literals scan (host, 60, 7, 1000). Class: any new test literal; fixed by one constant and registry reads (1982885d). No repeat.
4. Gate: one run, pinned to 0bc49fea. Every stage passed (script tests 36.9 s, structure 11.2 s, total 69.8 s) except gate evidence: `forge_events could not record the verdict: gh: exit 403 (auth)`, class env (this container's forge credentials), not this change. No advisory head-tooling run was printed in the output.
5. Lessons: a guard-test template that already uses registry reads would save the literal round (owner: tests/gate). The forge 403 in cloud sessions is GX-ENV's.

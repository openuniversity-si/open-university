# GX-27 RETRO

1. Brief quality: asked to remove a "0 behind" line from `docs/padrao/v1/*`; no such line exists there (audit.md). The wording lives in the launch brief template outside the repo. Owner: brief/padrão owner should move the MERGE LOOP "0 behind" text into a padrão file or drop it from the template.
2. Audit/plan: premise P-47 held. Plan changed once: the padrão edit became a no-op, and a test that pinned the old default (`test_commit_check.py`) had to be adjusted, which the brief anticipated.
3. Execution: base never moved (eaeeb29d). One failure class: tests pinning the old default (two tests, fixed together with a `switch()` helper); a second one, `set_value` refusing a no-op, was my helper's bug, fixed in the same helper. Commits: audit skeleton, audit, plan, flip.
4. Gate: pinned `scripts/gate-dev --pr 725`, head cb9b48e1: PASSED, 71.5 s of 180 s, all 6 stages PASS, no known defects hit. `scripts/run test commit-check`: 20 tests OK.
5. Lessons: a registry default flip should come with a grep for tests asserting the old default (add to the registry-key unit template, owner: config). The generated module needed no change (it lists names and types only).

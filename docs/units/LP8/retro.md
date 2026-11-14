# LP8 retro

1. Brief: clear. One conflict: the brief names branch `mod/lp8`, the launcher assigned `claude/padrao-v3-pass-on-rvfy21`; the launcher branch was used (never push elsewhere).
2. Plan vs actual: estimate sonnet 0.5 h, actual about 15 min. Plan went from 5 commits to 4 (the two rules share the manifest line, so one commit).
3. Execution: `cp *.md` did not copy `padrao.json`, and the first `git add -A docs` committed the v1 rule copies with the plan (harmless, unreferenced); the manifest came as commit 2. Class: bulk copy plus `add -A` mixes steps; stage by path.
4. Collisions: none. Only `docs/padrao/v3/**` and `docs/units/LP8/**`. PD2 (#669) owns v2 and README; v2 not merged at start.
5. Tests: `test_coordinator_launch` and `test_coordinator` pass with v3 present. No structural test reads non-active versions, so v3's manifest is only checked by hand (version equals folder, every file exists).
6. Lesson (owner: coordinator/PD2): a test that validates every `docs/padrao/*/padrao.json` (version equals folder, files exist) would catch a bad new version before activation. CANDIDATE for the planner.
7. v3 is not activated; activation is a planner decision.

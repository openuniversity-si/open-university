# TX26 retro

Brief quality: clear and sized right (S). One gap: the brief says "38 covers-only merges"; on first-parent merges of the base since 24/10 the replay finds 346 merges, 17 touching a covers file, 15 where the covers manifest alone forced the full suite (old reason `selector changed: scripts/tests/covers/...`). The 38 are not reproduced with this definition (the audit's set is probably PRs, not first-parent merges, or counts merges that also touched other selector files). The direction holds.

Premises: P-46 held (`load()` still validates every manifest; `select()` raises on a malformed, missing or stray one). The CRITICAL premise (a manifest edit never skips map validation) held: the map check test is always selected with a manifest, and `load()` raises inside `select()`.

Replay (current mapping applied to historical diffs, 91 script tests in the full suite): median selected tests 91 before, 22 after over the 15 merges; 3 of them stay full (other selector or uncovered paths in the same PR).

Failures and root-cause class:
- Literal census refused `parents[2]` in the new test (class: code, a literal in scripts/**). Fixed with `.parent.parent.parent`; no baseline written.
- First `Bash` call used a lowercase tool name (class: tooling slip, no effect).

Gate runs: see the MERGE-READY comment for the exact head (pinned offline gate-dev).

Lessons:
- A replay's "N merges" depends on the definition; the next brief should name the query (owner: TX program plan author).
- New scripts/** tests: avoid index literals in `parents[...]`; a shared helper for the repo root would remove the class (owner: engine-lane, candidate for a later TX unit).

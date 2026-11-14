# LP7 retro

- Brief: clear. Wrong premise in it: "use the existing forge_events API" for premise.*; those four schemas are
  subject-exempt, the port refuses them (no repo/pr). Fixed with a thin ForgePort in premises.py; CANDIDATE: GX-37 ships
  premise.*.v2 with a subject, then ForgePort goes.
- Brief also forbade manifest edits, but importing forge_events made structure-check demand `engine-events` in
  engine-premises `requires` (one line, no cycle). Lesson: a brief that adds an import must allow the matching requires line.
- Estimate 1.5 h; actual about 40 min of work, one writer, no sub-agents (3 small files; they would have cost more).
- Mistake: `git add -A` in commit 1 swept the premises edit into the docs commit, so plan item 2 has no commit of its own.
  Lesson: stage by path when docs and code are in flight together.
- lessons.apply already had audit + lesson.applied + brief hook; LP7 added apply_lesson (decision-keyed, idempotent) and
  lessons_brief.brief_lines. No new registry key: dry run is the `--no-emit` flag, adapter/repo come from forge-events.*.
- Collisions: none. Coverage sidecars (covers/premises.json, lessons.json) not added: GX-08 not on the base.

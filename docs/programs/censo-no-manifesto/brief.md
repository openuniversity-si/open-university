# Program censo-no-manifesto: brief

## Complaint
Units edit a file in the code that is not theirs. The literal census (D-063) lives in 31 per-area files under
`scripts/lib/literal-catalogs/` and `scripts/lib/absolute-literals-baseline/`. All of them belong to `engine-structure`,
yet 69 of the 107 units write into them. N writers of one file make N(N-1)/2 pairs that can collide, so at 1,000 PRs a
day the file becomes the bottleneck (Daniel, 2026-10-28 17:17, twice).

## Symptom
Of the 21 open non-draft PRs on 2026-10-28, 19 touch a shared file. 16 touch a per-area census file, 7 of them
`scripts.json` in both lists, and 12 touch `CODEOWNERS`.

## Evidence
`docs/units/CENSO-NO-MANIFESTO/plan.md` gives each number with the command that printed it: 536 entries, every one
resolving to exactly one unit, none held in a file its unit owns, and 218 colliding pairs inside the area files.

## Measurable goal
The program gate measures merge throughput (`prs_merged_per_day`, the parent goal of `reach-1000-prs-per-day`). This
program removes one of its collision sources. Its own done signal is structural: no committed per-area census file,
every entry in its unit's `units/<id>/census.jsonl`, and `scripts/census check` green. Units CN3 and CN4 check this.

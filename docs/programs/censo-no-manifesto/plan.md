# Program censo-no-manifesto: plan

The PR graph is data (contracts/programs/program.v1.json). Status is never written here: `scripts/program status
censo-no-manifesto` folds it from events.

Order: the engine side ships the record, writer, check and derived view (CN1). The tooling side then reads the records
(CN2). After that the entries move, one commit per area, with `scripts/census migrate` (CN3). One release later, both
sides drop the old form (CN4E, CN4T). Every unit follows the usual rules: one PR from and to `mod/roadmap-integration`,
3–8 commits with `Plan: N` trailers, `Fit-Review: not reviewed (Daniel 2026-10-25: no review step)`, a retro at
`docs/units/<id>/retro.md`, and the train merges it, never its own session.

```json program.v1
{
  "contract": "program.v1",
  "program": "censo-no-manifesto",
  "complaint": {
    "symptom": "19 of 21 open PRs touch a shared file; 16 a per-area census file, 12 CODEOWNERS",
    "evidence": "docs/units/CENSO-NO-MANIFESTO/plan.md (each number beside its command)",
    "goal": {"metric": "prs_merged_per_day", "comparator": "gte", "target": 1000, "unit": "prs/day"}
  },
  "units": [
    {"id": "CN1", "title": "Record, writer, check, derived view, regenerate merge driver (engine lane)", "depends_on": [], "owner": "engine-lane", "model": "opus", "wave": 1, "pr": 776,
     "done": ["units/<id>/census.jsonl shaped by contracts/units/census.v1.json, sealed by audit_chain, checked by scripts/census check inside structure-check",
              "scripts/census add|remove|sync|migrate|list|show|check; baseline counts read from the absolute scan",
              "scripts/generate census renders the per-area view, committed: false",
              "structure-check and the architecture checker read through scripts/lib/census.py, merging the per-area files until migrated",
              "CODEOWNERS and apps/web/tsconfig.paths.json merge through the regenerate driver (.gitattributes, scripts/cloud/setup.sh)"],
     "area": ["scripts/lib/census.py", "scripts/census", "scripts/lib/generate_census.py", "scripts/lib/merge_regenerate.py", "scripts/lib/structure.py", "scripts/lib/architecture/tree.mjs"]},
    {"id": "CN2", "title": "The TypeScript census readers read the unit records (tooling lane)", "depends_on": ["CN1"], "owner": "tooling-lane", "model": "sonnet", "wave": 2,
     "done": ["readCatalogManifest and readExceptions return the fold of every units/<id>/census.jsonl merged with the per-area files still present (the same view as scripts/lib/census.py entries), through one reader module next to census-files.ts",
              "the census constants (units dir, record file name, ops, censuses) are keys of the census-files.ts catalog, so the absolute census of apps/web/scripts does not grow",
              "pnpm literals:census --write refuses and names scripts/census sync; --list stays (scripts/census reads it)",
              "absolute-literals.test.ts and literal-catalogs.test.ts green on a tree where a catalog and a baseline file live only in a unit record (fixture)"],
     "area": ["apps/web/scripts/lib/census-files.ts", "apps/web/scripts/lib/literal-catalogs.ts", "apps/web/scripts/lib/absolute-literals.ts", "apps/web/scripts/literals-census.ts"]},
    {"id": "CN3", "title": "Migrate the census into the unit records, one commit per area", "depends_on": ["CN2"], "owner": "engine-lane", "model": "sonnet", "wave": 3,
     "done": ["one commit per census area (18): scripts/census migrate <area> --why 'CENSO-NO-MANIFESTO migration', with nothing else in the commit",
              "scripts/census list prints 536 entries before and after, and scripts/census check is green",
              "no *.json is left directly under scripts/lib/literal-catalogs/ or scripts/lib/absolute-literals-baseline/ (the engine/ subfolder is TX22's and stays); both are in .gitignore",
              "engine-structure drops the two per-area folders from paths and shared; the absolute census test and structure-check are green"],
     "area": ["units/*/census.jsonl", "scripts/lib/literal-catalogs", "scripts/lib/absolute-literals-baseline", "units/engine-structure/unit.json", ".gitignore"]},
    {"id": "CN4E", "title": "Drop the old per-area form from the engine readers (one release after CN3)", "depends_on": ["CN3"], "owner": "engine-lane", "model": "sonnet", "wave": 4,
     "done": ["scripts/lib/census.py reads only the unit records, and a committed per-area file is refused outright",
              "census.catalog_legacy_dir and census.baseline_legacy_dir keep only their role as the derived view's paths (expand then contract, D-068 (3))"],
     "area": ["scripts/lib/census.py", "config/registry/census.json"]},
    {"id": "CN4T", "title": "Drop the old per-area form from the TypeScript readers (one release after CN3)", "depends_on": ["CN3"], "owner": "tooling-lane", "model": "sonnet", "wave": 4,
     "done": ["the TypeScript readers read only the unit records", "pnpm literals:census --write is removed"],
     "area": ["apps/web/scripts/lib/census-files.ts", "apps/web/scripts/lib/literal-catalogs.ts", "apps/web/scripts/lib/absolute-literals.ts", "apps/web/scripts/literals-census.ts"]}
  ]
}
```

## Open PRs that touch a per-area file

At its next base merge after CN3, each of these PRs takes the base side of the per-area files (they are deleted). It
then replays its own entries: `scripts/census add <path> --catalog …` for a catalog, and `scripts/census sync --unit
<unit>` for the baseline. `scripts/census check` names any entry it left behind.

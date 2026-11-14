# SHARED-NEEDS-NO-OWNER plan

Declaring a path `shared` means several lanes write it legitimately, so it can never be the reason a change waits for
anyone. `lanes()` reads it that way since LANE-OWN; `refusals()` must read it the same way, through the same list.

## Commit plan
- [ ] 1. Audit: `docs/units/SHARED-NEEDS-NO-OWNER/audit.md`. The two `pr.refused` events quoted, the code path with
  file and line, the count of open PRs affected with the command that measured it, and the rule the fix applies.
- [ ] 2. Fix: `scripts/lib/train_ownership.py` gains one helper, `deciding(manifest)` (the `paths` without the `shared`
  globs), which `lanes()` and `refusals()` both call. The `lanes()` docstring says that a shared path never decides the
  lane and never refuses. Naming keeps every path: `owner_of()` is unchanged, and a new `units()` takes over the naming
  that `forge_events.unit_of` used to borrow from `refusals()`, so the `unit` of the events and the queue's weights do
  not move. The LANE-OWN test that pinned the old refusal (`scripts/tests/test_structure.py`) now pins the new rule;
  `scripts/tests/forge_events/test_unit_of.py` pins the naming of a shared path.
- [ ] 3. Tests in `scripts/tests/test_train_role.py`: (a) a change of only another lane's shared path merges, with
  `self.asked == []` and no `pr.refused`; (b) a shared path beside a foreign non-shared path is refused, and the
  refusal names only the non-shared file; (c) the existing tests keep passing.
- [ ] 4. Mutation proof in `docs/units/SHARED-NEEDS-NO-OWNER/mutations.md` and the PR body: the shared filter removed
  from `refusals()` turns (a) red; `deciding()` returning the whole `paths` list turns the lane rule red too. Then the
  suites are green again.
- [ ] 5. This plan, then `retro.md` at the end.
- [ ] 6. Audit: every other rule in `scripts/lib` that waits for an approval, with its file, its line and whether it
  can block. None is fixed here.

## Dependency graph and critical path
- Step 0 → 6 → 1 → 5 (plan) → 2 → 3 → 4 → 5 (retro) → gate on the head.
- 6 runs before 1 for one operational reason: 1 needs GitHub REST, which the session's limiter blocked until
  21:00:41 UTC; 6 needs no network.
- Real edges: 2 → 3 (the tests prove the fix), 2 + 3 → 4 (a mutation needs both), 4 → 5 (the retro records the
  mutations). 1 and 6 change only `audit.md`, so they collide with each other and with nothing else.
- Critical path: 2 (15 min) → 3 (10 min) → 4 (10 min) → 5 retro (10 min) → gate-dev (about 15 min) ≈ 60 min.

## Premises
- The train reads the manifests at the integration tip (`train.start_batch` uses `workspace.tip`), so the fix judges
  every queued PR at the train's first run after the merge. Radius: low.
- A shared glob is also one of the unit's `paths` (`units.py` validates `shared` ⊆ `paths`), so the naming still sees
  it. Radius: low.
- `refusals()` has two callers: `train.owned()` and `forge_events.unit_of`. The second moves to `units()` in the same
  commit. Radius: low.
None is CRITICAL (no money, production or source of truth).

## Tests per commit
- 2: `scripts/tests/test_structure.py`, `scripts/tests/forge_events/test_unit_of.py`, and every suite that reaches
  `train_ownership`, `unit_of` or `pr_ready` (14 files, listed in the retro).
- 3: `scripts/tests/test_train_role.py`.
- 4: the two mutated runs and the restored run, quoted in `mutations.md`.
- Final: one `scripts/gate-dev --pr 778` on the head.

## Known base defects expected
None registered for these files (`rg` over `config/registry/defects.json` and `docs/operations/known-defects.md`).

## Cheapest useful effort
Action: one helper that both ownership rules read, proven by two train tests, two mutations and one gate-dev run on the head.
Cost: one module, its naming caller and three test files, about 60 minutes and one gate run.
Requirement: Daniel ruled on 27/10 that nothing may depend on him approving a write; the train refuses every PR that touches a shared literal file for exactly that approval.
Cheaper rejected: approving each refused PR by hand (the single identity cannot approve its own pull request, and it recurs with every literal); filtering shared paths inside `refusals()` alone (a second copy of the rule that can drift from `lanes()`, which is how this stop happened).

Premises: none

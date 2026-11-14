# LP4 plan (mirrored in the PR description)

Deadline: opus · 2 h from launch (27/10 15:4x BRT); stop and write lessons at 4 h.

## Commit plan
1. Audit (`docs/units/LP4/audit.md`).
2. Plan (this file).
3. Signatures, affected set and overrun: the pure functions of `scripts/lib/plan_triage.py` (`signature`, `inputs`,
   `affected`, `overrun`) and their tests.
4. Triage and promotion: `triage`, `triage_all`, the candidate payload, and the 27/10 replay (L1, L2, L5, L6) inline in
   the test.
5. CLI: `scripts/plan note | input | triage` through the forge_events port, `--help` text, round trip on a temp store,
   payloads validated against the plan.* contracts.
6. RETRO (`docs/units/LP4/retro.md`).

## Dependency graph and owned files
`1 → 2 → 3 → 4 → 5 → 6`. 3-5 all live in one module and one test file, so they run in sequence in this session
(sub-agents would share the two files: a collision edge, not removable without splitting the module LP2 fixed).
Critical path ≈ 10 + 5 + 25 + 25 + 25 + gate 10 + 10 = 110 min.

| Commit | Files owned |
|---|---|
| 1, 2, 6 | `docs/units/LP4/**` |
| 3, 4, 5 | `scripts/lib/plan_triage.py`, `scripts/tests/test_plan_triage.py`; 5 also `scripts/plan` |

## Premises
Premises: P-51, P-52 (D-071). Working premises:
- **CRITICAL**: none. No money, production or source of truth: notes and candidates go through the existing port.
- (medium) The folded plan exposes a unit's estimate as `estimate` (minutes); until LP3 folds `set_estimate`, overrun
  is false for a unit without one. Blast radius: the overrun input only.
- (low) A failure signature is `gate_failures`' normalized first error with dotted registry names collapsed, without
  the test id, so one env cause hitting several tests is one candidate (design 1.2: "12 sightings → one candidate").

## Tests
Targeted: `python3 -m unittest scripts/tests/test_plan_triage.py`, `scripts/structure-check`, `scripts/program check
live-planning`. One final `scripts/gate-dev --pr <n>` from a clean base-tip checkout.

## Known base defects expected
claude-session, root-identity, config RegistryMemo / flaky config.test.sh, cloud uid-65534 fs-encoding (env; owners
GX-03 / GX-ENV per the brief).

# Live planning — RETRO (LP2)

- **Brief:** clear; one correction arrived mid-unit (tests register through `scripts/tests/covers/<test>.json`, not headers); applied in the runbook. The brief names branch `mod/lp2`, the harness bound `claude/live-planning-lp2-…` (audit L12 again): pushed to `mod/lp2`.
- **Collisions checked first:** no `plan.*` contract and no D-071 on the base or at merge time (base moved by GX-42 only, docs). D-071 kept.
- **Premises:** `scripts/premises propose` gave P-48..P-52; the first run used `decision:D-071` as reason, which computes radius high (blocks unless confirmed). Redone with `plan:live-planning` (medium), as the design says (none CRITICAL). P-48 (LP-P1) confirmed by A Torre's delegation.
- **Contracts:** a plan event is about a program, not a PR, so it carries the subject fields with `pr`, `sha` and `unit` null; no exemption entry in `forge-events` was needed.
- **Mistake:** my first contract tests wrote literals (11, 2, 64) that structure-check's literal census refuses; caught by the local run, fixed in a follow-up commit.
- **Lesson (owner: brief template):** run `scripts/structure-check` before the first push of a unit that adds tests, not after; and say in the brief that a runbook link must exist before the doc that links it (push-guard refused one push).
- **Not done:** stubs have no test of their own (brief); LP3/LP4 add `test_plan_live.py` / `test_plan_triage.py` and their `covers/` sidecars once GX-08 is on the base.

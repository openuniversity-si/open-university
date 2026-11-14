# ADR-33 — Development gates per PR, full verification at end of day

Accepted 2026-10-19, Daniel's decision at 16:27/16:29 BRT. Supersedes ADR-24/28/29's requirement to run the full
battery before every main merge. ADR-32's production hard check and rollback are unchanged.

## Context and decision

Open University currently has one user, Daniel. E1 spent about 60 minutes coding and 45 minutes verifying in two
full batteries. The target is roughly ten small PRs/day. Run fast programming checks with each PR and full
verification once at the end of the day, over everything shipped to main. A nightly failure produces the day's
last cleanup PR. Timing over 90 seconds is a warning, never a failure; warm development aims at 2–3 minutes.

`scripts/gate-dev --pr <n>` runs lint, typecheck, every unit/coverage and integration case, both cached builds,
cheap safety prerequisites and 40 existing Chromium desktop smoke cases. `scripts/gate-noite` runs every stage
and all browser projects/a11y from the old `gate-local --nightly`, plus inventory preservation. It checks fetched
origin/main or an explicit SHA, reports Markdown/JSON stage failures and candidate merged PRs since the last
successful night (first run: 24 hours; optional explicit boundary), and never merges/deploys/rolls back.
Pixels remain report-only. No tests/assertions/retries/timeouts are weakened, and no new CI service is introduced.

**DB is the exception** (amended by [ADR-34](ADR-34-db-gate.md): gate-dev plus `scripts/gate-db` replace the full battery before merge): schema, migrations and production-data writers require the full exact-head battery and
numbered disposable Neon acceptance **before merge**. A database mistake cannot be repaired safely just by another
code PR. One deliberately conservative path policy classifies the actual PR merge-base diff, including renames;
merge-phase refetches/reclassifies and refuses uncertainty rather than trusting a development record's db flag.

Exact-head dev/full records authorize ordinary PRs; only full `nightly=1` plus `neon=pr-<n>` authorizes DB PRs.
Keep `--match-head-commit`, existing PR eligibility, preview sync and Neon cleanup. Full evidence also satisfies
dev acceptance. Legacy gate-local PR/nightly commands remain. ship-verify consumes evidence without rerunning
a gate. The nightly reuses a merged ancestor PR's disposable name, exact-checkout/ancestry guarded, inside the
existing cost/protection envelope, and deletes it afterwards.

Both gates verify actual browser and Vitest inventories: noite equals full, dev is a subset, union equals full,
and all baseline identities and fixed nightly stages survive. At this checkout the baseline is 795 browser,
649 unit-list and 183 integration-list entries (the brief's earlier 792-browser baseline predates E1).
Scripts, locks, configurable environment and neutral state defaults work identically for humans and any coding
agent. AGENTS.md owns the short delivery rules; Claude/Cursor files only point there.

## Trade-off

Mobile, WebKit, accessibility or operational regressions can reach production during the day on this single-user
site; Daniel accepts that risk to spend more time producing code. A missed end-of-day run extends that window,
so an operator must invoke gate-noite and review its report. Candidate PR attribution helps triage but does not
prove causation. Full test coverage is deferred, not removed. Production hard failures still trigger only the
existing ADR-32 guarded response; nightly failures alone never roll back or modify production data.

Implementation and commands: local gate operations.

Note (GX-26, 2026-10-28): the single budget is the `gate.ceiling_s` 180 s ceiling (D-064 (f)), a warning only, never a failure. It supersedes the 90 s figure above; the text above is kept as history.

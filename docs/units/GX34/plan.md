# GX-34 plan (mirrored in the PR description)

Decision: D-070. Premises: P-27 thousand a day is the start (high), P-14 combined-head failure rate (medium, swept
1–10 %), P-15 tier-2 cloud duration (medium, swept 240–600 s), P-23 unit daily capacity (low, lane-growth scenario).
No CRITICAL premise: the unit is docs only and touches no money, production or source of truth.

## Commits (one writer per file)

1. `docs/units/GX34/audit.md` (Plan: 1)
2. `docs/units/GX34/plan.md` (Plan: 2)
3. `docs/units/GX34/simulation.md` (Plan: 3): the discrete-event simulator, in full, as a fenced block (the
   repository runs literal and structure scans on `.py` files; a block in a Markdown file keeps the unit docs-only and
   still reproducible), its input (the 71 merges with lanes and files, extracted by a script in the same file) and the
   raw output.
4. `docs/programs/gate-excellence/design-sharded-tier2.md` part 1 (Plan: 4): the train today, the constraints from
   the audit, design L (lane-partitioned executors), design S (speculative batches on predicted tips), adaptive batch
   size, and how each meets D-065 (4)/(5), GA-P02 and the tree proof.
5. The same doc, part 2 (Plan: 5): simulation results (makespan, wait, executor-minutes, saturation PRs/h at
   1k/10k/day), the recommended design, the named build units, the C3 re-plan inputs.
6. `docs/units/GX34/retro.md` (Plan: 6).

Graph: 1 → 2 → 3 → 4 → 5 → 6. The only real edge is 3 → 5 (numbers); 4 → 5 is a file collision (one file), kept
serial because both are short and a split file would be a second deliverable. No sub-agent fan-out: one doc,
one writer; the only parallel step is the base-tip gate run in the background while the retro is written.

Critical path (estimated minutes): 1 (done) → 2 (5) → 3 (35) → 4 (20) → 5 (25) → gate (≈ 15, background) → 6 (15)
≈ 2 h, inside the 1.9 h × 2 stop line.

## Tests

None (docs). Per push: `scripts/commit-check --local` (pre-push hook) and `scripts/structure-check --pr-body`.
Final: one `scripts/gate-dev --pr 704` from a clean checkout of the base tip (verdict of record, D-A3) and one from
this checkout (report-only).

## Known base defects

`claude-session.test.sh`, `root-identity.test.sh`, `config.test.sh` (RegistryMemo), uid-65534 fs-encoding crash: GX-ENV.

## Simulation model (what commit 3 builds)

- Input: the 71 first-parent merges of 27/10 BRT; ready time = last non-merge commit of the PR + a tier-1 gate wall;
  partition key = lanes of today's manifests ∪ shared files no manifest claims (generated aggregates counted or not,
  two variants).
- Tier 2: duration D (240 / 420 / 600 s), a batch is red iff it holds a bad PR; bad PRs drawn i.i.d. with f
  (1 / 3 / 10 %) or from a two-state red-streak chain (calm 1 %, streak 35 %, mean streak 8 PRs, ≈ 5 % average).
  An ejected PR comes back fixed after 30 min.
- Designs: B0 today (one lock, batch 8, serial bisection, nothing merged on red), B1 = GX-30 (proven prefix merged),
  L(k) lane-partitioned with k executors, S(k) speculative depth k with parallel bisection, and fixed vs adaptive
  (halve on red, double on green) batch size.
- Outputs: makespan of the day, mean / p90 wait (ready → merged), tier-2 runs (executor-minutes), saturation
  throughput (PRs/h with an unbounded backlog), at the 27/10 lane mix and with lanes scaled with volume (P-23).

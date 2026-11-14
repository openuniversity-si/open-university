# GATE-GC-CHEIO — the report folders get a bound of their own

## Why this unit exists

`gate_gc.collect_reports` keeps the newest `gate-gc.reports_keep` runs per (sha, mode) and never bounds the folder:
every push adds a sha directory. On 28/10 the box ran out of inodes three times (99%, `df -i`) with 40 GB free, and
each stop looked like a transport fault. Audit: [audit.md](audit.md).

## Steps

- [ ] 1. `docs/units/GATE-GC-CHEIO/audit.md` and this plan: the `df -i` line, the inode table with its commands, the code path (`gate_gc.py:46-59`), D-070 and D-069 item 4.
- [ ] 2. `scripts/lib/gate_gc.py`: a global collection measured on the folder, beside the per-(sha, mode) one; registry keys `gate-gc.reports_shas_keep` and `gate-gc.report_only_shas_keep`; tests (a) 100 shas, keep 10 → the newest 10 stay, (b) the per-(sha, mode) bound still holds and composes.
- [ ] 3. Liveness: never remove the sha a live gate is writing, a sha named by a held `gate.lock`, or a sha a live process holds open, nor any sha directory newer than the newest live report; the exit hook passes its own sha, lock and folder; test (c).
- [ ] 4. Readers: the audit answers how long an old run stays diagnosable and what reads `reports/*/*/`; the keys are set from that need; `gate-dev --why` names a run the bound removed instead of calling it unfinished.
- [ ] 5. Evidence and retro: the mutation proof (global collection off → test (a) fails alone), the other unbounded folders measured with `du -s --inodes` (top 10), `retro.md`.

## Cheapest useful effort
Action: the folder-wide collection in the gate's existing exit hook, proven by hermetic tests over temp dirs.
Cost: one session, two gate-dev runs.
Requirement: Daniel needs the train to stop failing on a full inode table that looks like a transport fault.
Cheaper rejected: a cron that deletes old shas on the box — outside the gate, unproven, and the next box repeats it.

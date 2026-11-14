# FLUXO-AMPLO — research

Stage 2 (D-077). Looks outward from the intake's real problem: measure a flow's throughput in integrated commits and keep
the count honest without time windows. References are cited from the literature as I know it; no number below is
reused as a measurement of A Torre (those are in the intake and the audit).

## Quem já resolveu
- **DORA / Accelerate** (Forsgren, Humble, Kim, 2018; the DORA reports). Four keys: deployment frequency, lead time for
  changes, change-fail rate, time to restore. Throughput and stability are measured together because teams that
  raise one by sacrificing the other do not stay elite. Lesson: a throughput number is never reported alone.
- **Flow metrics** (Kersten, *Project to Product*, Flow Framework; Vacanti, *Actionable Agile Metrics*). Flow velocity
  (items done per period), flow time, flow load (WIP), flow efficiency (active time ÷ flow time). Little's law
  (L = λW, Little 1961) ties them: with WIP held, shorter flow time is the only way to higher throughput. Lesson: find
  the stage where work waits (the constraint), as in the Theory of Constraints (Goldratt, *The Goal*).
- **Goodhart's law and Campbell's law** (Goodhart 1975; Campbell 1979; Strathern's wording, "when a measure becomes a
  target it ceases to be a good measure"; Manheim and Garrabrant on its variants). Lesson: a target on commits invites
  splitting; the defence is a *set* of measures that pull against each other, plus a count of a thing that is costly
  to fake. Single-metric targets fail first on the cheapest-to-game dimension.
- **Atomic commits and tangled changes** (Herzig and Zeller, "The impact of tangled code changes", MSR 2013; Hindle,
  German, Holt, "What do large commits tell us?", MSR 2008; Kawrykow and Robillard, "Non-essential changes in version
  histories", ICSE 2011; Google's engineering practices on small CLs; Git's own guidance, "make commits of logical
  units"). Findings I rely on: tangled commits (several concerns in one) are common and distort analyses; the
  opposite error, over-split commits, exists too (formatting-only and rename-only commits are "non-essential").
  Lesson: cohesion is checkable from the diff and from co-change history, not from size alone.
- **Software-size and activity metrics' abuse** (lines of code, commit counts as productivity: widely criticised;
  Fowler, "CannotMeasureProductivity"; the SPACE framework, Forsgren et al. 2021). Lesson: count accepted outcomes,
  not activity, and add satisfaction/quality dimensions.
- **Mutation and revert-based validity**: a commit that is later reverted, or whose lines are rewritten soon after
  inside the same envelope, was not a unit of finished work (SZZ-style bug-introducing analysis, Śliwerski, Zimmermann,
  Zeller 2005, uses the same link in reverse).

## Estado da arte
Elite flow measurement pairs a throughput measure with stability and rework measures (DORA), watches WIP and flow
time to locate the constraint (flow metrics, TOC), and treats any single target as gameable (Goodhart). For commit
quality the literature offers three checkable properties: the change is *self-contained* (builds and passes on its
own, so it is bisectable), *single-concern* (no tangling; co-change coupling and one intent), and *non-trivial and
surviving* (not a whitespace/rename-only change; not rewritten by the next changes). Durability is classically
measured as survival time of lines or churn within a window; nothing in the literature requires wall time — churn can be
measured in **operations** (the next N integrations), which is what A Torre's rule asks for.

## Encaixe em nós
- **Copy**: pair the main metric with stability/rework measures (DORA); report WIP and the constraint (flow); Little's
  law as the diagnostic frame for the bottleneck.
- **Adapt**: durability by survival in *operations*: a counted commit's added lines are judged against the next
  K integrated commits on the base (K a registry value), never against days. Cohesion by plan linkage (one `Plan: N`
  item, D-025 in AGENTS.md) and by one-area diffs (`scripts/lib/gate-areas.json`) instead of a size threshold. Tangled
  vs over-split is checked both ways: more than one area in a commit, and consecutive commits of one PR that rewrite
  each other's hunks (co-change) merge into one count.
- **Does not fit**: calendar windows (7-day survival, DORA's per-day deployment frequency taken literally), human
  satisfaction surveys (one actor today), PR-level counting (a PR is an envelope, Daniel's rule).

## Escada de ambição
1. **Minimum useful now**: a read-only command over git history that prints the baseline (counted and raw integrated
   commits per day) and each guard ratio, so every claim can be rerun.
2. **Next**: guards computed per commit at admission (a merge-train check), so a split or trivial commit is flagged
   before it counts, and weighted by outcome pairing (lead time per plan item, rework per 100 commits).
3. **State of the art**: counted commits become an event stream (valid, cohesive, relevant verdicts as events) with the
   guards as SLOs, and phases advance only while all guards hold — Goodhart-resistant by construction, since the target
   is the set, not the count.

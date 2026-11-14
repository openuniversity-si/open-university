# FLUXO-AMPLO — pesquisa

The full note is [research.md](../../units/FLUXO-AMPLO/research.md); this is the program's summary.

## Quem faz melhor
- DORA / Accelerate (Forsgren, Humble, Kim): throughput is reported with change-fail rate and restore time; elite
  teams deploy many small changes without paying for it in stability.
- Flow metrics and Little's law (Kersten; Vacanti; Little 1961): throughput = WIP / flow time; find the stage where work
  waits and limit WIP.
- Goodhart and Campbell: a target on one measure is gamed first on its cheapest dimension; a set of opposing measures
  is the defence.
- Atomic-commit research (Herzig and Zeller; Hindle et al.; Kawrykow and Robillard): tangled and non-essential
  commits are measurable from the diff; so are over-split ones.
- Trunk-based development at scale (Google's monorepo, Facebook's Sapling, the merge queues of GitHub and Bors-style
  trains): many short-lived lanes into one queue, each change small and whole, admission automated.

## Encaixe em nós
- **Copy**: pair the main metric with guards; Little's law as the frame for the diagnosis; small whole commits into a
  queue.
- **Adapt**: durability as survival across the next integrations, not days (operations only); lane partition by
  `gate-areas.json` areas instead of CODEOWNERS teams.
- **Does not fit**: time-window durability, per-day literal DORA frequency, human satisfaction surveys (one actor).

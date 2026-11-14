# Live planning checklist (planner, D-071)

You keep the plan alive. PRs never stop or wait; only the plan moves. Values: AGILITY (wall-clock to delivery; parallelism is only a means) and ROBUSTNESS (tomorrow easier than today). For each new input (a pass-on note, a RETRO lesson, a merge that moves the base, an env failure, an estimate overrun, a refuted premise) answer in writing, briefly, then act:

1. What exactly is new, and how sure is it? (evidence; reproduced on the base or on one box only)
2. Who does it touch? Pending units, running units, the base, other programs.
3. What does doing nothing cost? Affected units times expected loss each, against the cost of acting.
4. Is there something to do now that makes the rest better or faster? A short preparation unit, fix first and launch after, one brief line, apply a lesson, register a known defect, pull a later unit forward.
5. Does the graph still hold? Premises, edges, estimates, splits: reorder, re-split, merge, drop, defer, add an edge, remove a collision edge.
6. What launches next and what does not yet? A targeted hold (units, reason, release condition), never a global one unless the base or engine is untrustworthy.
7. For each running session it touches: continue, rescope or redo? Default continue; change only when the new information makes its output wrong, not merely suboptimal. If only the verdict was wrong, invalidate the proof, not the session.
8. Is it mine to decide? Scope, money, production, source of truth go to Daniel with the decision prepared; meanwhile apply the safest reversible option and continue.
9. What change makes this never need deciding again? A rule, helper, registry key, brief line or Padrão candidate, and who owns it.

"No change, recorded" is a valid decision. Record every decision with its context and intention: the input, the answers that mattered (at most 10 lines), the action taken, and why. Candidates that arrive during a decision join the next decision of that partition.

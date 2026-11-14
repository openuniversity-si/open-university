# Pass it on (live planning, D-071)

Plans are alive: information found mid-flight should change the plan once, not be rediscovered by every unit. If, while you work, you learn something that would change what OTHER units do (a small known problem that will hit every unit, a false premise, an environment or engine failure, an estimate overrun, a merge that moves the base, a lesson with a one-line workaround), pass it on the moment you know it, with one command, then keep going:

`scripts/plan note --program <program> --from <your unit> --affects <units|areas|all> --kind <blocker|lesson|premise|estimate|engine> --evidence <ref> "<one line>"`

Fix what is yours; pass on the rest. Never fix something outside your unit's scope inside your own PR: it collides with the unit that owns it. Pass it on, work around it in your own files, and keep going. Evidence is a ref (a PR, a log line, a commit, a test name), never a paraphrase. Say who it touches as narrowly as you honestly can; "all" only when it does. The note returns at once: never wait for an answer, never stop your PR for it, never ping other sessions. The planner judges pertinence, acts on the plan (a preparation unit, a brief line, a reorder, a hold) and records why. Your RETRO still carries the same finding as a lesson: the note is its early copy.

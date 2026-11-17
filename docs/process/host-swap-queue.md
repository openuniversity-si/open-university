# Host swap queue

D-054. Production is frozen ([RELEASES.md](../process/RELEASES.md)). Every production change the code needs and
production does not have is listed here, in the order it runs. Nothing here runs by hand.

Production was Open University's site, which left the repository (D-111). Its queue held Q-01–Q-05 and Q-07–Q-11: the
database migrations from 0033 on, the media and fidelity rewrites to R2, the first release deploy and the retirement of
the old blob and Mux tokens. It is archived with Open University at `567176bb` (D-110,
`git show 567176bb:docs/process/host-swap-queue.md`). Those items run only if Open University comes back, from its
archive and through a release pipeline of its own. The engine has no database migration journal, so
`scripts/structure-check` has no migration to hold against this file.

## Queue

### Q-06. Restrict merges into main on the forge

- not a migration: a repository setting on the selected forge (`forge-events.adapter`, today Origin), made by the
  repository owner (Daniel); agent tokens cannot change it
- why queued: the scripts refuse a non-release merge into `main` (`scripts/lib/release_policy.py`), but a plain
  merge through the forge's own client or web UI does not run them (RELEASES.md, "What enforces it")
- setting: a rule on `main`, where the forge offers one, that allows only a pull request from `mod/roadmap-integration` to merge, with a merge
  commit, and blocks force pushes and deletions
- check: a test PR from any other branch into `main` shows as blocked; the release PR is mergeable

### Q-12. Pause the Open University site (D-105)

- not a migration: the last step of OU-DECOUPLE, taken by Daniel after the archive exists and the removal has merged
- action: the least destructive one that takes the site offline, announced on the PR first. The RDS and R2 data are not
  deleted or modified, and Cloudflare is not changed
- check: the site no longer serves

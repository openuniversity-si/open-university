# Save often (Daniel 21:04, no quota pause)

The session may end at any moment when the quota runs out, so unsaved work is lost work. Commit small and often: each commit is one green step (the change plus its tests pass locally), and you push it right away with `git push origin HEAD:<branch>`. Never hold more than one green step unpushed, never batch several commits into one push at the end, and never keep work only in the working tree. Open the PR right after the first push. Tick the commit plan in the PR body as you push, so a new session can resume from the remote branch and the PR alone.

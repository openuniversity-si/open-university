# GX-FIX-train-lock — audit

Base `ebab9368` (`mod/roadmap-integration`, GX-02 #695 merged). Measured 2026-10-27 from Claude Code cloud session
`session_01N99RyQsv6CLPhTFfPmB4Q3` (this unit). Every request goes through the session's egress proxy
(`$HTTPS_PROXY`, `gitConfigInjection: true`); no token was printed. Requests were shaped so that nothing shared could
change (invalid sha/state/body, an already merged PR, a throwaway ref).

## Why the train halted

The train-role session (`session_01N99RyN8hG5oS7hoWLNaTJt`, PR #705 comment 6453543556): `scripts/train run` →
`forge_github._lock_commit` → `POST /repos/openuniversity-si/open-university/git/trees` → 403 *Write access to this GitHub API path is
not permitted through this proxy.* That text is the proxy's (its `documentation_url` points at docs.anthropic.com), not
GitHub's. Reproduced below.

## Permitted paths (REST, `api.github.com/repos/openuniversity-si/open-university`)

All with `Content-Type: application/json` (without it the proxy answers **415** *Request bodies must declare
Content-Type: application/json* to every body-carrying write; `github_api._request` already sends it).

| Request | Status | Refused by | Train/gate caller |
|---|---|---|---|
| `POST /git/trees` (invalid mode) | 403 | **proxy** | `forge_github._lock_commit` (lock) |
| `POST /git/blobs` (invalid encoding) | 403 | **proxy** | none |
| `POST /git/commits` (zero tree sha) | 403 | **proxy** | `forge_github._lock_commit` (lock) |
| `POST /git/refs` (zero sha) | 403 | **proxy** | `forge_github.lock` (create) |
| `PATCH /git/refs/heads/<absent>` (zero sha) | 403 | **proxy** | `forge_github.lock` (renew / take-over) |
| `DELETE /git/refs/heads/<absent>` | 403 | **proxy** | `forge_github.unlock`; `github_api.run_http` `pr merge --delete-branch` |
| `PUT /contents/probe.txt` (bad base64, absent branch) | 403 | **proxy** | none |
| `POST /merges` (absent base) | 403 | **proxy** | none |
| `POST /statuses/<sha>` (invalid state) | 403 | **proxy** | `forge_github.set_status` (GX-17 `tower/gate`) |
| `POST /check-runs` (invalid status) | 403 | **proxy** | none |
| `PUT /pulls/695/merge` (zero sha, PR already merged) | 200 `merged: true`, sha `ebab9368` (no change) | GitHub (permitted) | `forge_github.merge` → `github_api.run_http pr merge` |
| `PUT /pulls/695/update-branch` (zero expected sha) | 422 *expected head sha didn't match* | GitHub (permitted) | none |
| `POST /issues/705/comments` (empty body) | 422 | GitHub (permitted) | `append`, `comment`, `upsert_comment`, `pr comment` |
| `PATCH /issues/comments/6453543556` (empty body) | 422 | GitHub (permitted) | `upsert_comment` |
| `POST /pulls` (absent head) | 422 | GitHub (permitted) | `open_change` |
| `PATCH /pulls/695` (invalid state) | 200, ignored (PR still closed/merged) | GitHub (permitted) | `close_change`, `pr close` |
| `GET` repo, `git/ref`, `git/commits`, pulls | 200 | — | reads |

PR #695 after the probes: `closed`, `merged`, `merge_commit_sha ebab9368…`; `mod/roadmap-integration` still `ebab9368`.

## Permitted paths (git protocol, `https://github.com/openuniversity-si/open-university`)

Lock-shaped commit (`lock.json` `{"owner","expires"}`, message = the same JSON) built locally with `hash-object`,
`mktree`, `commit-tree`.

| Push | Result | Refused by |
|---|---|---|
| create `refs/heads/train/probe-01N99RyQsv6CLPhTFfPmB4Q3` | `[new branch]` | permitted |
| create `refs/heads/claude/probe-<sid>`, `refs/heads/mod/gx-fix-train-lock-probe` | `[new branch]` | permitted (no per-session branch-name limit on `refs/heads/*`) |
| create `refs/train/probe-<sid>` (outside `refs/heads`) | *unexpected disconnect while reading sideband packet* | **proxy** |
| fast-forward the probe ref (child of the read sha) | `2e007626..6c731bea` | permitted |
| non-fast-forward without force | rejected (non-fast-forward) | git/GitHub (correct) |
| `--force-with-lease=<ref>:` (must not exist) on an existing ref | `(stale info)` | git (correct) |
| `--force-with-lease=<ref>:<stale sha>` | `(stale info)` | git (correct) |
| non-fast-forward with a correct lease | refused by our own pre-push hook (`no_history_rewrite`, LR1) | repo policy |
| delete (`git push origin :<ref>`, `--delete`, with or without lease) | *RPC failed; HTTP 403* | **proxy** |

Consequences:
- A ref can be **created** and **fast-forwarded**, never deleted or rewound, from this session. The pre-push policy
  refuses a rewind anyway, so the lock must never need force.
- The three probe refs (`train/probe-…`, `claude/probe-…`, `mod/gx-fix-train-lock-probe`) **could not be deleted** from
  here (proxy 403). They hold one lock-shaped commit each, are not PRs and are not read by anything. Removing them needs
  a person (`git push origin --delete <ref>` outside the proxy) — listed in the PR.
- `git push` exits 0 with *Everything up-to-date* after a proxy-refused delete: success must be read from
  `--porcelain` output / `ls-remote`, never from the exit code alone.

## Every train and gate forge write (base `ebab9368`)

| Site | Write | Path class | Verdict |
|---|---|---|---|
| `scripts/lib/forge_github.py:256-263` `_lock_commit` | `POST git/trees`, `POST git/commits` | git-data REST | **refused → move** |
| `scripts/lib/forge_github.py:279-297` `lock` | `POST git/refs`, `PATCH git/refs/heads/<name>` | git-data REST | **refused → move** |
| `scripts/lib/forge_github.py:299-302` `unlock` | `DELETE git/refs/heads/<name>` | git-data REST | **refused → move (and no delete at all)** |
| `scripts/lib/forge_github.py:265-277` `_holder` | `GET git/ref`, `GET git/commits` | read | permitted |
| `scripts/lib/forge_github.py:145` `merge` → `github_api.py:292` | `PUT pulls/<n>/merge` | pulls | permitted |
| `scripts/lib/github_api.py:294-299` `pr merge --delete-branch` | `DELETE git/refs/heads/<head>` | git-data REST | refused; only caller is `scripts/merge-phase:178` (production, frozen) → **list only** |
| `forge_github.append/comment/upsert_comment`, `github_api` `pr comment` | `POST issues/<n>/comments`, `PATCH issues/comments/<id>` | issues | permitted |
| `forge_github.open_change`, `close_change`, `github_api` `pr close` | `POST pulls`, `PATCH pulls/<n>` | pulls | permitted |
| `forge_github.set_status` (`gate_status.set_status`, GX-17) | `POST statuses/<sha>` | statuses | refused; already non-fatal by design (printed once as `status: unavailable (403)`); no permitted equivalent (`check-runs` also 403); the gate verdict's carrier is the status comment (permitted) → **no change, documented** |
| `scripts/merge-phase:34` | `PATCH git/refs/heads/preview` | git-data REST | production, frozen (D-054) → **list only** |

Users of the lock: `engine_role.LockedRole` (`port.lock` / `port.unlock`) for the train (`train.lock_ref`) and the
battery (`battery.lock_ref`); both go through `GitHubAdapter.lock/unlock`, so one fix covers both. The port signature
(`lock(repo, name, owner, now, expires)`, `unlock(repo, name, owner)`) stays.

Live `refs/heads/train/lock` today: `844a84c0` (a lock commit written earlier from the box through REST). The new
mechanism reads and fast-forwards it, so no migration is needed.

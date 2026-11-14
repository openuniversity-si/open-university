# SHARED-NEEDS-NO-OWNER audit

Base: `mod/roadmap-integration` @ 1de1fc2b. Branch: `claude/shared-paths-ownership-refusals-ubmrj4` (the session's
assigned branch; the brief names `mod/shared-needs-no-owner`, and the assignment wins as in LANE-OWN retro §1).

## The stop

The train's run at 17:26 on 28/10 refused both PRs that had just passed the gate (quoted from the brief):

```
pr.refused #632 reason=ownership units=['engine-structure']
  files=['scripts/lib/absolute-literals-baseline/scripts.json','scripts/lib/literal-catalogs/scripts.json']
pr.refused #663 reason=ownership units=['engine-structure']
  files=['scripts/lib/absolute-literals-baseline/ui.json','scripts/lib/literal-catalogs/ui.json']
```

Every file named is under a glob that `units/engine-structure/unit.json:29-32` declares `shared`.

## The code path

Line numbers are those of the base, 1de1fc2b.

| Step | Where | What it does |
|---|---|---|
| 1 | `scripts/lib/train.py:187` | `build()` keeps only the entries `owned()` accepts. |
| 2 | `scripts/lib/train.py:170-180` | `owned()` calls `refusals(base, changed_files, entry.lane_id, approvals)` and, on any refusal, emits `pr.refused` with `reason='ownership'`, the units and the files. |
| 3 | `scripts/lib/train_ownership.py:61` | `refusals()` matches each changed file against the manifest's whole `paths` list, `shared` globs included. |
| 4 | `scripts/lib/train_ownership.py:62` | The unit counts as foreign when its lane is not the PR's `lane_id`. |
| 5 | `scripts/lib/train_ownership.py:66-67` | It asks for approvals once and keeps every foreign unit whose `owner` is not among the approvers. |
| 6 | `scripts/lib/forge_github.py:180-190` | The approvers are the reviewer logins whose latest review is `APPROVED`. |

`lanes()` (`scripts/lib/train_ownership.py:35-36`) already removes `manifest['shared']` from the globs that decide a
lane. Its docstring (lines 30-31) states the disagreement: "it stays owned (refusals() still names its owner)".

## Why the approval never arrives

- `refusals()` compares the manifest `owner` with the approvers (`scripts/lib/train_ownership.py:67`). The owner of
  `engine-structure` is `engine-lane` (`units/engine-structure/unit.json:5`), a lane id; the approvers are GitHub logins
  (`scripts/lib/forge_github.py:186-190`). No login is a lane id, so no review can match.
- Mapped to people, the answer is the same. `generate.codeowners_identities` gives each of the 18 lanes one identity,
  `@the-owner`, and that identity opens every PR (the `authors` line of the measurement below). GitHub does not let the
  author of a pull request approve it.
- Daniel ruled on 27/10 that nothing may depend on him answering a permission prompt or approving a write.

A refusal that only an approval can lift, where the approval cannot exist, does not gate the change. It stops it for
good: the PR leaves the queue with `pr.refused`, and the same refusal comes back with its next `pr.ready`.

## Open PRs affected

Measured at 21:01 UTC on 28/10, with this checkout's code before the fix and the manifests of the integration tip
1de1fc2b. Command, from the checkout root:

```
OU_CONFIG_STORE=file python3 measure.py 1de1fc2bef6e4d70e9a604ed4cd0b223abb5daac 900
```

`measure.py` (below) lists every open PR and its files over the repository's own REST client (`github_api`). It then
judges each PR with `train_ownership` at the tip: `lane_of()` (the lane the gate would name) and `refusals()` with
nobody approving (`approvals=list`), because no approval can arrive. `OU_CONFIG_STORE=file` reads registry values
without the shared store. The session's limiter blocked REST until 21:00:41 (see the PR's first STATUS), and the last
argument lets the client wait that block out instead of failing.

Result: `{'open': 50, 'non-draft': 22, 'touch shared': 17, 'refused': 17, 'refused for a shared file': 17}`. Every
author is `the-owner`. The shared globs at the tip are engine-structure's two literal globs and web-build's
`apps/web/tsconfig.json` and `apps/web/eslint.config.mjs`.

- **17 of the 22 open non-draft PRs touch a shared path, and the train refuses all 17 for a shared file.** (The brief
  counted 19 of 21 at 17:26; the open set has changed since.)
- **9 of them are refused for that alone:** their lane is decidable and `engine-structure` is the only refused unit:
  #620 (factory-lane), #622 #625 #626 #632 #633 (tooling-lane), #644 (catalog-lane), #659 #663 (ui-lane). This is the
  set the fix unblocks. #632 and #663 are the two refusals of 17:26.
- **8 of them have no lane at the tip** (#592 #596 #618 #635 #641 #645 #649 #662): their non-shared paths span
  several lanes, so they are also refused for other units. That is lane debt. The fix removes only the shared files
  from their refusals; the gate's lane rule and the non-shared check still stop them.
- The other 5 non-draft PRs (#610 #615 #643 #772 #774) touch no shared path and are not refused.
- 15 of the 28 drafts also touch a shared path (`grep ' draft, ' | grep -vc ' 0 shared'` over the output).

| PR | lane at the tip | shared files | refused units (nobody approving) |
|---|---|---|---|
| #592 | none | 2 | app-course, engine-structure, web-build |
| #596 | none | 3 | engine-structure, release-server, testing-support, web-build |
| #610 | engine-lane | 0 | none |
| #615 | kernel-lane | 0 | none |
| #618 | none | 2 | engine-structure, tooling-brand, ui-shell |
| #620 | factory-lane | 2 | engine-structure |
| #622 | tooling-lane | 2 | engine-structure |
| #625 | tooling-lane | 2 | engine-structure |
| #626 | tooling-lane | 2 | engine-structure |
| #632 | tooling-lane | 2 | engine-structure |
| #633 | tooling-lane | 2 | engine-structure |
| #635 | none | 2 | engine-structure, progress, release-domain, tooling-docs |
| #641 | none | 2 | catalog-rules, engine-structure, engine-units |
| #643 | none | 0 | none |
| #644 | catalog-lane | 2 | engine-structure |
| #645 | none | 2 | db-core, engine-structure, fidelity-references |
| #649 | none | 2 | engine-config, engine-structure, site-text, ui-billboard |
| #659 | ui-lane | 2 | engine-structure |
| #662 | none | 1 | engine-config, engine-coordinator, engine-defects, engine-generate, engine-structure, fidelity-runner, web-build |
| #663 | ui-lane | 2 | engine-structure |
| #772 | engine-lane | 0 | none |
| #774 | engine-lane | 0 | none |

```python
"""Open PRs vs the train's ownership refusal at the integration tip (SHARED-NEEDS-NO-OWNER audit, item 1).

python3 measure.py <tip>: lists every open PR over the repository's REST client (github_api), reads its file list,
and judges it with this checkout's train_ownership at <tip>'s manifests: the lane the gate would name (lane_of) and
the train's refusals() with nobody approving (approvals=list), which is what the train sees, because no approval
can arrive.
"""
from pathlib import Path
import sys

sys.path.insert(0, 'scripts/lib')
import github_api  # noqa: E402
import train_git  # noqa: E402
import train_ownership  # noqa: E402
from gate_areas import glob_match  # noqa: E402

REPO, TIP, PAGE = 'openuniversity-si/open-university', sys.argv[1], 100
WAIT = int(sys.argv[2]) if len(sys.argv) > 2 else None  # github_api max_wait_s: wait out a recorded limiter block
ownership = train_ownership.UnitOwnership(train_git.GitWorkspace(Path('.')))
shared = sorted({glob for manifest in ownership.manifests(TIP) for glob in manifest.get('shared') or []})


def listing(path):
    found, page = [], 1
    while True:
        batch = github_api.rest('GET', f'{path}per_page={PAGE}&page={page}', expect=list, max_wait_s=WAIT)
        found += batch
        if len(batch) < PAGE:
            return found
        page += 1


pulls = sorted(listing(f'/repos/{REPO}/pulls?state=open&'), key=lambda pull: pull['number'])
print('shared globs at tip:', shared)
print('authors:', sorted({pull['user']['login'] for pull in pulls}))
counts = {'open': 0, 'non-draft': 0, 'touch shared': 0, 'refused': 0, 'refused for a shared file': 0}
for pull in pulls:
    files = [item['filename'] for item in listing(f"/repos/{REPO}/pulls/{pull['number']}/files?")]
    hit = [name for name in files if any(glob_match(name, glob) for glob in shared)]
    lane = ownership.lane_of(TIP, files)
    refused = ownership.refusals(TIP, files, lane, list)
    blamed = sorted({name for item in refused for name in item['files']} & set(hit))
    counts['open'] += 1
    if pull['draft']:
        print(f"#{pull['number']} draft, {len(hit)} shared file(s)")
        continue
    counts['non-draft'] += 1
    counts['touch shared'] += bool(hit)
    counts['refused'] += bool(refused)
    counts['refused for a shared file'] += bool(blamed)
    print(f"#{pull['number']} base={pull['base']['ref']} lane={lane} shared={len(hit)} "
          f"refused={sorted(item['unit'] for item in refused)} shared_refused={len(blamed)}")
print(counts)
```

## The rule the fix applies

Declaring a path `shared` means exactly "several lanes write it legitimately". So a shared path can never be the reason
a change waits for anyone. `lanes()` already reads `shared` that way. `refusals()` must read it the same way, through
the same list, so the two can never disagree again: one helper returns a manifest's deciding paths (its `paths` without
its `shared` globs), and both rules call it.

A shared path stays owned for naming. `owner_of()` still names its unit, and `refusals()` still lists the unit when a
non-shared path of it is touched, naming only that path. The naming of events keeps it too: `forge_events.unit_of`
counted the units of a change through `refusals(commit, files, None, list)`, every touched unit with shared ones
included. LANE-OWN's audit (finding 2) called that "right for naming". If `unit_of` went on reading the new
`refusals()`, a change of only shared paths would lose its `unit`, and the train queue weighs entries by `unit`
(`scripts/lib/train_queue.py:72`). So `unit_of` moves to a naming query of its own, `units()`, over every path, and its
results do not change.

The ownership check for non-shared paths is unchanged.

## Other rules that wait for an approval that cannot arrive

Search: `rg -n -i "approv|needs-approval|needs_approval" scripts/lib --glob '!**/generated/**'` gives 104 lines
(`| wc -l`) in 21 files (`rg -l … | wc -l`). 11 of those files are JSON data (`--glob '*.json'`): literal baselines and
test titles, not rules. `media-parity.mjs` names an approved font. Then `rg -n -i "owner" scripts/lib --glob '*.py'`,
filtered on wait, confirm, decision, refus, block, approv and review. `needs-approval` and `needs_approval` match
nothing (`rg -c` over `scripts/lib`: 0 files). Every rule found is listed below; this PR changes none of them.

| # | Rule | Where | What it waits for | Can it block? |
|---|---|---|---|---|
| 1 | Train ownership, non-shared path | `scripts/lib/train.py:170-180`, `scripts/lib/train_ownership.py:53-67` | The manifest `owner` among the approvers, i.e. the reviewer logins whose latest review is `APPROVED` (`scripts/lib/forge_github.py:180-190`) | **Yes, and the approval never arrives.** The owner is a lane id (`engine-lane`); no reviewer login equals a lane id. Even mapped through `generate.codeowners_identities`, all 18 lanes name one identity, `@the-owner`, the author of every PR, and GitHub does not let an author approve their own pull request. It fires only on a manifest change between a PR's merge base and the train's tip, because the gate's `lane_errors` (`scripts/lib/structure.py:474`) already refuses a PR whose non-shared paths span two lanes. The brief keeps this rule as it is; the dead approval clause is a finding only. |
| 2 | Fit-Review `approved` trailer (D-054) | `scripts/lib/structure.py:93-130`; `scripts/lib/ship_verify.py:214-217` | An "Independent fit review (reviewer session, head …): APPROVED" comment on the head | No. Only a body that claims `approved` needs it; `not reviewed (Daniel 2026-10-25: no review step)` passes (`structure.py:94`, D-055). A reviewer is a session, not the owner, and ship-verify is frozen (D-054). |
| 3 | A gate change cites a decision (D-025) | `scripts/lib/commit_check.py:125-135`; `scripts/lib/local_checks.py:133-139` | A `D-NNN` that `docs/domain/DECISIONS.md` records | No. Any recorded decision satisfies it, and the author writes the citation. |
| 4 | An owner wait in a PR comment (X1) | `scripts/lib/decision_wait.py:72-100` (commit-check `decision`, stall-report `owner_wait`) | A later `Decision:` line | No. The session writes the `Decision:` line itself (DECIDE, THEN REPORT); the rule exists to stop sessions from waiting. |
| 5 | A high-radius premise (D-066) | `scripts/lib/premises.py:467-473`, read by `scripts/lib/structure.py:456` | `confirmed` with the literal quote, or `validated` | Only a PR that cites an open high-radius premise. `validated` settles it with evidence and no one's words (`premises.quote_required_statuses` is `["confirmed"]`). Not an approval. |
| 6 | Quarantine release | `scripts/lib/quarantine.py:125-148` | A merged PR of the owning lane that names the test as stabilized | No merge waits on it. It gates only the release of a quarantined test, and the owning lane can always merge its own fix. |
| 7 | CODEOWNERS | `scripts/lib/generate_codeowners.py:31-58` renders `CODEOWNERS` | `@the-owner` on every path | Not today. GitHub enforces code owners only through branch protection, which this repository does not have (`scripts/lib/commit_check.py:9-10`). If code-owner review were ever required, every PR would wait for the reason in row 1. |
| 8 | Capability dates (D-054) | `scripts/lib/structure.py:190-192` | Nothing: an `approved` date may not precede `requested` | No. A date-order check. |
| 9 | Neon compute envelope | `scripts/lib/neon_pr.py:159` | Nothing: a fixed cost limit | No. A static limit; "approved" names the envelope. |

Only row 1 waits for something that cannot arrive, and only row 1 can stop a merge on its own. Its shared-path half
is the stop this PR removes; its non-shared half is kept by the brief.

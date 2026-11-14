# Program fluxo-amplo: plan

## Alternativas
<!-- The units below are the work the lanes run now. The roots are in diagnostico.md; the decisions are in DECISIONS.md. -->

## Escolha
<!-- The coordinator reads the graph below; a lane takes its next unit from `scripts/coordinator next fluxo-amplo`, not from a
     message to a session. Status is never written here: `scripts/program status fluxo-amplo` folds it from events. -->

## Units

The PR graph is data (contracts/programs/program.v1.json). The main metric of FLUXO-AMPLO is counted integrated commits
(D-137, `scripts/flow-metrics`); the program gate measures PRs (`prs_merged_per_hour`), so it is the program's goal here
until the coordinator can count commits from git.

```json program.v1
{
  "contract": "program.v1",
  "program": "fluxo-amplo",
  "complaint": {
    "symptom": "the gate on the e2-micro takes far more than the 10 s of the regime of exception, and the lanes wait on it",
    "evidence": "docs/process/lane.md; base real gate 152 s cold and 10 s warm (db422dcd, D-191 and after)",
    "goal": {
      "metric": "prs_merged_per_hour",
      "comparator": "gte",
      "target": 7,
      "unit": "prs/hour"
    }
  },
  "units": [
    {
      "id": "CANALE2",
      "title": "the board: the state kinds edit a fixed set of comments on one issue (BOARD, E2)",
      "depends_on": [],
      "owner": "lane-1",
      "model": "claude-opus-5-5",
      "wave": 1,
      "done": [
        "the board kinds make no new comment on #865; one comment per section on the board issue, edited in place",
        "a test fails without each proof: rewritten, two writers converge, deleted by hand recreated once, oversize cut to the ref"
      ]
    },
    {
      "id": "CANALE3",
      "title": "rotation as code: past a threshold the next board opens and config points to it (E3)",
      "depends_on": [
        "CANALE2"
      ],
      "owner": "lane-1",
      "model": "claude-opus-5-5",
      "wave": 1,
      "done": [
        "past forge-events.github_comment_limit minus its margin the next issue opens and the key points to it",
        "the old issue gets one pointer line; a test fails without the rotation"
      ]
    },
    {
      "id": "CANALE5",
      "title": "the open pull requests of the redesign rebased with lane-ship, gated, through the train (E5)",
      "depends_on": [
        "CANALE3"
      ],
      "owner": "lane-1",
      "model": "claude-opus-5-5",
      "wave": 1,
      "done": [
        "every open pull request of the redesign is merged by the train or recorded with its reason",
        "no pull request is closed to clean up"
      ]
    },
    {
      "id": "CANALE7",
      "title": "the engine operates without GitHub: monitoring, control and communication channels (E7, /workspace/torre/redesenho-canal/e7-sem-github.md)",
      "depends_on": [
        "CANALE5"
      ],
      "owner": "lane-1",
      "model": "claude-opus-5-5",
      "wave": 1,
      "done": [
        "with api.github.com unreachable a session publishes STATUS, reads its own work, receives a decision and records a result",
        "the control plane holds the event route and forge_events has its adapter; GitHub keeps only the code (branch, PR, merge, gate)"
      ]
    },
    {
      "id": "CANALE8",
      "title": "one forge port of six operations (change, identity, append, read, set_status, merge); Origin implements all six; the switch is forge.adapter (/workspace/torre/redesenho-canal/e8-adaptador-total.md)",
      "depends_on": [
        "CANALE7"
      ],
      "owner": "lane-1",
      "model": "claude-opus-5-5",
      "wave": 1,
      "done": [
        "the same test file runs against the GitHub and the Origin adapters, and passes on both with api.github.com refusing every call",
        "scripts/config set forge.adapter origin changes no train, gate, lane or caller module"
      ]
    },
    {
      "id": "CANALTRIGGER",
      "title": "one train: a train that is not the designated one refuses before it takes the lock (TRIGGER-HOST)",
      "depends_on": [
        "CANALE8"
      ],
      "owner": "lane-1",
      "model": "claude-opus-5-5",
      "wave": 1,
      "done": [
        "the designated owner, an instance token in the lease and one instance per host; busy is not retried as a wait",
        "the four ways a second train appears each have a test"
      ]
    },
    {
      "id": "CANALSYNC",
      "title": "the branch sync is one command and the hand merge of the base is refused at push (BRANCH-SYNC)",
      "depends_on": [
        "CANALTRIGGER"
      ],
      "owner": "lane-1",
      "model": "claude-opus-5-5",
      "wave": 1,
      "done": [
        "scripts/lane-ship --sync covers a clean branch, a local commit, a conflict and a branch already in sync",
        "commit-check --local refuses a merge of the base with git default message"
      ]
    },
    {
      "id": "G1",
      "title": "the e2-micro gate, measured",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "the real gate on the e2-micro is measured cold and warm",
        "under 10 s, or a decision records the measured limit"
      ]
    },
    {
      "id": "G2",
      "title": "the cold script-test stage",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "the cold base gate is measured before and after",
        "every cut is proved with scripts/covers-prove or a measured cache hit"
      ]
    },
    {
      "id": "S1",
      "title": "structure warnings of the env, events and structure units",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "scripts/structure-check shows no warning for the three units"
      ]
    },
    {
      "id": "P1",
      "title": "the pre-push hook costs",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "a real push is measured before and after",
        "no refusal is lost: a test fails without each cut"
      ]
    },
    {
      "id": "N6",
      "title": "delivery, forge and service units: the steps a session does by hand become scripts",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "every manual step in the units' docs is a script or is named as judgment (D-200)",
        "one PR per unit group, real gate, no oversize warning"
      ]
    },
    {
      "id": "N7",
      "title": "check units: budgets, slo, battery, census, literals, vendors, wrappers: the checks run without an AI session",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "the checks report through a script (scripts/checks, one line per check, pass, warn or fail) in engine-budgets; the service health report is not changed here (D-205)",
        "one PR per unit group, real gate, no oversize warning"
      ]
    },
    {
      "id": "N8",
      "title": "process units: rules, premises, effort, intake, lessons, retro, commit-plan, defects, quarantine, coordinator",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "the templates are generated by a script from the registry, with a drift test in engine-intake (D-205)",
        "one PR per unit group, real gate, no oversize warning"
      ]
    },
    {
      "id": "B1",
      "title": "the brief is stored when the work is assigned, so it never depends on the stage (D-206 (b))",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "a unit's brief is kept with its work.assigned event and printed after its start",
        "a test fails without the stored brief"
      ],
      "pr": 925
    },
    {
      "id": "F1",
      "title": "the unit's status comes from the merged pull requests of its branch (D-206 (c))",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "a unit merged outside the coordinator's launch shows merged in scripts/program status",
        "a test fails without the change"
      ],
      "pr": 925
    },
    {
      "id": "C1",
      "title": "no git write passes text as a command-line argument (D-206 (a))",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "every git write of text goes through stdin, one helper, with a test that a 200 KB record is written",
        "a grep test fails on any new '-m' with a record"
      ],
      "pr": 949
    },
    {
      "id": "L1",
      "title": "every external command the engine launches is probed before a launch (D-206 (d))",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "the coordinator's launcher probes its command's flag before it launches; a stale argument fails at preflight",
        "a test fails with the stale argument"
      ]
    },
    {
      "id": "R1",
      "title": "the train refuses a merge on a red base, so the regime cannot hide one (D-206 (e))",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "the train holds a merge while the base's last real gate is red",
        "a test fails without the hold"
      ]
    },
    {
      "id": "D1",
      "title": "the decisions register: one record per decision, the table generated (D-208)",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "scripts/decision new claims the number, stamps the clock and writes docs/domain/decisions/D-NNN.md",
        "docs/domain/DECISIONS.md is generated from the records, and the migration of the existing rows is one commit that a test checks"
      ],
      "pr": 946
    },
    {
      "id": "F2",
      "title": "a branch starts from the base in one command (scripts/branch-start)",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "scripts/branch-start NAME fetches the base and creates the branch from it, refusing a dirty tree or a name already on the remote",
        "a test fails without the refusals"
      ]
    },
    {
      "id": "M9",
      "title": "engine-gate-tests: its tests and checks run without a session to read them (D-209)",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "engine-gate-tests is held by lane 9 (D-209), its covers narrowed with scripts/covers-prove where a test does not read a glob",
        "one PR per change, real gate, no oversize warning"
      ],
      "pr": 969
    },
    {
      "id": "M10",
      "title": "engine-gate-ops: its tests and checks run without a session to read them (D-209)",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "engine-gate-ops is held by lane 10 (D-209), its covers narrowed with scripts/covers-prove where a test does not read a glob",
        "one PR per change, real gate, no oversize warning"
      ],
      "pr": 953
    },
    {
      "id": "M11",
      "title": "engine-gate-verdict: its tests and checks run without a session to read them (D-209)",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "engine-gate-verdict is held by lane 11 (D-209), its covers narrowed with scripts/covers-prove where a test does not read a glob",
        "one PR per change, real gate, no oversize warning"
      ]
    },
    {
      "id": "M12",
      "title": "engine-generate: its tests and checks run without a session to read them (D-209)",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "engine-generate is held by lane 12 (D-209), its covers narrowed with scripts/covers-prove where a test does not read a glob",
        "one PR per change, real gate, no oversize warning"
      ],
      "pr": 960
    },
    {
      "id": "M13",
      "title": "engine-units: its tests and checks run without a session to read them (D-209)",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "engine-units is held by lane 13 (D-209), its covers narrowed with scripts/covers-prove where a test does not read a glob",
        "one PR per change, real gate, no oversize warning"
      ],
      "pr": 958
    },
    {
      "id": "M14",
      "title": "engine-forge-github: its tests and checks run without a session to read them (D-209)",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "engine-forge-github is held by lane 14 (D-209), its covers narrowed with scripts/covers-prove where a test does not read a glob",
        "one PR per change, real gate, no oversize warning"
      ]
    },
    {
      "id": "M15",
      "title": "engine-quarantine and engine-production: its tests and checks run without a session to read them (D-209)",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "engine-quarantine and engine-production is held by lane 15 (D-209), its covers narrowed with scripts/covers-prove where a test does not read a glob",
        "one PR per change, real gate, no oversize warning"
      ]
    },
    {
      "id": "M16",
      "title": "engine-merge-regenerate: its tests and checks run without a session to read them (D-209)",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "engine-merge-regenerate is held by lane 16 (D-209), its covers narrowed with scripts/covers-prove where a test does not read a glob",
        "one PR per change, real gate, no oversize warning"
      ]
    },
    {
      "id": "K1",
      "title": "the program's goal is counted commits per hour, measured from git (D-218 (1))",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "scripts/coordinator status reports the counted commits of the last hour, from flow-metrics, as the goal",
        "a test fails with the goal measured from pull requests"
      ]
    },
    {
      "id": "K5",
      "title": "the commit plan is per commit; the pull request is a container for the train (D-218 (2))",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "done": [
        "scripts/pr-body and scripts/commit-check read the plan per commit, each commit naming what it delivers",
        "the 3-to-8 rule in AGENTS.md is replaced or kept by a decision of Daniel's (recorded)"
      ]
    },
    {
      "id": "I1",
      "title": "incident register: every refusal and stop is an incident with case, class and design (D-234, priority)",
      "depends_on": [],
      "owner": "lane-1",
      "model": "lane-session",
      "wave": 1,
      "done": [
        "every refusal of lane-ship, the gate and the push opens an incident",
        "scripts/incident list shows the open ones; each incident has its case, class and design fields"
      ]
    },
    {
      "id": "E1",
      "title": "the regime of exception: the lanes run under a declared regime with its own gate and bypass (D-191 to D-200)",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "pr": 997,
      "done": [
        "the regime is declared in the registry and the lanes read it",
        "lane-status prints the regime and drift is named"
      ]
    },
    {
      "id": "W1",
      "title": "the write queue: creates and decision writes go through one queue, not by hand",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "pr": 1007,
      "done": [
        "a create is queued and written by the script, not by a session",
        "a repeated write is refused, not duplicated"
      ]
    },
    {
      "id": "RN1",
      "title": "the runner serves the gate and the train with no session to read them",
      "depends_on": [],
      "owner": "queue",
      "model": "lane-session",
      "wave": 2,
      "pr": 904,
      "done": [
        "scripts/service runner gates new heads and runs the train with no AI session",
        "pause, resume and requeue work on the runner"
      ]
    }
  ]
}
```

## Lanes closed by quota (D-277, 01/11 15:14 BRT)
Five lane sessions run at most (`coordinator.max_sessions` = 5). Lanes 1, 2, 6, 8 and 16 stay. Lanes 3, 4, 5, 7, 9, 10, 11, 12,
13, 14 and 15 are closed by quota on 01/11: each finishes the pull request it has open and takes no next unit; a lane idle
before that leaves at once. Owner `queue` means pending: the coordinator launches nothing for it until a decision adds a lane
with the quota measured.

| Lane | Its units | Where they go |
|---|---|---|
| 3 | G2 | lane 2 (the gate's owner) |
| 4 | S1, C1 | queue |
| 5 | P1 | queue |
| 7 | N7 | queue (lane 7 finishes its open pull request first) |
| 9 to 15 | M9, M10, M11, M12, M13, M14, M15 | queue (M10, M11 and M12 merged their pull requests on 01/11: #933, #936, #980) |

The channel redesign (E2 the board, E3 rotation, E5 the open pull requests, TRIGGER-HOST, BRANCH-SYNC) is lane 1's; E1 merged (#1030).

## Only the redesign runs, serially (D-281, 01/11 15:30 BRT)
Daniel: one session, one open pull request at a time, merged before the next opens. The graph holds the channel redesign as
six units of lane 1 in one chain, CANALE2 -> CANALE3 -> CANALE5 -> CANALE7 -> CANALE8 -> CANALTRIGGER -> CANALSYNC, in wave 1 (CANALE7: Daniel, 15:43 BRT; CANALE8, one forge port with Origin as its second adapter: Daniel, 16:04 BRT); every other unit,
lanes 1 to 16 included, is queued (owner `queue`, wave 2): it keeps its branch and its open pull request and is not launched.
`coordinator.max_sessions` = 1. The ids drop the hyphen of the order's `CANAL-E2` because program.v1 accepts letters and digits only.

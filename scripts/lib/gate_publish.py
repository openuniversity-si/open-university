"""When and where the gate publishes its verdict (GX-39 seam, moved from gate_report.main and emit_evidence).

GX-12 (D-070): a tier-2 run (no PR, a full sha) publishes on the repository channel with `pr` null."""
import re

SHA = re.compile(r'[0-9a-f]{40}')


def should_publish(mode, pr, sha):
    """The tier-1 rule: a named mode, a PR and a full commit sha."""
    return bool(mode and pr and SHA.fullmatch(sha))


def repository_run(mode, pr, sha):
    """GX-12: a gate with a named mode and a full sha but no PR (tier 2, bisection probes) belongs to the repository channel."""
    return bool(mode and not pr and SHA.fullmatch(sha))


def publishes(mode, pr, sha):
    """Either rule: a run with neither a PR nor a full sha, or with no mode, publishes nothing."""
    return should_publish(mode, pr, sha) or repository_run(mode, pr, sha)


def change_number(pr):
    """The PR number of the envelopes, None (pr null) for a repository-channel run."""
    return int(pr) if pr else None


def tier(mode, pr, tier1_modes, current, repository_tier):
    """`repository_tier` (the caller's registry read) for a repository-channel run; otherwise
    `current(mode, tier1_modes)` (gate_tier.current, passed in)."""
    return current(mode, tier1_modes) if pr else repository_tier


def channel(mode, logs):
    """The writer id of the gate's append: the mode and the run folder that holds the logs."""
    from pathlib import Path
    return f'gate:{mode}:{Path(logs).resolve().parent.name}'

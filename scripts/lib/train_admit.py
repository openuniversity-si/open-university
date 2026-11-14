"""Verdict admission (D-075, amends D-065 (5); P-53 under P-43): may the train merge one PR on its own verdict?

With train.admit_mode verdict the train asks `admissible` for every queued PR before it builds a batch. The proof is
the gate.passed the PR's pr.ready rests on (train_queue.Entry.evidence). The answer is yes only when that verdict
proves the exact tree the train will merge, with no relaxation of P-43:

  source      the proof was read from the verified source (train_reuse.verified_source: a remote forge that keeps only
              trusted author associations), at the v4 proof version (gate_proof.proof_version), type gate.passed;
  input       plan dev (train-reuse.tier2_plan, the plan the train reuses), payload.sha is the pinned head, base_sha is
              the integration tip T, and T is an ancestor of the head: a no-fast-forward merge of the head into T has
              the head's tree, so the tested tree is the merged tree;
  machine     toolchain_id is the train's own attestation (GX-28) and gate_version is the tip's (P-46: the pinned gate);
  digest      head_tree is the head's tree and the input_digest recomputed with the PR formula (selection_digest of the
              plan with no batch) equals the proof's: the recorded digest is never trusted;
  cold        no carried_from and, unless the train reuses by content (D-076, P-56: the tip's tooling keys every cached
              result by its content), cost.cache_hits 0, no stage cached and no cached_tests: never a result of
              another tree.

Shard admission (D-075 as amended 29/10 14:52, P-54; partially refutes P-43 for this path only). A verdict made on an
older tip B (every condition above except base_sha == T) still admits when the caller passes a Shard: B is an ancestor
of the head and of T, and disjoint() found nothing: T is at most train.shard_admit_max_behind merges past B, neither
B..head nor B..T touches a train.shard_admit_never path, and their units+dependents keys (train_shard.key, manifests at
T, generated outputs not skipped) share no element. The digest is then recomputed with B, the base the gate judged.
Whether an admission acts is the caller's (train.shard_admit: shadow only measures it).

Self-hosting admission (D-079, amends D-075; TRAIN-ADMIT-GATE-CHANGE). A PR that changes the toolchain set (the gate,
the train, the registry: train.self_host_paths) brings its own attestation, so its toolchain_id can never be the
train's. With a SelfHost, a verdict whose only difference from the rule above is that foreign toolchain_id admits on a
dual verdict: this proof is the pinned gate on the tip (gate_version is still the tip's, P-46) and every other
condition holds, the digest recomputed with the proof's own toolchain_id; and the second leg, the head's own tooling
run cold on the same head (SelfHost.judge, called last and only then), passes. Either leg red refuses. A PR that
touches none of the paths is judged as before. After the merge the tip carries the new tooling and registry, so the
next attestation is the new pin.

Anything missing or different refuses with one reason (fail closed); the train then takes train.verdict_fallback.
Pure: the caller reads git (the head's tree, the ancestry, the tip's gate_version, the changed files, the manifests)
and passes the values in.
"""
from collections import namedtuple

from gate_areas import glob_match
import gate_digest
import gate_proof
import train_shard

KIND = 'gate.passed'
WARM = 'the verdict is not cold'  # the refusal of a verdict resting on tier-1 box-local markers
Shard = namedtuple('Shard', 'base_in_head base_in_tip collision')  # the ancestry of B and disjoint()'s answer
# the toolchain-set paths the PR changes, and the head's own toolchain leg: judge() -> (passed, why)
SelfHost = namedtuple('SelfHost', 'touched judge')


def admissible(proof, tip, head, head_tree, contains_tip, toolchain_id, gate_version, plan, version, verified,
               shard=None, self_host=None, content=False):
    """(True, the input_digest) when `proof` lets the train merge `head` alone on `tip`, else (False, the reason).
    With `shard`, a verdict on an older tip is judged by the shard rule instead of refused; with `self_host`, a
    foreign toolchain_id of a PR that changes the toolchain set is judged by the dual verdict. With `content` (the
    train's gate.content_cache_enabled, D-076) a verdict whose hits were all reused by content is cold enough (warmth)."""
    if not verified:
        return False, 'the proof was not read from a verified source'
    if not isinstance(proof, dict) or proof.get('type') != KIND:
        return False, f'the evidence is not a {KIND}'
    if proof.get('version') != version:
        return False, f'proof version {proof.get("version")} is not the v4 proof version {version}'
    payload = proof.get('payload') or {}
    if payload.get('plan') != plan:
        return False, f'plan {payload.get("plan")} is not {plan}'
    if payload.get('sha') != head:
        return False, f'the proof is of {payload.get("sha")}, not the head {head}'
    base = payload.get('base_sha')
    if base != tip:
        refused = behind(base, tip, shard)
        if refused:
            return False, refused
    elif not contains_tip:
        return False, f'the head does not contain the tip {tip}'
    foreign = payload.get('toolchain_id') != toolchain_id
    if foreign:
        if base != tip or self_host is None or not self_host.touched:
            return False, f'toolchain {payload.get("toolchain_id")} is not the attested {toolchain_id}'
        toolchain_id = payload.get('toolchain_id')  # the head's own: the digest is recomputed with it
    if payload.get('gate_version') != gate_version:
        return False, f'gate_version {payload.get("gate_version")} is not the tip gate {gate_version}'
    if payload.get('head_tree') != head_tree:
        return False, f'head_tree {payload.get("head_tree")} is not the head tree {head_tree}'
    try:
        digest = gate_digest.input_digest(head_tree, base, plan, gate_proof.selection_digest(plan, None), toolchain_id,
                                          gate_version)
    except ValueError as error:
        return False, str(error)
    if payload.get('input_digest') != digest:
        return False, f'input_digest {payload.get("input_digest")} is not the recomputed {digest}'
    warm = warmth(payload, content)
    if warm:
        return False, f'{WARM} ({warm})'
    if foreign:
        passed, why = self_host.judge()
        if not passed:
            return False, f'dual verdict: the head\'s own toolchain {toolchain_id} did not pass ({why})'
    return True, digest


def behind(base, tip, shard):
    """Why a verdict on base `base`, not the tip, does not admit (no shard, or the shard rule refuses), else ''."""
    if shard is None:
        return f'the verdict was made on base {base}, not the tip {tip}'
    if not shard.base_in_head:
        return f'the head does not contain its verdict base {base}'
    if not shard.base_in_tip:
        return f'the verdict base {base} is not an ancestor of the tip {tip}'
    if shard.collision:
        return f'shard: {shard.collision}'
    return ''


def disjoint(manifests, pr_files, base_files, distance, max_behind, never):
    """'' when the PR's change (B..head) and the base's (B..tip) cannot touch each other, else the first refusal: the
    tip too far past B, a train.shard_admit_never path on either side, or a shared element of their shard keys.
    Generated outputs are not skipped here (unlike the shadow report): two regenerations collide."""
    if distance > max_behind:
        return f'the tip is {distance} merges past the verdict base (train.shard_admit_max_behind {max_behind})'
    for side, files in (('the PR', pr_files), ('the base', base_files)):
        hit = sorted(path for path in files if any(glob_match(path, glob) for glob in never))
        if hit:
            return f'{side} changes {hit[0]}, a train.shard_admit_never path'
    shared = sorted(set(train_shard.key(manifests, pr_files)) & set(train_shard.key(manifests, base_files)))
    if shared:
        return f'overlap on {", ".join(shared)}'
    return ''


def warmth(payload, content=False):
    """Why the verdict rests on a result of another tree, or '' when everything ran or was reused by content.

    D-076 (P-56): with `content` (the train's gate.content_cache_enabled), cached tests and stages are this tree's
    results: the proof's gate_version is the tip's (checked before), and that tooling keys every cached result by the
    content it reads, the attested toolchain and the judging runner (gate_keys.key_parts). Only a stage carried over
    from another head (carried_from) still refuses. Without it, any hit refuses (P-43, D-075)."""
    if payload.get('carried_from'):
        return f'carried from {(payload["carried_from"] or {}).get("sha")}'
    if content:
        return ''
    hits = (payload.get('cost') or {}).get('cache_hits')
    if hits != 0:
        return f'cache_hits {hits}'
    if payload.get('carried_from'):
        return f'carried from {(payload["carried_from"] or {}).get("sha")}'
    if payload.get('cached_tests'):
        return f'{len(payload["cached_tests"])} cached test(s)'
    cached = [stage.get('name') for stage in payload.get('stages') or () if stage.get('cached')]
    if cached:
        return f'cached stage(s) {", ".join(map(str, cached))}'
    return ''

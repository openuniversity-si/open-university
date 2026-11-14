"""input_digest of a gate verdict (GX-37, GA2 Q14): a pure function a verifier recomputes from git and the toolchain manifest.

  sha256 of the canonical JSON array [head_tree, base_sha, plan, selection_digest, toolchain_id, gate_version]
  (sorted keys, no spaces, UTF-8); the order is part of the contract, a new input is a new gate.passed version.
"""
import hashlib
import json

FIELDS = ('head_tree', 'base_sha', 'plan', 'selection_digest', 'toolchain_id', 'gate_version')


def input_digest(head_tree, base_sha, plan, selection_digest, toolchain_id, gate_version):
    parts = [head_tree, base_sha, plan, selection_digest, toolchain_id, gate_version]
    for name, part in zip(FIELDS, parts):
        if not isinstance(part, str) or not part:
            raise ValueError(f'input_digest: {name} must be a non-empty string')
    return hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

"""Tier-2 reuse of exactly-matching attested proofs (GX-31, B-20 (b), D-070 under GA-P02 strict, P-43).

The train's judge path (GX-30, train.Train.judge) asks this module before a tier-2 run (the batch head or a bisection
probe). A run is skipped only when a proof matches the exact key the train recomputes itself for the judged commit:

  key         head_tree (the judged commit's tree), base_sha (the batch base), plan (train-reuse.tier2_plan, the plan
              scripts/gate-batch binds), selection_digest (gate_proof.selection_digest of the union selection
              gate_batch.plan derives for the base, the members and the commit, the same file gate-local binds),
              toolchain_id (gate_keys.toolchain_id, the GX-28 attestation of this container, E49) and gate_version
              (gate_proof.gate_version of the tool root), hashed by gate_digest.input_digest. A proof's own digest is
              never trusted: the train computes the one it looks for.
  proof       a gate.passed at the v4 proof version (gate_proof.proof_version) on the repository channel (pr null),
              tier gate-tier.batch, whose input_digest and every key field above are equal.
  verified    read only from the adapter that stores gate.passed when it is remote and keeps only trusted writers
              (forge_control: the holders of the events token,
              which the control plane demands on every append); the port re-validates every
              envelope and recomputes its event_id. A local log (forge-events.file_kinds, a box-local file) or an
              in-memory log is never a source, nor a .pass record or a result-cache marker (tier 1).

Anything else runs: a missing or unattested input, an adapter that cannot be read, no match (fail closed). The switch
train-reuse.reuse_attested_proofs off is the one-key rollback: tier 2 never reuses and nothing here reads the forge
(D-065 (5) as before GX-31).
"""
import config
import forge_events

PROOF_KIND = 'gate.passed'
KEY_FIELDS = ('head_tree', 'base_sha', 'plan', 'toolchain_id', 'gate_version', 'input_digest')


def enabled(root=None):
    """train-reuse.reuse_attested_proofs of the checkout at `root` (the train's own, engine_role.ROOT)."""
    return bool(config.get('train-reuse.reuse_attested_proofs', root))


def attested_toolchain():
    """The GX-28 attestation of this container (gate_keys, the same id the gate binds); raises when not attested."""
    import gate_keys
    return gate_keys.toolchain_id()


def verified_source(adapter, kind=PROOF_KIND):
    """The adapter that stores `kind` when it is remote and names its trusted writers (`trusted`), else None."""
    route = getattr(adapter, 'route', None)
    target = route(kind) if callable(route) else adapter
    if getattr(target, 'remote', False) and getattr(target, 'trusted', None):
        return target
    return None


class Reuse:
    """The lookup for one train: `root` holds the judged commits (the train's workspace), `tool_root` is the checkout
    whose scripts/ run tier 2 (gate_version) and whose registry is read. `toolchain_id` and `gate_version` are
    injectable callables (tests); by default the attestation and gate_proof's recipe."""

    def __init__(self, repo, root, tool_root, toolchain_id=None, gate_version=None):
        self.repo, self.root, self.tool_root = repo, root, tool_root
        self.toolchain_id = toolchain_id or attested_toolchain
        self.gate_version = gate_version or self.tool_gate_version

    def tool_gate_version(self):
        """The tooling's scripts/ tree, read once per lookup object (GATE-SPEED F3): one train run judges every batch
        with one checkout of the tooling, and each read was a git process (1,162 of them in the train's tests)."""
        if getattr(self, '_tool_gate_version', None) is None:
            import gate_proof
            self._tool_gate_version = gate_proof.gate_version(self.tool_root)
        return self._tool_gate_version

    def key(self, base, heads, commit):
        """The exact proof key of a tier-2 run on `commit` (base and member heads in batch order). Raises when an
        input is missing or cannot be read."""
        import gate_batch
        import gate_digest
        import gate_proof
        plan = config.get('train-reuse.tier2_plan', self.tool_root)
        batch = gate_batch.plan(self.root, base, list(heads), commit)
        if batch['conflicts'] or batch['selection'] is None:
            raise ValueError(f'{commit} is not the union of its members on {base}')
        key = {'head_tree': gate_proof.tree(self.root, batch['head']), 'base_sha': batch['base'], 'plan': plan,
               'selection_digest': gate_proof.selection_digest(plan, batch['selection']),
               'toolchain_id': self.toolchain_id(), 'gate_version': self.gate_version()}
        key['input_digest'] = gate_digest.input_digest(*(key[name] for name in gate_digest.FIELDS))
        return key

    def find(self, port, base, heads, commit):
        """(the matching verified proof envelope or None, the reason in one line). Never raises: a failure runs."""
        try:
            source = verified_source(port.adapter)
            if source is None:
                return None, 'no verified source (gate.passed is not stored by a remote log with trusted writers)'
            key = self.key(base, heads, commit)
            import gate_proof
            version, tier = gate_proof.proof_version(PROOF_KIND), config.get('gate-tier.batch', self.tool_root)
            reader = forge_events.ForgeEvents(source, port.clock, port.producer, port.correlation_id)
            for event in reversed(reader.read_recent(self.repo, kinds=[PROOF_KIND])):  # D-085
                if matches(event, key, version, tier):
                    return event, f'input_digest {key["input_digest"]}'
            return None, f'no verified proof for input_digest {key["input_digest"]}'
        except Exception as error:  # noqa: BLE001 - any failure means "not proven here": tier 2 runs (fail closed)
            return None, f'lookup failed ({type(error).__name__}: {error})'


def matches(event, key, version, tier):
    """True when `event` is a passing tier-2 v4 proof on the repository channel for exactly `key`."""
    payload = event.get('payload') or {}
    return (event.get('type') == PROOF_KIND and event.get('version') == version and payload.get('pr') is None
            and payload.get('tier') == tier
            and all(payload.get(name) == key[name] for name in KEY_FIELDS)
            and (payload.get('selection') or {}).get('digest') == key['selection_digest'])

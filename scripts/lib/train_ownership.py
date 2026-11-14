"""The train's ownership check (D-069 item 8, plan v3.1 row M3): an interface over U0's unit manifests.

A change outside the lane's units needs the owner's approval. The manifests are U0's (`units/<id>/unit.json`: `id`,
`owner`, `lane`, `paths`, ...; plan v3 §4.2), read at the integration tip the batch is built on, so the rule is the
one already merged. While no manifest exists there (today), refusals() is a no-op and owner_of() finds no owner (the
quarantine, M7, then names quarantine.unknown_owner): this module adds no ownership mechanism of its own, and it never
asks the forge for approvals unless a manifest makes them matter. A path a manifest declares `shared` never needs that
approval: several lanes write it (SHARED-NEEDS-NO-OWNER).
"""
import json

import config
from gate_areas import glob_match


def deciding(manifest):
    """The manifest's paths that decide a lane and can refuse a change: its `paths` without its `shared` ones.

    lanes() and refusals() both read this one list (SHARED-NEEDS-NO-OWNER), so they cannot disagree about a shared
    path again; owner_of() and units() still name a unit by all of its paths.
    """
    shared = set(manifest.get('shared') or [])
    return [glob for glob in manifest.get('paths', []) if glob not in shared]


class UnitOwnership:
    def __init__(self, workspace):
        self.workspace = workspace
        self.manifest_glob = config.get('train.unit_manifests')

    def manifests(self, commit):
        """Every unit manifest in the commit's tree, by path order: one listing and one batched read per commit,
        remembered by its sha (git_objects, GATE-SPEED R2)."""
        paths = sorted(path for path in self.workspace.paths(commit) if glob_match(path, self.manifest_glob))
        texts = self.workspace.files(commit, paths)
        return [json.loads(texts[path]) for path in paths]

    def retired(self, commit, files, head):
        """D-112: the ids of the units the change retires: their manifest at the commit is one of the files and is gone
        at the head. A retired unit decides no lane and refuses nothing; without a head no unit is retired."""
        if not head:
            return set()
        gone = [path for path in self.workspace.paths(commit) if glob_match(path, self.manifest_glob)
                and path in set(files) and not self.workspace.has_path(head, path)]
        texts = self.workspace.files(commit, gone)
        return {json.loads(texts[path])['id'] for path in gone}

    def lanes(self, commit, files, head=None):
        """{unit: lane} of the units whose paths the files touch at the commit, shared paths aside (LANE-OWN).

        The one lane rule: lane_of() and structure.lane_errors() both read it, so a PR announced with a lane is judged
        by the rule that named it. A shared path is written by several lanes: it never decides the lane and never
        refuses a change (refusals() reads the same deciding() list), and owner_of() still names its unit.
        """
        touched, retired = {}, self.retired(commit, files, head)
        for manifest in self.manifests(commit):
            if manifest['id'] in retired:
                continue
            globs = deciding(manifest)
            if any(glob_match(path, glob) for path in files for glob in globs):
                touched[manifest['id']] = manifest.get('lane', manifest.get('owner'))
        return touched

    def lane_of(self, commit, files, head=None):
        """The one lane of lanes(), else None (no unit, only shared paths, or several lanes: refused)."""
        lanes = set(self.lanes(commit, files, head).values())
        return lanes.pop() if len(lanes) == 1 else None

    def owner_of(self, commit, path):
        """(unit, owner) of the first manifest at the commit whose paths cover the file, else (None, None)."""
        for manifest in self.manifests(commit):
            if any(glob_match(path, glob) for glob in manifest.get('paths', [])):
                return manifest['id'], manifest.get('owner')
        return None, None

    def units(self, commit, files):
        """[unit] of the manifests at the commit whose paths, shared ones included, the files touch: the naming of a
        change (forge_events.unit_of), which never refuses anything."""
        return [manifest['id'] for manifest in self.manifests(commit)
                if any(glob_match(path, glob) for path in files for glob in manifest.get('paths', []))]

    def refusals(self, commit, files, lane_id, approvals, head=None):
        """[{unit, owner, files}] of the units outside lane_id that the files touch without their owner's approval.

        Only the deciding() paths count: a shared path never asks anybody, and a foreign unit lists only its non-shared
        files (SHARED-NEEDS-NO-OWNER). approvals is a callable returning the approvers of the change; it is called at
        most once, and only when a foreign unit is touched.
        """
        foreign, retired = [], self.retired(commit, files, head)
        for manifest in self.manifests(commit):
            if manifest['id'] in retired:
                continue
            globs = deciding(manifest)
            touched = [path for path in files if any(glob_match(path, glob) for glob in globs)]
            if touched and manifest.get('lane', manifest.get('owner')) != lane_id:  # D-067 (2): the owner is the lane
                foreign.append({'unit': manifest['id'], 'owner': manifest.get('owner'), 'files': touched})
        if not foreign:
            return []
        approvers = set(approvals())
        return [item for item in foreign if item['owner'] not in approvers]

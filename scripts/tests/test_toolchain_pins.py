#!/usr/bin/env python3
"""The toolchain pins live in the registry; scripts/cloud/toolchain.json keeps checksums only (D-069 item 12)."""
import copy
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config
import forge_events
import gate_digest
import gate_proof
import toolchain_manifest as manifest
import train_admit


class RemoteForge(forge_events.MemoryAdapter):
    remote = True  # the shared store on the forge, as the train reads it


class Clock:
    def now(self):
        return datetime.datetime.fromtimestamp(0, datetime.timezone.utc)


class ToolchainPins(unittest.TestCase):
    def test_every_tool_version_comes_from_the_registry(self):
        loaded, pinned = manifest.load(), manifest.versions()
        for tool, version in pinned.items():
            self.assertEqual(loaded[tool]['version'], version)
        self.assertEqual(pinned['node'], config.get('toolchain.node_version'))

    def test_the_checksum_file_holds_no_version_list(self):
        raw = json.loads(manifest.MANIFEST.read_text())
        # vazão F6 and F16: a tool that left TOOLS (gh, the Vercel CLI, pnpm) leaves no checksums behind.
        self.assertEqual(set(raw) - {'environment'}, set(manifest.TOOLS))
        for tool in manifest.TOOLS:
            self.assertNotIn('version', raw[tool])
            self.assertNotIn('revision', raw[tool])
            self.assertNotIn('tag', raw[tool])

    def test_every_pinned_version_has_its_checksums(self):
        loaded = manifest.load()
        for tool in manifest.TOOLS:
            self.assertTrue(manifest.artifact(tool, loaded)['url'])

    def test_a_pin_without_checksums_is_refused(self):
        original = config.get
        config.get = lambda name: '0.0.0' if name == 'toolchain.node_version' else original(name)
        try:
            with self.assertRaisesRegex(RuntimeError, 'no sha256 for node 0.0.0'):
                manifest.load()
        finally:
            config.get = original


SHELL = shutil.which('sh')
# What each fake binary prints for `observed_version` (GX-28 fixture container, no network, no real toolchain).
BANNERS = {'python': '{v}', 'node': 'v{v}', 'gitleaks': '{v}', 'postgres': 'psql (PostgreSQL) {v}'}


def fake_toolchain(root, versions, calls=None):
    """A `.toolchain` whose bin/ answers the version probes; `calls` names a file each probe appends to."""
    (root / 'bin').mkdir(parents=True, exist_ok=True)
    for tool, version in versions.items():
        binary = root / 'bin' / manifest.binary_name(tool)
        log = f'echo {tool} >> {calls}\n' if calls else ''
        binary.write_text(f'#!{SHELL}\n{log}echo "{BANNERS[tool].format(v=version)}"\n')
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)


class Attestation(unittest.TestCase):
    """GX-28: toolchain_id attests what is installed and the committed registry, never install.stamp."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name) / '.toolchain'
        self.pins = {tool: manifest.load()[tool]['version'] for tool in manifest.TOOLS}
        fake_toolchain(self.root, self.pins)

    def tearDown(self):
        self.dir.cleanup()

    def test_observed_versions_cover_every_listed_tool(self):
        seen = manifest.observed_versions(self.root)
        self.assertEqual(list(seen), config.get('toolchain.observed_tools'))
        self.assertEqual({tool: seen[tool] for tool in manifest.TOOLS}, self.pins)
        # F54: the engine drives no browser (D-113), so chromium is neither observed nor a value the registry takes.
        self.assertEqual(set(config.get('toolchain.observed_tools')), set(manifest.TOOLS))
        self.assertEqual(config.entry('toolchain.observed_tools', manifest.ROOT)['items']['enum'], list(manifest.TOOLS))
        with self.assertRaisesRegex(RuntimeError, 'unknown tool chromium'):
            manifest.observed_versions(self.root, tools=['chromium'])

    def test_a_stale_toolchain_gets_another_id(self):
        fresh = manifest.attestation(self.root)
        fake_toolchain(self.root, {'postgres': '17.2'})
        stale = manifest.attestation(self.root)
        self.assertEqual(stale['observed_versions']['postgres'], '17.2')
        self.assertNotEqual(stale['toolchain_id'], fresh['toolchain_id'])
        self.assertEqual(manifest.install_id(), manifest.install_id())  # the pins alone would not have seen it

    def test_a_missing_binary_is_absent_and_changes_the_id(self):
        fresh = manifest.attestation(self.root)
        (self.root / 'bin' / 'gitleaks').unlink()
        gone = manifest.attestation(self.root)
        self.assertEqual(gone['observed_versions']['gitleaks'], manifest.ABSENT)
        self.assertNotEqual(gone['toolchain_id'], fresh['toolchain_id'])

    def test_the_install_stamp_is_never_the_answer(self):
        fresh = manifest.attestation(self.root)
        (self.root / 'install.stamp').write_text(manifest.install_id() + '\n')
        fake_toolchain(self.root, {'node': '20.0.0'})
        self.assertNotEqual(manifest.attestation(self.root)['toolchain_id'], fresh['toolchain_id'])

    def test_a_probe_is_reused_only_while_the_binary_keeps_its_identity(self):
        calls = Path(self.dir.name) / 'calls'
        fake_toolchain(self.root, self.pins, calls)
        manifest.attestation(self.root)
        manifest.attestation(self.root)
        self.assertEqual(sorted(calls.read_text().split()), sorted(manifest.TOOLS))
        fake_toolchain(self.root, {'gitleaks': self.pins['gitleaks']}, calls)
        manifest.attestation(self.root)
        probes = calls.read_text().split()
        self.assertEqual(sorted(probes), sorted([*manifest.TOOLS, 'gitleaks']))

    def attest_under(self, adapter, change=None):
        """The attestation a process gets when its change store is `adapter` (after `change`, a (name, value) set)."""
        with config.use_adapter(adapter, Clock()):
            if change:
                config.set_value(*change, actor='train', reason='a shared-store override', now=Clock().now())
            self.assertEqual(bool(config.overrides()), bool(change))
            return manifest.attestation(self.root)

    def test_the_file_and_the_shared_store_attest_one_id(self):
        """D-080: the gate (OU_CONFIG_STORE=file) and the train (the shared store) attest the same head alike."""
        gate = self.attest_under(forge_events.MemoryAdapter())
        size = config.get('train.batch_size')
        train = self.attest_under(RemoteForge(), ('train.batch_size', size + 1))
        self.assertEqual(train['registry_digest'], gate['registry_digest'])
        self.assertEqual(train['toolchain_id'], gate['toolchain_id'])

    def test_a_committed_tooling_change_gets_another_id(self):
        fresh = manifest.attestation(self.root)
        committed = config.files()
        changed = copy.deepcopy(committed)
        changed['toolchain'][1]['properties']['toolchain.observed_tools']['default'] = ['python', 'node']
        with mock.patch.object(config, 'files', lambda root=None: changed):
            tooling = manifest.attestation(self.root)
        self.assertNotEqual(tooling['registry_digest'], fresh['registry_digest'])
        self.assertNotEqual(tooling['toolchain_id'], fresh['toolchain_id'])
        fake_toolchain(self.root, {'node': '20.0.0'})
        self.assertNotEqual(manifest.attestation(self.root)['toolchain_id'], fresh['toolchain_id'])

    def test_strict_admission_admits_a_session_verdict(self):
        """D-075 strict admission: a verdict the gate made under the file store admits on the train's shared store."""
        gate = self.attest_under(forge_events.MemoryAdapter())['toolchain_id']
        size = config.get('train.batch_size')
        train = self.attest_under(RemoteForge(), ('train.batch_size', size + 1))['toolchain_id']
        tip, head, tree = (hashlib.sha1(name.encode()).hexdigest() for name in ('tip', 'head', 'tree'))
        gate_version = hashlib.sha256(b'gate').hexdigest()
        plan = 'dev'
        digest = gate_digest.input_digest(tree, tip, plan, gate_proof.selection_digest(plan, None), gate, gate_version)
        version = gate_proof.proof_version()
        proof = {'type': train_admit.KIND, 'version': version, 'payload': {
            'plan': plan, 'sha': head, 'base_sha': tip, 'head_tree': tree, 'toolchain_id': gate,
            'gate_version': gate_version, 'input_digest': digest, 'cost': {'cache_hits': 0}, 'stages': []}}
        self.assertEqual(train_admit.admissible(proof, tip, head, tree, True, train, gate_version, plan, version, True),
                         (True, digest))


if __name__ == '__main__':
    unittest.main()

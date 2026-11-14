"""Tier-1 result cache: the tier guard, the content key, store and hit (D-065 V6, M5). Hermetic: temp repos only.

OU-DECOUPLE F5 (D-113): the lint and typecheck keys (`key`) left with Open University's web stages; every key here is a
stage key (`stage_key`) of a stage the test declares deterministic, over a product fixture under products/demo.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import gate_result_cache as cache  # noqa: E402

REAL_GET = cache.get
INPUT_KEYS = ("gate-inputs.enabled", "gate-inputs.schema_version")
OUTSIDE_TIER_ONE = ("pr", "nightly", "noite", "db", "full", "tier3", "")


class TierGuardTest(unittest.TestCase):
    def test_only_the_pr_gate_is_tier_one(self):
        self.assertEqual(cache.tier_of("dev"), 1)
        for mode in OUTSIDE_TIER_ONE:
            with self.subTest(mode=mode):
                self.assertIsNone(cache.tier_of(mode))

    def test_unit_seam_is_null_until_u0(self):
        self.assertIsNone(cache.unit_hash())


class RepoCase(unittest.TestCase):
    """A repository with a product fixture and one stage declared deterministic over it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name) / "repo"
        self.product = self.root / "products" / "demo"
        self.write("products/demo/index.ts", "export const a = 1;\n")
        self.write("scripts/lib/other.py", "x = 1\n")
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True)
        self.stage_all()
        self.cache_dir = pathlib.Path(self._tmp.name) / "cache"
        self.spec = {"version": 1, "deterministic": True, "inputs": ["products/demo/**"]}

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def stage_all(self):
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)

    def key(self, mode="dev", stage="stage a", scope="", spec=None, overrides=None):
        values = {**{name: cache.get(name) for name in cache.TOOLCHAIN_PINS}, **(overrides or {}),
                  **{name: cache.get(name) for name in ("gate.stage_cache_enabled", "gate.stage_cache_version", *INPUT_KEYS)
                     if name not in (overrides or {})}}
        declared = {"stages": {stage: spec or self.spec}}
        with mock.patch.object(cache, "declaration", side_effect=lambda name: declared["stages"].get(name)), \
                mock.patch.object(cache, "get", side_effect=lambda name: values[name]):
            return cache.stage_key(mode, self.root, stage, scope)


class StageCacheTest(RepoCase):
    """GS1: a stage declared deterministic is cached by its declared inputs; nothing else is."""

    def test_the_same_inputs_give_the_same_key(self):
        self.assertTrue(self.key())
        self.assertEqual(self.key(), self.key())

    def test_a_declared_input_change_misses(self):
        before = self.key()
        self.write("products/demo/index.ts", "export const a = 2;\n")
        self.assertNotEqual(self.key(), before)

    def test_an_untracked_input_misses(self):
        before = self.key()
        self.write("products/demo/new.ts", "export {};\n")
        self.assertNotEqual(self.key(), before)

    def test_a_file_outside_the_declared_inputs_does_not_change_the_key(self):
        before = self.key()
        self.write("scripts/lib/other.py", "x = 2\n")
        self.assertEqual(self.key(), before)

    def test_a_deleted_input_misses(self):
        before = self.key()
        (self.product / "index.ts").unlink()
        self.assertNotEqual(self.key(), before)

    def test_modification_time_does_not_change_the_key(self):
        before = self.key()
        os.utime(self.product / "index.ts", (1, 1))
        self.assertEqual(self.key(), before)

    def test_a_stage_version_bump_misses(self):
        self.assertNotEqual(self.key(), self.key(spec={**self.spec, "version": 2}))

    def test_a_different_input_declaration_misses(self):
        self.assertNotEqual(self.key(), self.key(spec={**self.spec, "inputs": ["**"]}))

    def test_a_scope_change_misses(self):
        self.assertNotEqual(self.key(scope="scoped a"), self.key(scope="scoped b"))
        self.assertNotEqual(self.key(scope="full"), self.key(scope="scoped"))

    def test_the_stage_id_is_part_of_the_key(self):
        self.assertNotEqual(self.key(stage="stage a"), self.key(stage="stage b"))

    def test_every_toolchain_pin_misses(self):
        before = self.key()
        for name in cache.TOOLCHAIN_PINS:
            with self.subTest(pin=name):
                self.assertNotEqual(self.key(overrides={name: cache.get(name) + ".1"}), before)

    def test_the_pins_come_from_the_registry(self):
        self.assertEqual(sorted(cache.TOOLCHAIN_PINS), sorted(
            name for name in ("toolchain.node_version", "toolchain.python_version", "toolchain.claude_cli_version")))
        for name in cache.TOOLCHAIN_PINS:
            self.assertTrue(cache.get(name))

    def test_the_registry_key_version_misses(self):
        self.assertNotEqual(self.key(), self.key(overrides={"gate.stage_cache_version": cache.get("gate.stage_cache_version") + 1}))

    def test_a_stage_that_is_not_declared_deterministic_has_no_key(self):
        self.assertEqual(self.key(spec={**self.spec, "deterministic": False}), "")
        with mock.patch.object(cache, "declaration", return_value=None):
            self.assertEqual(cache.stage_key("dev", self.root, "script tests"), "")

    def test_tiers_two_and_three_and_the_flag_have_no_key(self):
        for mode in OUTSIDE_TIER_ONE:
            with self.subTest(mode=mode):
                self.assertEqual(self.key(mode=mode), "")
        self.assertEqual(self.key(overrides={"gate.stage_cache_enabled": False}), "")

    def test_the_shipped_declarations_cache_only_stages_that_exist_and_never_the_judging_ones(self):
        declared = json.loads(cache.DECLARATIONS.read_text())["stages"]
        for name in ("pr metadata", "structure check", "script tests"):
            self.assertFalse((declared.get(name) or {}).get("deterministic", False), name)
        for name, spec in declared.items():
            if spec["deterministic"]:
                self.assertTrue(spec["inputs"] and isinstance(spec["version"], int), name)

    def test_a_fresh_marker_hits_and_an_expired_one_misses(self):
        ttl = cache.get("gate.stage_cache_ttl_s")
        cache.store(self.cache_dir, "k1", now=1000)
        self.assertTrue(cache.hit(self.cache_dir, "k1", now=1000))
        self.assertTrue(cache.hit(self.cache_dir, "k1", now=1000 + ttl))
        self.assertFalse(cache.hit(self.cache_dir, "k1", now=1000 + ttl + 1))

    def test_a_marker_from_the_future_misses(self):
        cache.store(self.cache_dir, "k2", now=5000)
        self.assertFalse(cache.hit(self.cache_dir, "k2", now=4999))

    def test_corrupt_markers_miss(self):
        for name, blob in (("empty", b""), ("garbage", b"\x00\xffnot json"), ("list", b"[]"), ("scalar", b"7"),
                           ("no-key", b'{"stored_at": 1000}'), ("no-time", b'{"key": "c-no-time"}'),
                           ("text-time", b'{"key": "c-text-time", "stored_at": "1000"}'),
                           ("bool-time", b'{"key": "c-bool-time", "stored_at": true}'),
                           ("other-key", b'{"key": "someone-else", "stored_at": 1000}')):
            with self.subTest(case=name):
                key = f"c-{name}"
                cache.storage.open_store(self.cache_dir).put(f"tier1/{key}", blob)
                self.assertFalse(cache.hit(self.cache_dir, key, now=1000))

    def test_a_missing_marker_misses(self):
        self.assertFalse(cache.hit(self.cache_dir, "never-stored", now=1000))


class AttestedToolchainTest(StageCacheTest):
    """GX-28: every key carries the attested toolchain_id (gate_keys.key_parts); a stale `.toolchain` misses."""

    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(ROOT / "scripts" / "tests"))
        from test_toolchain_pins import fake_toolchain
        import gate_keys
        import toolchain_manifest
        self.fake, self.gate_keys = fake_toolchain, gate_keys
        self.toolchain = pathlib.Path(self._tmp.name) / ".toolchain"
        self.pins = {tool: toolchain_manifest.load()[tool]["version"] for tool in toolchain_manifest.TOOLS}
        self.fake(self.toolchain, self.pins)
        environ = mock.patch.dict(os.environ, {"OU_TOOLCHAIN_DIR": str(self.toolchain)})
        environ.start()
        self.addCleanup(environ.stop)
        gate_keys.reset()
        self.addCleanup(gate_keys.reset)

    def keys(self):
        """(key of one stage, key of another) of a fresh process (one attestation per process)."""
        self.gate_keys.reset()
        first = self.key()
        self.gate_keys.reset()
        return first, self.key(stage="stage b")

    def test_the_key_parts_are_the_attested_toolchain_id_and_the_judging_runner(self):
        import toolchain_manifest
        self.assertEqual(self.gate_keys.key_parts(),
                         ["toolchain", toolchain_manifest.attestation(self.toolchain)["toolchain_id"],
                          "runner", self.gate_keys.runner_digest()])

    def test_a_changed_runner_misses_every_cache(self):
        """D-076: the runner is the part of gate_version a cached result depends on."""
        fresh = self.keys()
        with mock.patch.object(self.gate_keys, "runner_digest", return_value="another runner"):
            changed = self.keys()
        self.assertNotEqual(changed[0], fresh[0])
        self.assertNotEqual(changed[1], fresh[1])

    def test_an_unreadable_runner_never_shares_a_key(self):
        with mock.patch.object(self.gate_keys, "runner_digest", side_effect=OSError("gone")):
            first, second = self.keys(), self.keys()
        self.assertNotEqual(first[0], second[0])
        self.assertNotEqual(first[1], second[1])

    def test_the_same_toolchain_gives_the_same_keys(self):
        self.assertEqual(self.keys(), self.keys())

    def test_a_stale_toolchain_misses_every_cache(self):
        fresh = self.keys()
        self.fake(self.toolchain, {"gitleaks": "0.0.1"})
        stale = self.keys()
        self.assertNotEqual(stale[0], fresh[0])
        self.assertNotEqual(stale[1], fresh[1])

    def test_an_unattested_run_never_shares_a_key(self):
        with mock.patch("toolchain_manifest.attestation", side_effect=RuntimeError("no registry")):
            first, second = self.keys(), self.keys()
        self.assertNotEqual(first[0], second[0])
        self.assertNotEqual(first[1], second[1])

    def test_d082_one_run_keys_every_process_alike_even_when_it_cannot_attest(self):
        """GX-23: gate-local exports one snapshot per run; a fresh process inherits it instead of attesting again."""
        with mock.patch("toolchain_manifest.attestation", side_effect=RuntimeError("probe failed")):
            self.gate_keys.reset()
            exported = self.gate_keys.snapshot()
            with mock.patch.dict(os.environ, {self.gate_keys.ENV: exported}):
                first, second = self.keys(), self.keys()
        self.assertEqual(first, second)
        self.assertIn("unattested", json.loads(exported)["parts"])

    def test_d082_a_probe_that_fails_mid_run_keeps_the_keys_of_the_run(self):
        self.gate_keys.reset()
        with mock.patch.dict(os.environ, {self.gate_keys.ENV: self.gate_keys.snapshot()}):
            fresh = self.keys()
            with mock.patch("toolchain_manifest.attestation", side_effect=RuntimeError("probe failed")), \
                    mock.patch.object(self.gate_keys, "runner_digest", side_effect=OSError("rewritten")):
                failed = self.keys()
        self.assertEqual(failed, fresh)

    def test_d082_a_snapshot_of_other_tooling_or_malformed_is_ignored(self):
        self.gate_keys.reset()
        exported = json.loads(self.gate_keys.snapshot())
        for name, value in (("root", "/elsewhere"), ("toolchain_dir", "/other/.toolchain"), ("parts", []),
                            ("parts", "toolchain"), ("parts", ["toolchain", ""])):
            with self.subTest(field=name, value=value), \
                    mock.patch.dict(os.environ, {self.gate_keys.ENV: json.dumps({**exported, name: value})}):
                self.assertIsNone(self.gate_keys.inherited())
                self.assertEqual(self.gate_keys.key_parts(), self.gate_keys.computed_parts())
        for raw in ("not json", "[]", ""):
            with self.subTest(raw=raw), mock.patch.dict(os.environ, {self.gate_keys.ENV: raw}):
                self.assertIsNone(self.gate_keys.inherited())

    def test_d082_the_exported_parts_reach_another_process(self):
        env = {**os.environ, "OU_TOOLCHAIN_DIR": str(self.toolchain)}
        lib = ROOT / "scripts" / "lib"
        exported = subprocess.run([sys.executable, str(lib / "gate_keys.py"), "export"], env=env, capture_output=True,
                                  text=True, check=True).stdout.strip()
        probe = "import gate_keys, json; print(json.dumps(gate_keys.key_parts()))"

        def child():
            return subprocess.run([sys.executable, "-c", probe], cwd=lib, env={**env, "GATE_KEY_PARTS": exported},
                                  capture_output=True, text=True, check=True).stdout

        first, second = child(), child()
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first), json.loads(exported)["parts"])


class StoreTest(RepoCase):
    def test_a_stored_pass_hits_only_its_own_key(self):
        cache_dir = pathlib.Path(self._tmp.name) / "cache"
        mine = self.key()
        self.write("products/demo/index.ts", "export const a = 3;\n")
        other = self.key()
        self.assertFalse(cache.hit(cache_dir, mine))
        cache.store(cache_dir, mine)
        self.assertTrue(cache.hit(cache_dir, mine))
        self.assertFalse(cache.hit(cache_dir, other))

    def test_a_cold_verdict_keeps_its_stage_markers_apart_from_its_build_cache(self):
        """D-076: GATE_STAGE_CACHE_DIR, set by gate-verdict --cold, holds the markers instead of the build cache."""
        build, stages = (pathlib.Path(self._tmp.name) / name for name in ("build", "stages"))
        mine = self.key()
        with mock.patch.dict(os.environ, {"GATE_STAGE_CACHE_DIR": str(stages)}):
            cache.store(build, mine)
            self.assertTrue(cache.hit(build, mine))
        self.assertFalse(cache.hit(build, mine))
        self.assertTrue(cache.hit(stages, mine))

    def test_an_empty_key_is_never_stored_or_hit(self):
        cache_dir = pathlib.Path(self._tmp.name) / "cache"
        with self.assertRaises(ValueError):
            cache.store(cache_dir, "")
        self.assertFalse(cache.hit(cache_dir, ""))

    def test_a_cached_stage_says_so_in_its_record(self):
        logs = pathlib.Path(self._tmp.name) / "logs"
        logs.mkdir()
        cache.record_cached(logs, "schema compat", "abc123")
        stage = json.loads((logs / "schema_compat.stage.json").read_text())
        self.assertEqual(stage, {"name": "schema compat", "result": "PASS", "exit": 0, "seconds": 0,
                                 "cached": True, "key": "abc123"})
        self.assertIn("cached", (logs / "schema_compat.log").read_text())


class DeclaredInputsTest(RepoCase):
    """GX-23 (B-15, GA-P10): a declared stage keys on its declared inputs and the traced read set; narrowing fails closed."""

    STAGES = ("stage a", "stage b")

    def setUp(self):
        super().setUp()
        self.write("config/registry/battery.json", "{}\n")
        self.write("docs/notes.md", "a\n")
        self.stage_all()
        self.declared = {name: {"inputs": ["products/demo/**"], "traced": ["config/registry/battery.json"]}
                         for name in self.STAGES}
        self.values = {}

    def config(self, name):
        return self.values[name] if name in self.values else REAL_GET(name)

    def keys(self, mode="dev", declared=None, scope=""):
        payload = {"shared_inputs": ["package.json"], "stages": self.declared if declared is None else declared}
        spec = {"version": 1, "deterministic": True, "inputs": ["**"]}
        inputs = pathlib.Path(self._tmp.name) / "gate-stage-inputs.json"
        inputs.write_text(json.dumps(payload))
        with mock.patch.object(cache, "INPUTS", inputs), mock.patch.object(cache, "declaration", return_value=spec), \
                mock.patch.object(cache, "get", side_effect=self.config):
            return {name: cache.stage_key(mode, self.root, name, scope) for name in self.STAGES}

    def test_a_scripts_or_docs_only_change_hits_every_declared_stage(self):
        before = self.keys()
        self.assertTrue(all(before.values()))
        self.write("scripts/lib/other.py", "x = 2\n")
        self.write("docs/notes.md", "b\n")
        self.write("scripts/lib/new.py", "y = 1\n")
        self.assertEqual(self.keys(), before)

    def test_a_declared_input_change_misses_every_declared_stage(self):
        before = self.keys()
        self.write("products/demo/index.ts", "export const a = 2;\n")
        after = self.keys()
        for name in self.STAGES:
            self.assertNotEqual(after[name], before[name], name)

    def test_a_traced_file_outside_the_globs_misses(self):
        before = self.keys()
        self.write("config/registry/battery.json", '{"changed": true}\n')
        after = self.keys()
        for name in self.STAGES:
            self.assertNotEqual(after[name], before[name], name)

    def test_an_undeclared_stage_keys_on_its_stage_inputs(self):
        undeclared = {name: spec for name, spec in self.declared.items() if name != "stage a"}
        before = self.keys(declared=undeclared)
        self.write("scripts/lib/other.py", "x = 2\n")
        after = self.keys(declared=undeclared)
        self.assertNotEqual(after["stage a"], before["stage a"])
        self.assertEqual(after["stage b"], before["stage b"])

    def test_the_flag_off_gives_the_keys_from_before_gx23(self):
        self.values["gate-inputs.enabled"] = False
        off = self.keys()
        self.assertEqual(off, self.keys(declared={}))
        self.write("scripts/lib/other.py", "x = 2\n")
        self.assertTrue(all(self.keys()[name] != off[name] for name in self.STAGES))

    def test_the_declaration_and_schema_version_are_key_parts(self):
        before = self.keys()
        wider = {name: {**spec, "inputs": [*spec["inputs"], "units/**"]} for name, spec in self.declared.items()}
        self.assertTrue(all(self.keys(declared=wider)[name] != before[name] for name in self.STAGES))
        self.values["gate-inputs.schema_version"] = cache.get("gate-inputs.schema_version") + 1
        self.assertTrue(all(self.keys()[name] != before[name] for name in self.STAGES))

    def test_a_malformed_declaration_fails_closed(self):
        for bad in ({"inputs": []}, {"inputs": "products/demo/**", "traced": []}, {"inputs": ["products/demo/**"]},
                    {"inputs": [""], "traced": []}, ["products/demo/**"]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.keys(declared={"stage a": bad})
        spec = {"version": 1, "deterministic": True, "inputs": ["**"]}
        with mock.patch.object(cache, "INPUTS", pathlib.Path(self._tmp.name) / "missing.json"), \
                mock.patch.object(cache, "declaration", return_value=spec), \
                mock.patch.object(cache, "get", side_effect=self.config), self.assertRaises(ValueError):
            cache.stage_key("dev", self.root, "stage a")

    def test_tiers_two_and_three_still_get_no_key(self):
        for mode in OUTSIDE_TIER_ONE:
            with self.subTest(mode=mode):
                self.assertEqual(set(self.keys(mode=mode).values()), {""})


class ShippedInputsTest(unittest.TestCase):
    """The committed gate-stage-inputs.json parses, and every traced path is covered or listed."""

    def setUp(self):
        self.document = json.loads(cache.INPUTS.read_text())
        self.stages = self.document["stages"]

    def test_the_declaration_parses_and_every_declared_stage_is_a_cached_stage(self):
        # OU-DECOUPLE F5 (D-113): the web stages it declared left with Open University; no engine stage is cached.
        self.assertIsInstance(self.document["shared_inputs"], list)
        declared = json.loads(cache.DECLARATIONS.read_text())["stages"]
        for name in self.stages:
            self.assertIsNotNone(cache.declared_inputs(name), name)
            self.assertTrue((declared.get(name) or {}).get("deterministic"), name)
        self.assertIsNone(cache.declared_inputs("script tests"))

    def test_every_traced_path_exists_in_the_tree(self):
        for name, spec in self.stages.items():
            for path in spec["traced"]:
                self.assertTrue((ROOT / path).exists() or "*" in path, f"{name}: {path}")


if __name__ == "__main__":
    unittest.main()

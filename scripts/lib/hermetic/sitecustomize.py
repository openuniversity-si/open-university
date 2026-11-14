"""Starts the hermetic rules (scripts/lib/hermetic.py) in every Python process of a script test, children included.

The rules are the tooling's (the judge's), the code under test is not: once they are installed this file takes the tooling's
scripts/lib modules and path entry back out, so the code under test imports its own config, regime, hermetic and the rest.
Its own config is pinned to the same store, and its own regime judges the rules as written, by an import hook, because the
pins live in the modules and not in os.environ (D-272: the live exception regime lifts the locks the script tests assert)."""
import importlib.util
import os
import pathlib
import sys

if os.environ.get('COVERAGE_PROCESS_START'):  # GATE-SPEED's coverage guard (D-116): every test process is measured
    try:
        import coverage
        coverage.process_startup()
    except ImportError:
        pass

_LIB = pathlib.Path(__file__).resolve().parents[1]
_before = set(sys.modules)

sys.path.insert(0, str(_LIB))
import hermetic  # noqa: E402
import config  # noqa: E402

hermetic.install()
_KIND = config.store_kind()  # the store install() pinned


_PINS = {  # the code under test's own copies, pinned as they load
    'config': lambda module: module.pin_store(_KIND) if hasattr(module, 'pin_store') else None,  # the store kind
    'regime': lambda module: module.pin(False) if hasattr(module, 'pin') else None,  # the judges see no exception regime (D-272)
}


class _PinConfig:
    """Pins the store of every `config` module, and the judges' view of every `regime` module, imported from here on."""

    def find_spec(self, name, path=None, target=None):
        if name not in _PINS:
            return None
        for finder in sys.meta_path:
            spec = finder.find_spec(name, path, target) if finder is not self and hasattr(finder, 'find_spec') else None
            if spec is not None and spec.loader is not None:
                exec_module = spec.loader.exec_module
                pin = _PINS[name]

                def pinned(module, exec_module=exec_module, pin=pin):
                    exec_module(module)
                    pin(module)
                spec.loader.exec_module = pinned
                return spec
        return None


def _drop_tooling():
    for name in set(sys.modules) - _before:
        origin = getattr(sys.modules[name], '__file__', None)
        if origin and _LIB in pathlib.Path(origin).resolve().parents:
            del sys.modules[name]
    sys.path[:] = [entry for entry in sys.path if entry != str(_LIB)]
    sys.meta_path.insert(0, _PinConfig())


_drop_tooling()

"""Test doubles of the forge that carry the surface their consumer demands (ORIGIN-FINISH).

The port checks the surface of the calling consumer's whole demand (operation_demands.json) before any operation, so
a journal double without, say, `comments` is refused even when the test never reads comments. A double built here has
every demanded operation: the ones the test answers, and the rest refusing loudly if they are ever called.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import forge_events  # noqa: E402
import forge_requirements  # noqa: E402


def _refusing(operation):
    def refuse(*args, **kwargs):
        raise AssertionError(f'the test double was asked for {operation}, which this test does not answer')
    return refuse


def with_surface(adapter, *consumers):
    """`adapter`, given an instance method for each operation `consumers` demand that it lacks."""
    for operation in sorted(forge_requirements.for_consumers(consumers).required):
        if not callable(getattr(adapter, operation, None)):
            setattr(adapter, operation, _refusing(operation))
    return adapter


def journal(*consumers, changes=None):
    """A MemoryAdapter with the surface of `consumers`."""
    return with_surface(forge_events.MemoryAdapter(changes), *consumers)


def origin(**operations):
    """The Origin adapter (the one forge, D-293) with each named operation answered by the test: the port's proof check
    sees the adapter type it proves, and nothing reaches a client, a git remote or a journal."""
    import forge_origin
    adapter = object.__new__(forge_origin.OriginAdapter)
    for name, answer in operations.items():
        setattr(adapter, name, answer)
    return adapter

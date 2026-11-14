"""ORIGIN-FINISH: a test of one forge's path pins forge-events.adapter (and any other key) for its block, whatever the
registry default names; every other key keeps its effective value."""
from contextlib import contextmanager
from unittest import mock

import config


def pinned(**values):
    """config.get answers `values` (keys spelled with '_' for '-' and '__' for '.': forge_events__adapter) as given."""
    keys = {name.replace('__', '.').replace('_', '-'): value for name, value in values.items()}
    real = config.get
    return mock.patch.object(config, 'get', side_effect=lambda name, *rest, **options:
                             keys[name] if name in keys else real(name, *rest, **options))


class _Refused:
    """An Origin client and git refs on a declared Origin host whose every call is refused."""
    HOST = 'origin.test'

    def url(self):
        return f"https://{self.HOST}/{config.get('forge-events.repo')}.git"

    def __getattr__(self, name):
        def refuse(*args, **kwargs):
            raise AssertionError(f'the forge was called ({name}); this test builds it and never calls it')
        return refuse


@contextmanager
def origin():
    """The Origin adapter (D-293: the one forge), built offline for a test whose configured forge is built and never
    called: its client, git refs and journal refuse every call."""
    forge = _Refused()
    real = config.get
    with mock.patch.object(config, 'get', side_effect=lambda name, *rest, **options:
                           'origin' if name == 'forge-events.adapter' else [forge.HOST]
                           if name == 'origin-client.git_hosts' else real(name, *rest, **options)), \
            mock.patch('forge_origin_client.client_from_config', return_value=forge), \
            mock.patch('forge_origin.GitRefs', return_value=forge), \
            mock.patch('forge_origin.GitRefAdapter', return_value=forge):
        yield forge

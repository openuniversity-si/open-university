"""ENGINE-REPO (the migration to GitHub, 14/11/2026): the engine's repository on its forge comes from configuration.

The looks that read or answer for the engine's own repository (the canary's checkout, the check runs, the pre-gate, the
prewarm, the PR observation, the branch merges, the full run) asked for it as a constant. The public tree names the
public repository; the deployed engine may run against another (the forge it still reads, until it moves). repo()
answers, in order: TOWER_ENGINE_REPO in the process's environment; the `engine.repo` datum of the service's settings
(config_data, written by the Torre through PUT /v1/config/engine.repo, seen on tower_config without a deploy) once the
service handed them over with use(); DEFAULT. A value that is not `owner/name` is ignored.
"""
import os
import re

DEFAULT = 'openuniversity-si/open-university'
ENV = 'TOWER_ENGINE_REPO'
KEY = 'engine.repo'
SHAPE = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
_settings = []  # the service's config_data.Config, once handed over


def use(settings):
    """The service's settings: repo() reads `engine.repo` from them from now on."""
    _settings[:] = [settings]


def repo(environ=None):
    environ = os.environ if environ is None else environ
    for value in (environ.get(ENV, ''), *(each.get(KEY) for each in _settings)):
        value = str(value or '').strip()
        if SHAPE.match(value):
            return value
    return DEFAULT

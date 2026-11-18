"""The owners a requirement may name (EFFORT-STEP, D-069 item 8): every effort.* value and the word match, read by
the effort check (scripts/lib/effort.py, which re-exports them) and by the PR body a branch builds (pr_body). Its own
module under the configuration (D-322): delivery reads the owners without importing the measurement's check.
"""
import re

import config

NAMES = ('effort.heading', 'effort.fields', 'effort.requirement_field', 'effort.placeholders', 'effort.owners',
         'effort.owner_registry', 'effort.machine_words', 'effort.rule_doc')


def settings(root=None):
    """Every effort.* value, read once per check (a plan check judges every plan with one read of the registry)."""
    values = {name: config.get(name, root) for name in NAMES}
    values['owners'] = list(values['effort.owners']) + list(config.get(values['effort.owner_registry'], root))
    return values


def names(value, words):
    """The words of `words` that `value` names as a whole word (case-insensitive)."""
    return [word for word in words if re.search(r'(?<![\w-])' + re.escape(word) + r'(?![\w-])', value, re.IGNORECASE)]

"""The user-facing text check (D-069 item 15, plan v3.1 L1), a module of scripts/structure-check.

User-facing text is a registry entry marked `x-text: true` whose value is keyed by locale ({"en": "..."}); a product
reads it from the registry (Open University's web app and its `locale-text` generator left in OU-DECOUPLE F4 (D-111),
so this checkout holds no text entry and an empty visible scope). check(root) returns the
errors of the entries themselves, reusing config's loader and json_schema (no second validator):
  every x-text entry carries the default locale (l10n.default_locale) in its `required` list and its default, only
  locales of l10n.locales, and a non-empty string for each;
  every entry of the text owner (l10n.text_owner) is x-text, and an x-text entry lives only in that owner's file.
check_visible(root) refuses a user-visible string outside the text entries, only where text has migrated (P-05):
  l10n.scoped_files    every JSX text node, `{"string"}` child and literal l10n.visible_attributes value;
  l10n.scoped_exports  path:identifier whose exported constant must not be initialized by a string literal.
It is a lexical check (comments and code are told apart; no TypeScript parser), so it errs only toward the strings a
reader can see. The scope lists are registry data: a unit adds its files in U4.
check(root) runs both.
"""
from pathlib import Path
import re

import config


def text_entries(params):
    return {name: item for name, item in params.items() if item.get('x-text') is True}


def entry_errors(root):
    params = config._load(root)
    if 'l10n.locales' not in params:
        return []  # a repository without the l10n registry has no text rules to apply
    locales = config.get('l10n.locales', root)
    default = config.get('l10n.default_locale', root)
    owner = config.get('l10n.text_owner', root)
    errors = []
    if default not in locales:
        errors.append(f'l10n.default_locale {default!r} is not one of l10n.locales')
    for name, item in params.items():
        in_owner = name.startswith(owner + '.')
        if in_owner and item.get('x-text') is not True:
            errors.append(f'{name}: an entry of the {owner} owner must be user-facing text (x-text: true)')
        if item.get('x-text') is True and not in_owner:
            errors.append(f'{name}: x-text entries live in config/registry/{owner}.json (l10n.text_owner)')
    for name, item in text_entries(params).items():
        value = item.get('default')
        if default not in (item.get('required') or []):
            errors.append(f'{name}: x-text entry without {default}: "required" must list the default locale')
        if not isinstance(value, dict) or default not in value:
            errors.append(f'{name}: x-text entry without {default}: its default must be keyed by locale and carry {default}')
            continue
        for locale, text in value.items():
            if locale not in locales:
                errors.append(f'{name}: locale {locale!r} is not one of l10n.locales')
            if not isinstance(text, str) or not text.strip():
                errors.append(f'{name}: the {locale} text must be a non-empty string')
    return errors


COMMENT = re.compile(r'/\*.*?\*/|(?<![:"\'])//[^\n]*', re.S)
STRING_CHILD = re.compile(r'>\s*\{\s*(["\'`])((?:(?!\1)[^\\]|\\.)*)\1\s*\}')
JSX_TEXT = re.compile(r'(?<=>)([^<>{}]*)(?=<)')
NOT_TEXT = re.compile(r'[;=]|&&|\|\||=>')


def _blank(match):
    return re.sub(r'[^\n]', ' ', match.group(0))  # keep the line numbers


def _line(text, offset):
    return text.count('\n', 0, offset) + 1


def scoped_file_errors(path, text, attributes, letters):
    code = COMMENT.sub(_blank, text)
    enough = re.compile(rf'[A-Za-z][^A-Za-z]*' * letters)
    errors = []
    for match in JSX_TEXT.finditer(code):
        if enough.search(match.group(1)) and not NOT_TEXT.search(match.group(1)):
            errors.append(f'{path}:{_line(code, match.start(1))}: user-visible text {match.group(1).strip()!r} outside '
                          'the text entries; add a text.* registry entry and read it from the generated catalog (L1)')
    for match in STRING_CHILD.finditer(code):
        if enough.search(match.group(2)):
            errors.append(f'{path}:{_line(code, match.start())}: user-visible text {match.group(2)!r} outside the text '
                          'entries; add a text.* registry entry and read it from the generated catalog (L1)')
    names = '|'.join(re.escape(name) for name in attributes)
    for match in re.finditer(rf'\b({names})\s*=\s*(?:\{{\s*)?(["\'`])((?:(?!\2)[^\\]|\\.)*)\2', code):
        if enough.search(match.group(3)):
            errors.append(f'{path}:{_line(code, match.start())}: the {match.group(1)} attribute spells the visible text '
                          f'{match.group(3)!r}; read a text.* registry entry from the generated catalog (L1)')
    return errors


def scoped_export_errors(path, identifier, text):
    code = COMMENT.sub(_blank, text)
    found = re.search(rf'\bexport\s+const\s+{re.escape(identifier)}\b[^=\n]*=\s*(\S)', code)
    if not found:
        return [f'{path}: l10n.scoped_exports lists {identifier}, which the file no longer exports; remove the site']
    if found.group(1) in '"\'`':
        return [f'{path}:{_line(code, found.start(1))}: {identifier} spells a string literal; it has migrated to a text.* '
                'registry entry, so read it from the generated catalog (L1)']
    return []


def check_visible(root):
    params = config._load(root)
    if 'l10n.scoped_files' not in params:
        return []
    root = Path(root)
    attributes = config.get('l10n.visible_attributes', root)
    letters = config.get('l10n.visible_min_letters', root)
    errors = []
    for path in config.get('l10n.scoped_files', root):
        if not (root / path).is_file():
            errors.append(f'{path}: l10n.scoped_files lists a file that does not exist; remove the site')
            continue
        errors += scoped_file_errors(path, (root / path).read_text(encoding='utf-8'), attributes, letters)
    for site in config.get('l10n.scoped_exports', root):
        path, identifier = site.rsplit(':', 1)
        if not (root / path).is_file():
            errors.append(f'{path}: l10n.scoped_exports lists a file that does not exist; remove the site')
            continue
        errors += scoped_export_errors(path, identifier, (root / path).read_text(encoding='utf-8'))
    return errors


def check(root):
    return entry_errors(root) + check_visible(root)

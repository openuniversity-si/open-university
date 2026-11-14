"""Retro ingestion (LR1, D-069 items 4 and 9): a unit retro becomes lesson candidates in the registry, idempotently.

A retro is docs/units/<unit>/retro.md, or the PR comment titled lessons.retro_comment_title. Its lessons section
(lessons.ingest_section, "## 5. ...") is a numbered list; each item is one lesson, ref L<n>, with its owner from the
"Owner: ..." clause. Class, kind and signals come from the registry keyword lists, never from code. An item whose
(unit, ref, retro) is already in the registry is left alone, so reading the same retro twice changes nothing and an edited
retro never duplicates a lesson.

  parse(text, unit, source)       [candidate] of one retro text
  ingest(root, candidates, ...)   [(id, 'created' | 'exists')]
  retro_files(root)               the retros under lessons.ingest_glob
"""
import re
from pathlib import Path

import config
import lessons

HEADING = re.compile(r'^##\s+(\d+)\.\s+(.*?)\s*$')
ITEM = re.compile(r'^(\d+)\.\s+(.*\S)\s*$')
OWNER = re.compile(r'[Oo]wner:?\s*([^.)\n]+)')
MARKUP = re.compile(r'\*{1,2}')


def setting(name):
    return config.get(f'lessons.{name}')


def keyword_map(name):
    """{key: [keyword]} of a 'key=kw,kw' registry list, in order."""
    found = {}
    for entry in setting(name):
        key, words = entry.split('=', 1)
        found[key] = [word.strip().lower() for word in words.split(',') if word.strip()]
    return found


def first_match(text, name, default):
    low = text.lower()
    for key, words in keyword_map(name).items():
        if any(re.search(r'\b' + re.escape(word), low) for word in words):
            return key
    return default


def owner_of(text):
    """The canonical owner from the last 'Owner: ...' clause (aliases are lessons.owner_aliases), else the default."""
    clauses = OWNER.findall(text)
    if not clauses:
        return setting('unknown_owner')
    spoken = clauses[-1].lower()
    for alias in setting('owner_aliases'):
        phrase, owner = alias.split('=', 1)
        if phrase in spoken:
            return owner
    return setting('unknown_owner')


def title_of(text):
    plain = MARKUP.sub('', text)
    plain = re.split(r';| \(|\. ', plain, maxsplit=1)[0].strip().rstrip('.:')
    limit = setting('title_max_chars')
    if len(plain) > limit:
        plain = plain[:limit].rsplit(' ', 1)[0]
    return plain.rstrip(' ,')


def signals_of(cls):
    found = []
    for entry in setting('signal_map'):
        key, spec = entry.split('=', 1)
        if key == cls:
            event, stage, pattern = (spec.split('|') + ['', ''])[:3]
            found.append({'event': event, 'stage': stage or None, 'pattern': pattern or None})
    return found


def items(text):
    """[(section number, item number, item text)] of the numbered items of the lessons section."""
    found, section, current = [], None, None
    for line in text.splitlines():
        heading = HEADING.match(line)
        if heading or line.startswith('## '):
            section = int(heading.group(1)) if heading else None
            current = None
            continue
        if section != setting('ingest_section'):
            continue
        item = ITEM.match(line)
        if item:
            current = [section, int(item.group(1)), item.group(2)]
            found.append(current)
        elif current is not None and line.strip():
            current[2] += ' ' + line.strip()
        elif not line.strip():
            current = None
    return [tuple(entry) for entry in found]


def parse(text, unit, source):
    """The lesson candidates of one retro text: keyword arguments of lessons.add."""
    found = []
    for section, number, body in items(text):
        cls = first_match(body, 'class_keywords', setting('default_class'))
        found.append({'title': title_of(body), 'unit': unit, 'retro': source, 'section': section, 'ref': f'L{number}',
                      'cls': cls, 'kind': first_match(body, 'kind_keywords', setting('default_kind')),
                      'change': MARKUP.sub('', body), 'owner': owner_of(body),
                      'area': list(dict.fromkeys(re.findall(setting('area_path_pattern'), body))), 'signals': signals_of(cls)})
    return found


def retro_files(root):
    return sorted(Path(root).glob(setting('ingest_glob')))


def candidates_of_files(root, files=None):
    found = []
    for path in files or retro_files(root):
        path = Path(path)
        found += parse(path.read_text(encoding='utf-8'), path.parent.name, path.resolve().relative_to(Path(root).resolve()).as_posix())
    return found


def comment_text(comments):
    """The body of the newest PR comment whose first line is lessons.retro_comment_title, else None."""
    for comment in reversed(comments):
        body = comment.get('body') or ''
        if body.strip().splitlines() and MARKUP.sub('', body.strip().splitlines()[0]).lstrip('# ').strip().startswith(setting('retro_comment_title')):
            return body
    return None


def known(records, candidate):
    return next((r['id'] for r in records.values()
                 if (r['source']['unit'], r['source']['ref'], r['source']['retro']) == (candidate['unit'], candidate['ref'], candidate['retro'])), None)


def ingest(root, candidates, by=None, clock=None, port=None):
    """[(lesson id, 'created' | 'exists')]; a candidate whose (unit, ref, retro) is registered is not touched."""
    done = []
    for candidate in candidates:
        existing = known(lessons.load(root)[0], candidate)
        if existing:
            done.append((existing, 'exists'))
            continue
        record, outcome = lessons.add(root, candidate['title'], candidate['unit'], candidate['retro'], candidate['section'], candidate['ref'],
                                      candidate['cls'], candidate['kind'], candidate['change'], candidate['owner'], candidate['area'],
                                      candidate['signals'], by or setting('ingest_by'), clock, port)
        done.append((record['id'], outcome))
    return done

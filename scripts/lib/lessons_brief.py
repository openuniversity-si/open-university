"""The brief feedback query (LR1, D-069 items 4 and 9): the applied lessons relevant to a unit's area.

A launch brief gives a unit the lessons the engine already learned about the files it will touch. This module only
answers the query; putting the answer into the brief is the launch tool's job (CO1). A lesson names the files it is
about in `area` (paths or globs); an area-less applied lesson applies to every unit and follows the matches.

  matches(area, path)        whether a lesson area entry covers a path (glob either way, or a directory prefix)
  for_area(records, paths)   [lesson] relevant to those paths: area matches first, then general ones, at most lessons.brief_limit
  render(found)              the lines a brief carries, one per lesson
  brief_lines(root, paths)   the lines of the next launch brief for those paths, read from the register (LP7: a lesson the
                             planner just applied is in them, with no restart)
"""
from fnmatch import fnmatch

import config


def setting(name):
    return config.get(f'lessons.{name}')


def matches(area, path):
    """True when the lesson area entry and the unit path overlap."""
    area, path = area.rstrip('/'), path.rstrip('/')
    return (fnmatch(path, area) or fnmatch(area, path) or path.startswith(area + '/') or area.startswith(path + '/'))


def for_area(records, paths):
    allowed = setting('brief_statuses')
    live = sorted((r for r in records.values() if r['status'] in allowed), key=lambda r: r['id'])
    specific = [r for r in live if r['area'] and any(matches(entry, path) for entry in r['area'] for path in paths)]
    general = [r for r in live if not r['area']] if setting('brief_general') else []
    return (specific + general)[:setting('brief_limit')]


def render(found):
    return [f'{record["id"]} [{record["kind"]}] {record["change"]} (owner: {record["owner"]}, from {record["source"]["unit"]})' for record in found]


def brief_lines(root, paths):
    import lessons  # lessons imports this module for its CLI
    records, _ = lessons.load(root)
    return render(for_area(records, paths))

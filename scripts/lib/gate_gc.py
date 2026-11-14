"""Gate hygiene (GX-19, D-070): the per-stage time limit and the retention of report directories and build entries.

  gate_gc.py limits <stage>                           tab-separated: seconds the stage may run, the TERM-to-KILL grace,
                                                      the exit status of an overrun, the log lines to print
  gate_gc.py collect --reports DIR --build-cache DIR [--report-only] [--live-sha SHA] [--lock FILE]
                                                      remove what the keep bounds leave out; prints what it removed

Reports live at DIR/<sha>/<mode>-<timestamp>; the newest gate-gc.reports_keep per (sha, mode) stay, and of the sha
directories the newest gate-gc.reports_shas_keep stay (gate-gc.report_only_shas_keep with --report-only): every push
adds a sha, so a bound per key alone never bounds the folder (GATE-GC-CHEIO). The folder bound never removes a live sha
(D-069 item 4): the one the calling gate writes (--live-sha), one a held --lock names, or one a live process holds open
(a descriptor or working directory under it, read from gate-gc.proc_dir where it exists); nor a sha directory at least
as recent as the newest one a gate writes, or touched since the collection began. Build entries live
at DIR/<target>-<64 hex key>; the most recently used gate-gc.build_cache_keep per target stay. Anything else in either
directory is not ours and is left alone, except the aside copies gate-build.py leaves when it replaces an entry.
"""
import argparse
import fcntl
import os
from pathlib import Path
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402

SHA = re.compile(r'^[0-9a-f]{40}$')
NAMED_SHA = re.compile(r'\b[0-9a-f]{40}\b')
REPORT = re.compile(r'^(?P<mode>.+)-\d{8}T\d{6}$')
ENTRY = re.compile(r'^(?P<target>.+)-[0-9a-f]{64}$')
ASIDE_PREFIX = '.replaced-'
DEFAULT_STAGE = '*'


def stage_timeout(stage, limits=None):
    """Seconds `stage` may run: its own entry, else the `*` entry."""
    limits = config.get('gate-gc.stage_timeout_s') if limits is None else limits
    by_stage = {row['stage']: row['timeout_s'] for row in limits}
    return by_stage.get(stage, by_stage[DEFAULT_STAGE])


def _newest(paths, keep):
    """The paths beyond the `keep` most recently modified (names break ties, so the order is stable)."""
    ranked = sorted(paths, key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
    return ranked[keep:]


def _remove(path, removed):
    shutil.rmtree(path, ignore_errors=True)
    removed.append(path)


def collect_reports(reports, keep):
    removed = []
    if not reports.is_dir():
        return removed
    for sha_dir in (p for p in reports.iterdir() if p.is_dir() and SHA.match(p.name)):
        by_mode = {}
        for run in (p for p in sha_dir.iterdir() if p.is_dir() and not p.is_symlink()):
            match = REPORT.match(run.name)
            if match:
                by_mode.setdefault(match['mode'], []).append(run)
        for runs in by_mode.values():
            for run in _newest(runs, keep):
                _remove(run, removed)
    return removed


def _recency(sha_dir):
    """The newest mtime of the sha's runs (its own when it has none): a run still being written keeps its sha recent,
    and the per-(sha, mode) removal, which touches only the sha directory itself, never makes an old sha look new."""
    try:
        runs = [run.stat().st_mtime for run in sha_dir.iterdir() if run.is_dir() and not run.is_symlink()]
        return max(runs) if runs else sha_dir.stat().st_mtime
    except OSError:  # removed or replaced under us: rank it newest, so it is never the one removed
        return float('inf')


def held_lock_shas(lock):
    """The shas `lock` names while a live gate holds it (flock); a lock nobody holds, or one naming none, protects none."""
    try:
        with open(lock) as handle:
            named = set(NAMED_SHA.findall(handle.read()))
            if not named:
                return set()
            try:
                fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return named
            fcntl.flock(handle, fcntl.LOCK_UN)
            return set()
    except (OSError, TypeError):
        return set()


def held_open_shas(reports, proc=None):
    """The sha directories of `reports` a live process holds: an open descriptor or a working directory under one."""
    proc = Path(config.get('gate-gc.proc_dir')) if proc is None else Path(proc)
    prefix = str(Path(reports).resolve()) + os.sep
    held = set()
    try:
        pids = [p for p in proc.iterdir() if p.name.isdigit()]
    except OSError:  # no process table (not Linux): nothing is known to be held
        return held
    for pid in pids:
        try:
            links = [pid / 'cwd', *(pid / 'fd').iterdir()]
        except OSError:  # gone, or another user's
            continue
        for link in links:
            try:
                target = os.readlink(link)
            except OSError:
                continue
            if target.startswith(prefix):
                name = target[len(prefix):].split(os.sep, 1)[0]
                if SHA.match(name):
                    held.add(name)
    return held


def collect_shas(reports, keep, writing=(), lock=None, proc=None):
    """The folder bound: the sha directories beyond the `keep` most recent are removed whole, never a live one."""
    removed = []
    if not reports.is_dir():
        return removed
    began = time.time()
    shas = [p for p in reports.iterdir() if p.is_dir() and not p.is_symlink() and SHA.match(p.name)]
    writing = set(writing) | held_lock_shas(lock)
    live = writing | held_open_shas(reports, proc)
    written = [_recency(p) for p in shas if p.name in writing]
    floor = min(began, max(written)) if written else began
    for sha_dir in sorted(shas, key=lambda p: (_recency(p), p.name), reverse=True)[keep:]:
        if sha_dir.name not in live and _recency(sha_dir) < floor:  # read again: a run may have begun since the sort
            _remove(sha_dir, removed)
    return removed


def collect_build_cache(cache, keep):
    removed = []
    if not cache.is_dir():
        return removed
    by_target = {}
    for entry in (p for p in cache.iterdir() if p.is_dir() and not p.is_symlink()):
        if entry.name.startswith(ASIDE_PREFIX):
            _remove(entry, removed)
            continue
        match = ENTRY.match(entry.name)
        if match:
            by_target.setdefault(match['target'], []).append(entry)
    for entries in by_target.values():
        for entry in _newest(entries, keep):
            _remove(entry, removed)
    return removed


def collect(reports, cache, report_only=False, writing=(), lock=None):
    removed = []
    if reports:
        removed += collect_reports(Path(reports), config.get('gate-gc.reports_keep'))
        shas_keep = config.get('gate-gc.report_only_shas_keep' if report_only else 'gate-gc.reports_shas_keep')
        removed += collect_shas(Path(reports), shas_keep, writing, lock)
    if cache:
        removed += collect_build_cache(Path(cache), config.get('gate-gc.build_cache_keep'))
    return removed


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('limits').add_argument('stage')
    gather = sub.add_parser('collect')
    gather.add_argument('--reports')
    gather.add_argument('--build-cache')
    gather.add_argument('--report-only', action='store_true', help='the reports are the advisory run\'s (its own bound)')
    gather.add_argument('--live-sha', action='append', default=[], help='a sha the calling gate is writing')
    gather.add_argument('--lock', help='the gate lock; the shas it names are live while it is held')
    args = parser.parse_args(argv)
    if args.command == 'limits':
        print('\t'.join(str(value) for value in (stage_timeout(args.stage), config.get('gate-gc.kill_grace_s'),
                                                config.get('gate-gc.timeout_exit_code'), config.get('gate-gc.log_tail_lines'))))
        return 0
    for path in collect(args.reports, args.build_cache, args.report_only, args.live_sha, args.lock):
        print(f'gate-gc: removed {path}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

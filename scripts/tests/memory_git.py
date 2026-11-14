"""GATE-SPEED F11 (D-133, N6): git in memory for the tests whose subject is not git.

A MemoryGit answers `git -C <repo> <command> ...` for the repositories it created, as a CompletedProcess, without a
process: one object store (blobs, flat trees, commits) shared by every repository it holds, refs per repository, and
each repository's working tree on disk (a test writes files there; `add` reads them, `checkout` writes them). It knows
the commands the train's fixture, its fake forge and the train's workspace use; any other command raises
UnknownCommand, so a test never runs on a half-answered git. `intercept()` routes subprocess.run calls for its
repositories to it and leaves every other process alone.

Merges are three-way per path, and line by line inside a file both sides changed (difflib): disjoint edits merge,
overlapping ones conflict, as git's merge-tree does for the trees these tests build. A fatal error exits -1.
"""
import contextlib
import datetime
import difflib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

FATAL = -1
ZERO = '0' * len(hashlib.sha1().hexdigest())
HEX = re.compile(r'^[0-9a-f]{40}$')
# the fixture's first commit time; each later commit one second on (dates are deterministic)
EPOCH = int(datetime.datetime.fromisoformat('2026-10-31T00:00:00+00:00').timestamp())


class UnknownCommand(RuntimeError):
    pass


class Failed(Exception):
    def __init__(self, message, code=FATAL):
        super().__init__(message)
        self.code = code


def _sha(kind, data):
    return hashlib.sha1(f'{kind} {len(data)}\0'.encode() + data).hexdigest()


class Repo:
    def __init__(self, path, bare):
        self.path, self.bare = Path(path), bare
        self.refs, self.head, self.index, self.remotes = {}, 'refs/heads/master', None, {}

    def files_on_disk(self):
        """Every file of the worktree with its bytes, read each time. A stat key says nothing of a same-size rewrite
        in one coarse tick of the file system's clock: on the runner's disk (04/11) the fixture's commit kept the old
        bytes of a rewritten file, and train-role's ownership tests saw no change to refuse."""
        found, top = {}, str(self.path)
        for folder, names, files in os.walk(top):
            names[:] = [name for name in names if not (folder == top and name == '.git')]
            prefix = os.path.relpath(folder, top).replace(os.sep, '/')
            for name in files:
                if folder == top and name == '.git':
                    continue
                path, relative = os.path.join(folder, name), name if prefix == '.' else f'{prefix}/{name}'
                with open(path, 'rb') as handle:
                    found[relative] = handle.read()
        return found


class MemoryGit:
    def __init__(self):
        self.blobs, self.trees, self.commits, self.repos, self.indexes = {}, {}, {}, {}, {}
        self.clock = EPOCH

    # --- objects -------------------------------------------------------------------------------------------------
    def blob(self, data):
        key = _sha('blob', data)
        self.blobs[key] = data
        return key

    def tree(self, files):
        """A flat tree {path: blob id} from {path: bytes}."""
        entries = {path: self.blob(data) for path, data in files.items()}
        return self.tree_of(entries)

    def tree_of(self, entries):
        key = _sha('tree', json.dumps(sorted(entries.items())).encode())
        self.trees[key] = dict(entries)
        return key

    def commit(self, tree, parents, message, when=None, raw=False):
        if when is None:
            self.clock += 1
            when = self.clock
        record = {'tree': tree, 'parents': list(parents), 'message': message, 'time': int(when)}
        if raw:
            record['raw'] = True  # the message came from stdin: git stores it as it is, -m adds the newline
        key = _sha('commit', json.dumps(record, sort_keys=True).encode())
        self.commits[key] = record
        return key

    def files(self, commit):
        return {path: self.blobs[blob] for path, blob in self.trees[self.commits[commit]['tree']].items()}

    # --- repositories ----------------------------------------------------------------------------------------------
    def repo(self, where):
        found = self.repos.get(str(Path(where).resolve()))
        if found is None:
            raise Failed(f'fatal: not a git repository: {where}')
        return found

    def owns(self, where):
        return where is not None and str(Path(where).resolve()) in self.repos

    def init(self, path, bare=False, branch=None):
        Path(path).mkdir(parents=True, exist_ok=True)
        made = Repo(Path(path).resolve(), bare)
        if branch:
            made.head = f'refs/heads/{branch}'
        self.repos[str(made.path)] = made
        return made

    # --- revisions -----------------------------------------------------------------------------------------------
    def head_commit(self, repo):
        return repo.head if HEX.match(repo.head) else repo.refs.get(repo.head)

    def resolve(self, repo, expression):
        """A revision expression to an object id: a sha, HEAD, a ref, a branch, a remote branch, with ^{commit},
        ^{tree}, ^N, ~N and :path."""
        if ':' in expression:
            commit, path = expression.split(':', 1)
            files = self.trees[self.commits[self.resolve(repo, commit)]['tree']]
            if path not in files:
                raise Failed(f'fatal: path {path!r} does not exist in {commit!r}')
            return files[path]
        match = re.match(r'^(.*?)((?:\^\{(?:commit|tree)\}|\^\d*|~\d+)*)$', expression)
        name, suffix = match.groups()
        sha = self._name(repo, name)
        for part in re.findall(r'\^\{commit\}|\^\{tree\}|\^\d*|~\d+', suffix):
            if part == '^{commit}':
                if sha not in self.commits:
                    raise Failed(f'fatal: {expression} is not a commit')
            elif part == '^{tree}':
                sha = self.commits[sha]['tree'] if sha in self.commits else sha
            elif part.startswith('^'):
                number = int(part[1:] or 1)
                parents = self.commits[sha]['parents']
                if number > len(parents):
                    raise Failed(f'fatal: {expression}: no such parent')
                sha = parents[number - 1]
            else:
                for _ in range(int(part[1:])):
                    sha = self.commits[sha]['parents'][0]
        return sha

    def _name(self, repo, name):
        if HEX.match(name) and (name in self.commits or name in self.trees or name in self.blobs):
            return name
        if name == 'HEAD':
            found = self.head_commit(repo)
        else:
            found = next((repo.refs[ref] for ref in (name, f'refs/heads/{name}', f'refs/remotes/{name}', f'refs/{name}')
                          if ref in repo.refs), None)
        if not found:
            raise Failed(f"fatal: ambiguous argument '{name}': unknown revision")
        return found

    def ancestors(self, sha, first_parent=False):
        seen, order, todo = set(), [], [sha]
        while todo:
            current = todo.pop(0)
            if current in seen:
                continue
            seen.add(current)
            order.append(current)
            parents = self.commits[current]['parents']
            todo.extend(parents[:1] if first_parent else parents)
        return order

    def merge_base(self, left, right):
        mine = self.ancestors(left)
        theirs = set(self.ancestors(right))
        common = [sha for sha in mine if sha in theirs]
        best = [sha for sha in common if not any(sha != other and sha in self.ancestors(other) for other in common)]
        return best[0] if best else None

    # --- merges --------------------------------------------------------------------------------------------------
    def merge_trees(self, onto, head):
        """(tree id, conflicted paths) of a three-way merge of two commits at their merge base."""
        base = self.merge_base(onto, head)
        old = self.trees[self.commits[base]['tree']] if base else {}
        ours, theirs = self.trees[self.commits[onto]['tree']], self.trees[self.commits[head]['tree']]
        merged, conflicted = {}, []
        for path in sorted(set(old) | set(ours) | set(theirs)):
            o, a, b = old.get(path), ours.get(path), theirs.get(path)
            if a == b:
                chosen = a
            elif a == o:
                chosen = b
            elif b == o:
                chosen = a
            elif a and b:
                text = self._merge_lines(o, a, b)
                if text is None:
                    conflicted.append(path)
                    chosen = a
                else:
                    chosen = self.blob(text)
            else:
                conflicted.append(path)
                chosen = a or b
            if chosen:
                merged[path] = chosen
        return self.tree_of(merged), conflicted

    def _merge_lines(self, base, ours, theirs):
        """The merged bytes when the two sides changed disjoint line ranges of the base, else None."""
        old = self.blobs[base].decode(errors='surrogateescape').splitlines(keepends=True) if base else []
        a = self.blobs[ours].decode(errors='surrogateescape').splitlines(keepends=True)
        b = self.blobs[theirs].decode(errors='surrogateescape').splitlines(keepends=True)
        edits = []
        for side, lines in ((0, a), (1, b)):
            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, lines, autojunk=False).get_opcodes():
                if tag != 'equal':
                    edits.append((i1, i2, side, lines[j1:j2]))
        edits.sort(key=lambda edit: (edit[0], edit[1]))
        for first, second in zip(edits, edits[1:]):
            (start, end, side), (next_start, _, next_side) = first[:-1], second[:-1]
            if side != next_side and next_start <= end:
                return None
        out, at = [], 0
        for i1, i2, _side, lines in edits:
            out += old[at:i1] + lines
            at = max(at, i2)
        out += old[at:]
        return ''.join(out).encode(errors='surrogateescape')

    # --- the command line ------------------------------------------------------------------------------------------
    def run(self, args, cwd=None, input=None, env=None):
        """`git <args>` as subprocess.run would return it (text)."""
        args = list(args)
        where = cwd
        while args and args[0] in ('-C', '-c'):
            if args[0] == '-C':
                where = args[1] if where is None or Path(args[1]).is_absolute() else str(Path(where) / args[1])
            args = args[len(('-C', 'path')):]
        try:
            out = self._command(where, args, input or '', dict(env or {}))
            return subprocess.CompletedProcess(['git', *args], 0, out if isinstance(out, str) else '', '')
        except Failed as failure:
            return subprocess.CompletedProcess(['git', *args], failure.code, getattr(failure, 'out', ''), f'{failure}\n')

    def _command(self, where, args, stdin, env):
        command, rest = args[0], args[1:]
        options = [arg for arg in rest if arg.startswith('-')]
        plain = [arg for arg in rest if not arg.startswith('-')]
        handler = getattr(self, '_git_' + command.replace('-', '_'), None)
        if handler is None:
            raise UnknownCommand(f'memory git does not know `git {" ".join(args)}`')
        return handler(where, rest, options, plain, stdin, env)

    def _when(self, env, key):
        value = env.get(key)
        return int(value.split()[0]) if value else None

    def _git_init(self, where, rest, options, plain, stdin, env):
        branch = rest[rest.index('-b') + 1] if '-b' in rest else None
        named = [arg for index, arg in enumerate(rest) if not arg.startswith('-') and rest[index - 1:index] != ['-b']]
        target = Path(where or '.') / named[-1] if named else Path(where)
        self.init(target, bare='--bare' in options, branch=branch)
        return ''

    def _git_config(self, where, rest, options, plain, stdin, env):
        return ''

    def _git_symbolic_ref(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        repo.head = plain[1]
        return ''

    def _git_clone(self, where, rest, options, plain, stdin, env):
        source = self.repo(Path(where or '.') / plain[0] if not Path(plain[0]).is_absolute() else plain[0])
        target = self.init(Path(where or '.') / plain[1] if not Path(plain[1]).is_absolute() else plain[1])
        target.remotes['origin'] = str(source.path)
        for ref, sha in source.refs.items():
            if ref.startswith('refs/heads/'):
                target.refs[f'refs/remotes/origin/{ref[len("refs/heads/"):]}'] = sha
        target.head = source.head if not HEX.match(source.head) else source.head
        if source.head in source.refs:
            target.refs[source.head] = source.refs[source.head]
            if '--no-checkout' not in options:
                self._write_tree(target, source.refs[source.head])
        return ''

    def _git_remote(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        if plain[:1] == ['get-url']:
            return repo.remotes.get(plain[1], plain[1]) + '\n'
        if plain[:1] == ['add']:
            _add, name, url = plain
            repo.remotes[name] = url
            return ''
        raise UnknownCommand(f'memory git: remote {rest}')

    def _git_add(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        repo.index = repo.files_on_disk()
        return ''

    def _git_commit(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        flag = next(arg for arg in rest if arg == '-m' or arg == '-am')
        message = rest[rest.index(flag) + 1]
        parent = self.head_commit(repo)
        if '-a' in options or flag == '-am':  # every tracked file as it is on disk; an untracked one stays out
            disk, tracked = repo.files_on_disk(), repo.index if repo.index is not None else {}
            repo.index = {path: disk[path] for path in tracked if path in disk}
        elif repo.index is None:
            repo.index = repo.files_on_disk()
        sha = self.commit(self.tree(repo.index), [parent] if parent else [], message,
                          self._when(env, 'GIT_COMMITTER_DATE'))
        self._move_head(repo, sha)
        return ''

    def _move_head(self, repo, sha):
        if HEX.match(repo.head):
            repo.head = sha
        else:
            repo.refs[repo.head] = sha

    def _write_tree(self, repo, sha):
        """The commit's files as the repository's working tree and index."""
        files = self.files(sha)
        if not repo.bare:
            disk, tracked = repo.files_on_disk(), repo.index or {}
            for path in disk:
                if path in tracked and path not in files:  # an untracked file stays, as git leaves it
                    os.unlink(os.path.join(repo.path, path))
            for path, data in files.items():
                if disk.get(path) != data:
                    target = os.path.join(repo.path, path)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with open(target, 'wb') as handle:
                        handle.write(data)
        repo.index = files

    def _git_checkout(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        if '-B' in rest or '-b' in rest:
            flag = '-B' if '-B' in rest else '-b'
            name = rest[rest.index(flag) + 1]
            start = [arg for arg in plain if arg != name]
            sha = self.resolve(repo, start[0]) if start else self.head_commit(repo)
            repo.refs[f'refs/heads/{name}'] = sha
            repo.head = f'refs/heads/{name}'
        elif '--detach' in options:
            sha = self.resolve(repo, plain[0])
            repo.head = sha
        else:
            name = plain[0]
            if f'refs/heads/{name}' in repo.refs:
                repo.head, sha = f'refs/heads/{name}', repo.refs[f'refs/heads/{name}']
            else:
                sha = self.resolve(repo, name)
                repo.head = sha
        self._write_tree(repo, sha)
        return ''

    def _remote(self, repo, name):
        target = Path(repo.remotes.get(name, name))
        return self.repo(target if target.is_absolute() else repo.path / target)

    def _git_push(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        remote = self._remote(repo, plain[0])
        lines = []
        for spec in plain[1:]:
            force = spec.startswith('+') or '--force' in options or '-f' in options
            source, _, target = spec.lstrip('+').partition(':')
            target = target or source
            target = target if target.startswith('refs/') else f'refs/heads/{target}'
            sha = self.resolve(repo, source)
            old = remote.refs.get(target)
            if old and not force and old not in self.ancestors(sha):
                if '--porcelain' in options:
                    return f'!\t{source}:{target}\t[rejected] (non-fast-forward)\nDone\n'
                raise Failed(f' ! [rejected] {source} -> {target} (non-fast-forward)', 1)
            remote.refs[target] = sha
            lines.append(f'{"*" if not old else " "}\t{source}:{target}\t{"[new branch]" if not old else _short(old) + ".." + _short(sha)}')
        return ('\n'.join(lines) + '\nDone\n') if '--porcelain' in options else ''

    def _git_fetch(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        remote = self._remote(repo, plain[0])
        for spec in plain[1:]:
            source, _, target = spec.lstrip('+').partition(':')
            if HEX.match(source) and not target:
                if source not in self.commits:
                    raise Failed(f'fatal: remote error: upload-pack: not our ref {source}', 1)
                continue
            full = source if source.startswith('refs/') else f'refs/heads/{source}'
            if full not in remote.refs:
                raise Failed(f"fatal: couldn't find remote ref {source}", 1)
            repo.refs[target if target else 'FETCH_HEAD'] = remote.refs[full]
        return ''

    def _git_update_ref(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        if '-d' in options:
            repo.refs.pop(plain[0], None)
            return ''
        ref, new = plain[0], self.resolve(repo, plain[1])
        if len(plain) > 1 + 1 and repo.refs.get(ref, ZERO) != (self.resolve(repo, plain[1 + 1]) if plain[1 + 1] != ZERO else ZERO):
            raise Failed(f'fatal: update_ref failed for ref {ref!r}: cannot lock ref', 1)
        repo.refs[ref] = new
        return ''

    def _git_rev_parse(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        return ''.join(self.resolve(repo, expression) + '\n' for expression in plain)

    def _git_merge_tree(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        tree, conflicted = self.merge_trees(self.resolve(repo, plain[0]), self.resolve(repo, plain[1]))
        out = tree + '\n' + ''.join(f'{path}\n' for path in conflicted)
        if conflicted:
            raise _Output(out, 1)
        return out

    def _git_commit_tree(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        parents, message, index, from_file = [], None, 0, False  # no -m and no -F: git reads the message from stdin
        tree = None
        while index < len(rest):
            arg = rest[index]
            if arg == '-p':
                parents.append(self.resolve(repo, rest[index + 1]))
                index += 1 + 1
            elif arg == '-m':
                message = rest[index + 1]
                index += 1 + 1
            elif arg == '-F':
                message = stdin if rest[index + 1] == '-' else Path(rest[index + 1]).read_text()
                from_file = True
                index += 1 + 1
            else:
                tree = self.resolve(repo, arg)
                index += 1
        return self.commit(tree, parents, stdin if message is None else message, self._when(env, 'GIT_COMMITTER_DATE'),
                           raw=message is None or from_file) + '\n'

    def _git_ls_tree(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        sha = self.resolve(repo, plain[-1])
        tree = self.trees[self.commits[sha]['tree'] if sha in self.commits else sha]
        names = sorted(tree) if '-r' in options else sorted({path.split('/')[0] for path in tree})
        end = '\0' if '-z' in options else '\n'
        return ''.join(f'{name}{end}' for name in names)

    def _format(self, sha, pattern):
        record = self.commits[sha]
        return (pattern.replace('%ct', str(record['time'])).replace('%B', record['message'] + ('' if record.get('raw') else '\n'))
                .replace('%H', sha).replace('%T', record['tree']).replace('%P', ' '.join(record['parents'])))

    def _git_show(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        fmt = next((arg.split('=', 1)[1] for arg in options if arg.startswith('--format=') or arg.startswith('--pretty=')), None)
        out = []
        for expression in plain:
            if ':' in expression and fmt is None:
                out.append(self.blobs[self.resolve(repo, expression)].decode(errors='surrogateescape'))
            else:
                out.append(self._format(self.resolve(repo, expression), fmt or '%H') + '\n')
        return ''.join(out)

    def _git_log(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        fmt = next((arg.split('=', 1)[1] for arg in options if arg.startswith('--format=') or arg.startswith('--pretty=')), '%H')
        limit = int(rest[rest.index('-n') + 1]) if '-n' in rest else (1 if '-1' in options else None)
        shas = self.ancestors(self.resolve(repo, plain[0] if plain else 'HEAD'))
        shas = shas[:limit] if limit else shas
        return ''.join(self._format(sha, fmt) + '\n' for sha in shas)

    def _git_rev_list(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        first = '--first-parent' in options
        spec = [arg for arg in plain if arg != rest[rest.index('-n') + 1]] if '-n' in rest else plain
        if '..' in spec[0]:
            left, right = spec[0].split('..', 1)
            excluded = set(self.ancestors(self.resolve(repo, left)))
            shas = [sha for sha in self.ancestors(self.resolve(repo, right), first) if sha not in excluded]
        else:
            shas = self.ancestors(self.resolve(repo, spec[0]), first)
        if '-n' in rest:
            shas = shas[:int(rest[rest.index('-n') + 1])]
        if '--count' in options:
            return f'{len(shas)}\n'
        if '--parents' in options:
            return ''.join(' '.join([sha, *self.commits[sha]['parents']]) + '\n' for sha in shas)
        return ''.join(f'{sha}\n' for sha in (reversed(shas) if '--reverse' in options else shas))

    def _git_merge_base(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        left, right = self.resolve(repo, plain[0]), self.resolve(repo, plain[1])
        if '--is-ancestor' in options:
            if left not in self.ancestors(right):
                raise Failed('', 1)
            return ''
        found = self.merge_base(left, right)
        if not found:
            raise Failed('', 1)
        return found + '\n'

    def _git_diff(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        if '...' in plain[0]:
            left, right = plain[0].split('...', 1)
            right = self.resolve(repo, right)
            left = self.merge_base(self.resolve(repo, left), right)
        else:
            left, right = self.resolve(repo, plain[0]), self.resolve(repo, plain[1])
        old, new = self.trees[self.commits[left]['tree']], self.trees[self.commits[right]['tree']]
        end = '\0' if '-z' in options else '\n'
        return ''.join(f'{path}{end}' for path in sorted(set(old) | set(new)) if old.get(path) != new.get(path))

    def _git_cat_file(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        if '-e' in options:
            try:
                self.resolve(repo, plain[0])
            except (Failed, KeyError):
                raise Failed('', 1)
            return ''
        batch = next((arg for arg in options if arg.startswith('--batch')), None)
        if batch is None:
            raise UnknownCommand(f'memory git: cat-file {rest}')
        out = []
        for line in stdin.splitlines():
            try:
                sha = self.resolve(repo, line.strip())
            except (Failed, KeyError):
                out.append(f'{line.strip()} missing\n')
                continue
            if batch.startswith('--batch-check'):
                out.append(f'{sha}\n')
            else:
                data = self.blobs[sha].decode(errors='surrogateescape')
                out.append(f'{sha} blob {len(self.blobs[sha])}\n{data}\n')
        return ''.join(out)

    def _git_worktree(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        if plain[0] == 'add':
            target = self.init(plain[1])
            target.refs = repo.refs
            sha = self.resolve(repo, plain[1 + 1])
            target.head = sha
            self._write_tree(target, sha)
            return ''
        if plain[0] == 'remove':
            self.repos.pop(str(Path(plain[1]).resolve()), None)
            shutil.rmtree(plain[1], ignore_errors=True)
            return ''
        raise UnknownCommand(f'memory git: worktree {rest}')

    def _index(self, repo, env):
        """The index a command reads and writes: GIT_INDEX_FILE's when set (blob ids by path), else the repository's."""
        named = env.get('GIT_INDEX_FILE')
        if named:
            Path(named).touch()  # git writes the index file; its caller removes it
            return self.indexes.setdefault(named, {})
        return {path: self.blob(data) for path, data in
                (repo.index if repo.index is not None else repo.files_on_disk()).items()}

    def _git_write_tree(self, where, rest, options, plain, stdin, env):
        return self.tree_of(self._index(self.repo(where), env)) + '\n'

    def _git_read_tree(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        sha = self.resolve(repo, plain[0])
        Path(env['GIT_INDEX_FILE']).touch()
        self.indexes[env['GIT_INDEX_FILE']] = dict(self.trees[self.commits[sha]['tree'] if sha in self.commits else sha])
        return ''

    def _git_update_index(self, where, rest, options, plain, stdin, env):
        index = self._index(self.repo(where), env)
        for mode_blob_path in plain:
            _mode, _, blob_path = mode_blob_path.partition(',')
            blob, _, path = blob_path.partition(',')
            index[path] = blob
        return ''

    def _git_mktree(self, where, rest, options, plain, stdin, env):
        """A flat tree from `<mode> blob <id>\\t<path>` lines."""
        self.repo(where)
        entries = {}
        for line in stdin.splitlines():
            head, _, path = line.partition('\t')
            entries[path] = head.split()[-1]
        return self.tree_of(entries) + '\n'

    def _git_hash_object(self, where, rest, options, plain, stdin, env):
        self.repo(where)
        return self.blob(stdin.encode(errors='surrogateescape')) + '\n'

    def _git_archive(self, where, rest, options, plain, stdin, env):
        """A tar of the commit's files (bytes carried as surrogate-escaped text)."""
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w') as archive:
            for path, data in sorted(self.files(self.resolve(self.repo(where), plain[0])).items()):
                info = tarfile.TarInfo(path)
                info.size = len(data)  # TarInfo's default mode, 0644
                archive.addfile(info, io.BytesIO(data))
        return buffer.getvalue().decode(errors='surrogateescape')

    def _git_status(self, where, rest, options, plain, stdin, env):
        """`--porcelain`: the working tree against HEAD, modified (` M`), deleted (` D`) and untracked (`??`)."""
        repo = self.repo(where)
        head = self.files(self.head_commit(repo)) if self.head_commit(repo) else {}
        disk = repo.files_on_disk()
        lines = []
        for path in sorted(set(head) | set(disk)):
            if path not in disk:
                lines.append(f' D {path}')
            elif path not in head:
                lines.append(f'?? {path}')
            elif head[path] != disk[path]:
                lines.append(f' M {path}')
        return ''.join(f'{line}\n' for line in lines)

    def _git_for_each_ref(self, where, rest, options, plain, stdin, env):
        repo = self.repo(where)
        prefix = plain[0] if plain else ''
        return ''.join(f'{sha}\n' for ref, sha in sorted(repo.refs.items()) if ref.startswith(prefix))

    # --- interception ------------------------------------------------------------------------------------------------
    @contextlib.contextmanager
    def intercept(self):
        """subprocess.run of `git` for a repository this MemoryGit holds is answered here; every other call runs."""
        real = subprocess.run

        def run(command, *args, **kwargs):
            if isinstance(command, (list, tuple)) and command and Path(str(command[0])).name == 'git':
                where = self._where(list(command[1:]), kwargs.get('cwd'))
                if self.owns(where) or self._creates(list(command[1:])):
                    done = self.run(command[1:], cwd=kwargs.get('cwd'), input=_text(kwargs.get('input')),
                                    env=kwargs.get('env'))
                    if kwargs.get('check') and done.returncode:
                        raise subprocess.CalledProcessError(done.returncode, command, done.stdout, done.stderr)
                    if not kwargs.get('text') and not kwargs.get('universal_newlines') and not kwargs.get('encoding'):
                        done = subprocess.CompletedProcess(done.args, done.returncode, done.stdout.encode(
                            errors='surrogateescape'), done.stderr.encode())
                    return done
            return real(command, *args, **kwargs)
        subprocess.run = run
        try:
            yield self
        finally:
            subprocess.run = real

    @staticmethod
    def _creates(args):
        """`git init` and `git clone` make a repository: inside intercept() it is made here."""
        while args and args[0] in ('-C', '-c'):
            args = args[len(('-C', 'path')):]
        return args[:1] in (['init'], ['clone'])

    @staticmethod
    def _where(args, cwd):
        where = cwd
        while args and args[0] in ('-C', '-c'):
            if args[0] == '-C':
                where = args[1] if where is None or Path(args[1]).is_absolute() else str(Path(where) / args[1])
            args = args[len(('-C', 'path')):]
        if where is None and args[:1] == ['init']:
            return None
        return where if where is not None else os.getcwd()


class _Output(Failed):
    """A command that prints and exits non-zero (merge-tree with conflicts)."""

    def __init__(self, out, code):
        super().__init__('', code)
        self.out = out


def _short(sha):
    """An object id as git abbreviates it in a push report."""
    return sha[:len('abcdefg')]


def _text(value):
    return value.decode(errors='surrogateescape') if isinstance(value, bytes) else value

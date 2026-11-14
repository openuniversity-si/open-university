"""The zip packages of the port's Lambdas, built deterministically (DEP8, docs/operations/aws.md 22.2).

The same files always give the same bytes, so the sha256 of a package names its content: the gate's check job builds it
for the PR head, uploads it once to the outputs bucket as artifacts/lambda/<function>/<sha256>.zip and records which digest
each function would run in artifacts/lambda/head/<head sha>.json (with the base the head was built on); the fast deploy
swaps a pointer to it, the slow deploy (infra/aws/deploy.sh) builds it too for a stack that has none yet.

A package is the module closure of the handler (read from the imports with ast, so a new import is packaged by itself):
stdlib Python only. The library the port needs (psycopg) is one pinned layer, built by the deployer with its bytecode.

  scripts/lambda-package digest [--root DIR]                      the digest of each function's package, as JSON
  scripts/lambda-package gate --base SHA --head SHA               the gate's check: build, upload, record (only for a fast diff)
  scripts/lambda-package publish --record                         the deployer: build, upload, print the S3 keys (JSON, last line) deploy.sh passes to the port stack
  scripts/lambda-package code [--root DIR]                        IMAGE-PREWARM-B1: the service/runner code bundle's key and sha256
                                                                  (JSON), uploaded once when TOWER_ARTIFACT_BUCKET is set
  scripts/lambda-package code-gate --base SHA --head SHA          IMAGE-PREWARM-B2: the same bundle, only for a code-only head
                                                                  (deploy_classify.code_only of base...head); one JSON line
"""
import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

LIB = Path(__file__).resolve().parent
ROOT = LIB.parent.parent
sys.path.insert(0, str(LIB))
from adapters import storage  # noqa: E402

PACKAGE = 'tower_infra'
SOURCE = Path('infra/service') / PACKAGE
# function -> (handler module, the __init__ it ships). The ingress ships the minimal one, as its Dockerfile does.
FUNCTIONS = {
    'tower-port-api': ('http_port', Path('infra/service') / PACKAGE / '__init__.py'),
    'tower-port-ack-ingress': ('ingress', Path('infra/ingress/__init__.py')),
    'tower-port-webhook-consumer': ('webhook_consumer', Path('infra/service') / PACKAGE / '__init__.py'),
}
HANDLER = 'handler'
# GATE-SHUTDOWN: the functions the 40-port stack still has, the only ones `publish` (the deployer) builds and uploads: the
# webhook path (the ack ingress and its consumer) left the stack. FUNCTIONS keeps every package (the gate's digests, the
# import-closure tables of deploy_classify and fastdeploy are pinned to it).
PUBLISHED = ('tower-port-api',)
# the 40-port stack parameter each published function's S3 key goes to (deploy.sh --parameter-overrides; no SSM: the deployer
# role may not PutParameter under /tower/deploy/lambda/)
PARAMETERS = {'tower-port-api': 'PortCode'}
LAYER_PARAMETER = 'DepsKey'
LAYER_REQUIREMENTS = Path('infra/service/requirements-lambda.txt')
LAYER_PLATFORMS = ('--platform', 'manylinux2014_aarch64', '--platform', 'manylinux_2_28_aarch64')
DATE = (1980, 1, 1, 0, 0, 0)
CODE = 'tower-code'  # IMAGE-PREWARM-B1: the service/runner code bundle, artifacts/lambda/tower-code/<sha256>.zip
MIGRATIONS = Path('infra/db/migrations')
REQUIREMENTS = Path('infra/service/requirements.txt')
CODE_INPUTS = (SOURCE, MIGRATIONS, REQUIREMENTS)  # IMAGE-PREWARM-C: every path build_code reads (gate_infra.landed_code, deploy.sh)


def key_of(function, digest):
    return f'artifacts/lambda/{function}/{digest}.zip'


def code_key(digest):
    """IMAGE-PREWARM-B1: under artifacts/lambda/, which the service and runner task roles already read."""
    return key_of(CODE, digest)


def head_key(head):
    return f'artifacts/lambda/head/{head}.json'


def layer_key(digest):
    return f'artifacts/lambda/deps/{digest}.zip'


def imports_of(path):
    """The sibling modules a module imports (`from . import a, b` and `from .a import x`), lazy ones included."""
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                found.add(node.module.split('.')[0])
            else:
                found.update(alias.name for alias in node.names)
    return found


def closure(root, function):
    """The module names the function's handler needs, sorted."""
    handler = FUNCTIONS[function][0]
    todo, seen = [handler], set()
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        path = Path(root) / SOURCE / f'{name}.py'
        if not path.is_file():
            raise FileNotFoundError(f'{function}: module {name} is imported but {path} does not exist')
        seen.add(name)
        todo.extend(imports_of(path))
    return sorted(seen)


def build(root, function):
    """(zip bytes, sha256 hex, {archive name: file sha256}) of one function, byte-identical for the same files."""
    root = Path(root)
    files = {f'{PACKAGE}/__init__.py': root / FUNCTIONS[function][1]}
    files.update({f'{PACKAGE}/{name}.py': root / SOURCE / f'{name}.py' for name in closure(root, function)})
    return archive_of(files)


def archive_of(files):
    """(zip bytes, sha256 hex, {archive name: file sha256}) of {archive name: path}: fixed dates, modes and order."""
    out, parts = io.BytesIO(), {}
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            data = files[name] if isinstance(files[name], bytes) else files[name].read_bytes()
            parts[name] = hashlib.sha256(data).hexdigest()
            info = zipfile.ZipInfo(name, DATE)
            info.compress_type, info.external_attr, info.create_system = zipfile.ZIP_DEFLATED, 0o644 << 16, 3
            archive.writestr(info, data, zipfile.ZIP_DEFLATED, 9)
    data = out.getvalue()
    return data, hashlib.sha256(data).hexdigest(), parts


def build_all(root):
    return {function: build(root, function) for function in FUNCTIONS}


SALT = 'MEASURE'  # SWAP-MEASURE: the file a measured round's bundle carries beside the code (tower_infra/MEASURE)


def build_code(root, salt=None):
    """IMAGE-PREWARM-B1: the code bundle a service/runner task boots from (tower_infra.code_bundle): what the Dockerfile copies
    that is not a heavy layer, i.e. the whole tower_infra package and infra/db/migrations, plus requirements.txt, which the
    boot compares with the image's (another one needs a new image). Same (zip, sha256, parts) as build()."""
    root = Path(root)
    files = {f'{PACKAGE}/{path.relative_to(root / SOURCE)}': path for path in sorted((root / SOURCE).rglob('*'))
             if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc'}
    files.update({f'migrations/{path.name}': path for path in sorted((root / MIGRATIONS).iterdir()) if path.is_file()})
    files['requirements.txt'] = root / REQUIREMENTS
    if salt:  # SWAP-MEASURE: the same code with a mark of the round: another digest, so a successor of it may stand by
        files[f'{PACKAGE}/{SALT}'] = f'{salt}\n'.encode()
    return archive_of(files)


def manifest(built, base, head):
    return {'head': head, 'base': base,
            'functions': {function: {'sha256': digest, 'key': key_of(function, digest), 'bytes': len(data),
                                     'files': parts}
                          for function, (data, digest, parts) in sorted(built.items())}}


# --- the store: the storage port's s3 adapter (boto3 where it is, else the aws CLI; the deployer's image has the CLI only)


STORE_ADAPTER = 's3'  # explicit: providers.storage_adapter (local by default) must never decide where the artifacts go


def open_store(bucket):
    return storage.open_store(bucket, STORE_ADAPTER)


def upload(store, built, base, head, record=True):
    """Each package once (the key names its content), then the head's manifest. Answers the manifest."""
    fresh = []
    for function, (data, digest, _) in sorted(built.items()):
        key = key_of(function, digest)
        if not store.exists(key):
            store.put(key, data)
            fresh.append(function)
    found = manifest(built, base, head)
    if record:
        store.put(head_key(head), (json.dumps(found, indent=1, sort_keys=True) + '\n').encode())
    found['uploaded'] = fresh
    return found


def changed(root, base, head, dots='..'):
    out = subprocess.run(['git', '-C', str(root), 'diff', '--name-only', '--no-renames', f'{base}{dots}{head}'],
                         check=True, capture_output=True, text=True).stdout
    return out.splitlines()


def wants_artifact(paths):
    """True when the diff has a fast Lambda target (deploy_classify): only those PRs pay for a package."""
    import deploy_classify
    return any(target.startswith('fast:lambda-') for target in deploy_classify.classify(paths)['fast'])


def gate(root, base, head, store=None, paths=None):
    """The gate's check: nothing for a diff without a fast Lambda target, else build and (with a store) upload and record.
    A failed upload is a warning, not a red check: without the artifact the fast deploy falls back to the slow path."""
    paths = changed(root, base, head) if paths is None else paths
    if not wants_artifact(paths):
        return {'built': False, 'why': 'no fast Lambda target in the diff'}
    built = build_all(root)
    result = {'built': True, 'digests': {function: digest for function, (_, digest, _) in built.items()}}
    # DIGEST-FROM-GATE-JOB (revisão da arquitetura, achado 35): the digests are said even when a manifest of this head is in
    # the store already (FAST-ARTIFACT-NOCACHE: nothing is uploaded again). The store is writable by any check on the runner,
    # so the fast path trusts the digests this job says, not the manifest: one another PR's check wrote is refused
    if store is not None and store.exists(head_key(head)):
        return {**result, 'published': True, 'why': f'manifest {head_key(head)} already in the store'}
    if store is None:
        result['published'] = False
        result['why'] = 'no TOWER_ARTIFACT_BUCKET: built and digested only'
        return result
    try:
        result['uploaded'] = upload(store, built, base, head)['uploaded']
        result['published'] = True
    except Exception as error:  # noqa: BLE001
        result.update(published=False, why=f'upload failed: {error}')
    return result


# --- the deployer: the starting packages the stack reads, and the layer ---------------------------------------------------
LAYER_PYTHON = (3, 12)  # the Lambdas' runtime (40-port.json: python3.12): the only bytecode they load
LAYER_BYTECODE = b'\n# bytecode: cpython-312, unchecked-hash\n'  # part of the layer's name when it carries its bytecode


def layer_python(which=None, version=None):
    """PORT-COLD-LAYER: an interpreter of the Lambdas' own Python, to compile the layer's bytecode with: this one when
    it is that version, else python3.12 on the PATH, else None (the layer goes without bytecode, as it always did)."""
    import shutil
    if (version or sys.version_info[:2]) == LAYER_PYTHON:
        return sys.executable
    return (which or shutil.which)('python%d.%d' % LAYER_PYTHON)


def layer(root, store, run=subprocess.run, work=None, python=None):
    """The pinned layer (psycopg), built once per requirements file: python/ ... for arm64, CPython 3.12.
    PORT-COLD-LAYER: with its bytecode when the builder has the Lambdas' Python (live 12/11: the driver's import was
    0.32 to 0.46 s of a cold start, and the Lambda compiled every module of it on every cold start: /opt is read-only,
    nothing is kept). Unchecked-hash .pyc files: loaded as they are, whatever the files' dates in the zip. The layer's
    name says whether it carries them, so a builder that gains or loses that Python builds the other one."""
    import tempfile
    requirements = Path(root) / LAYER_REQUIREMENTS
    compiler = (python or layer_python)()
    digest = hashlib.sha256(requirements.read_bytes() + (LAYER_BYTECODE if compiler else b'')).hexdigest()
    key = layer_key(digest)
    if store.exists(key):
        return key
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(work or tmp) / 'python'
        # psycopg-binary 3.3 ships aarch64 wheels tagged manylinux_2_28 only; the python3.12 Lambda runtime (Amazon Linux 2023,
        # glibc 2.34) runs them, so both tags are accepted (09/11: manylinux2014 alone found no psycopg-binary==3.3.8).
        # --no-compile: pip's own bytecode is the builder's Python's and dated; the layer's is compiled below, or absent
        run([sys.executable, '-m', 'pip', 'install', '--quiet', '--target', str(target), *LAYER_PLATFORMS,
             '--implementation', 'cp', '--python-version', '%d.%d' % LAYER_PYTHON, '--only-binary=:all:', '--no-compile',
             '-r', str(requirements)], check=True)
        if compiler:
            # a file that does not compile goes without its bytecode (the Lambda compiles it, as before): never a failed build
            run([compiler, '-m', 'compileall', '-q', '--invalidation-mode', 'unchecked-hash', str(target)], check=False)
        tag = 'cpython-%d%d.pyc' % LAYER_PYTHON
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(p for p in target.rglob('*') if p.is_file()
                               and ('__pycache__' not in p.parts or (compiler and p.name.endswith(tag)))):
                info = zipfile.ZipInfo(str(path.relative_to(target.parent)), DATE)
                info.compress_type, info.external_attr = zipfile.ZIP_DEFLATED, 0o644 << 16
                archive.writestr(info, path.read_bytes())
        store.put(key, out.getvalue())
    return key


def backend_of(store):
    """Which client the store uses: boto3 when importable, else the aws CLI (the adapter tries boto3 first)."""
    client = getattr(store, 'client', None)
    try:
        return 'boto3' if client and client() else 'aws-cli'
    except Exception:  # noqa: BLE001
        return 'aws-cli'


def operation(label, store, key, fn, *args, **kwargs):
    """Run one step of the publish; when it fails, say WHICH operation (exists/put/ssm-put/pip), the S3 key prefix and the
    backend used, plus the stderr of the command, on stderr (deploy.sh keeps it in last-build.steps), then re-raise."""
    try:
        return fn(*args, **kwargs)
    except Exception as error:  # noqa: BLE001
        detail = getattr(error, 'stderr', None) or b''
        detail = detail.decode(errors='replace') if isinstance(detail, bytes) else str(detail)
        prefix = key.rsplit('/', 1)[0] if key and '/' in key else key
        print(f'lambda-package FAILED at {label}: backend={backend_of(store)} bucket={getattr(store, "bucket", "?")} '
              f'prefix={prefix} {type(error).__name__}: {str(error)[:200]} {detail.strip()[-300:]}', file=sys.stderr)
        raise


def publish(root, store, with_layer=True, run=subprocess.run):
    """The deployer's step before the stacks: the package of each PUBLISHED function and the layer uploaded. Answers the S3
    key of each (and 'deps' for the layer): the keys are deterministic, deploy.sh passes them to the port stack as parameters."""
    built = {function: build(root, function) for function in PUBLISHED}
    keys = {}
    for function, (data, digest, _) in built.items():
        keys[function] = key_of(function, digest)
        if not operation(f'exists {function}', store, keys[function], store.exists, keys[function]):
            operation(f'put {function}', store, keys[function], store.put, keys[function], data)
    if with_layer:
        keys['deps'] = operation('layer (pip install, zip, exists/put)', store, 'artifacts/lambda/deps/', layer, root, store, run=run)
    return keys


def publish_code(root, store=None, salt=None):
    """IMAGE-PREWARM-B1: the code bundle's key, sha256 and size; uploaded once (the key names its content) with a store."""
    data, digest, _ = build_code(root, salt)
    found = {'key': code_key(digest), 'sha256': digest, 'bytes': len(data), 'uploaded': False}
    if store is not None and not store.exists(found['key']):
        store.put(found['key'], data)
        found['uploaded'] = True
    return found


def gate_code(root, base, head, store=None, paths=None, salt=None):
    """IMAGE-PREWARM-B2: the prewarm's job (scripts/gate-check artifact code, made by the live service on a unit branch's
    push). The head's diff from where it left the base (base...head) classified by deploy_classify.code_only; a code-only
    head gets its bundle built and, with a store, uploaded. Answers {code_only, why[, key, sha256, bytes, uploaded]}; the
    service reads it from the job's log tail (one JSON line, the last)."""
    import deploy_classify
    if salt:  # SWAP-MEASURE: a measured round: the published head itself (base == head), its bundle with the round's mark
        if base != head:
            return {'code_only': False, 'why': 'a measured round is of the published head: base and head are one'}
        return {'code_only': True, 'why': f'a measured round ({salt})', 'published': store is not None,
                **publish_code(root, store, salt)}
    paths = changed(root, base, head, '...') if paths is None else paths
    ok, why = deploy_classify.code_only(paths)
    if not ok:
        return {'code_only': False, 'why': why}
    return {'code_only': True, 'why': why, 'published': store is not None, **publish_code(root, store)}


def main(argv):
    parser = argparse.ArgumentParser(prog='lambda-package', description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('digest').add_argument('--root', default=str(ROOT))
    gate_parser = sub.add_parser('gate')
    gate_parser.add_argument('--base', required=True)
    gate_parser.add_argument('--head', required=True)
    gate_parser.add_argument('--root', default=str(ROOT))
    pub = sub.add_parser('publish')
    pub.add_argument('--root', default=str(ROOT))
    pub.add_argument('--record', action='store_true', help='accepted and ignored (the keys are printed, not written to SSM)')
    pub.add_argument('--no-layer', action='store_true')
    sub.add_parser('code').add_argument('--root', default=str(ROOT))
    code_gate = sub.add_parser('code-gate')
    code_gate.add_argument('--base', required=True)
    code_gate.add_argument('--head', required=True)
    code_gate.add_argument('--root', default=str(ROOT))
    code_gate.add_argument('--salt', default='', help="SWAP-MEASURE: a measured round's mark (base and head the same)")
    args = parser.parse_args(argv)
    bucket = os.environ.get('TOWER_ARTIFACT_BUCKET')
    store = open_store(bucket) if bucket else None
    if args.command == 'digest':
        print(json.dumps({function: digest for function, (_, digest, _) in build_all(args.root).items()}, indent=1))
    elif args.command == 'gate':
        result = gate(args.root, args.base, args.head, store)
        print(json.dumps(result, sort_keys=True))  # one line, the last on stdout: the fast path reads the digests from it
        if store is not None and result.get('built') and not result.get('published'):
            print(f"lambda-package: WARNING no artifact published for {args.head}: {result.get('why')}", file=sys.stderr)
    elif args.command == 'code':
        print(json.dumps(publish_code(args.root, store), sort_keys=True))
    elif args.command == 'code-gate':
        print(json.dumps(gate_code(args.root, args.base, args.head, store, salt=args.salt or None), sort_keys=True))  # one line, the last
    else:
        if store is None:
            parser.error('TOWER_ARTIFACT_BUCKET is not set')
        print(json.dumps(publish(args.root, store, with_layer=not args.no_layer), sort_keys=True))  # one line: deploy.sh reads the last
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

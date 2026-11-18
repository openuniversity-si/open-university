"""Deploy classifier (DEP6): from the paths a merge changed to the deploy targets it needs, on one of two paths.

A path maps to a list of targets, by the first matching rule of RULES (ordered, most specific first; the table is in
docs/operations/aws.md, 'Deploy contínuo em dois caminhos'). Targets:

  fast:lambda-<x>      pointer swap of one Lambda alias (x: port, ingress, webhooks) or all of them (x: all)
  slow:stack-<y>       a CloudFormation stack of infra/aws/stacks (y: network, data, service, port, runner), or all
  slow:service-image   the Fargate service/runner image (infra/service, infra/db)
  slow:deployer        the deployer itself (infra/aws/deploy.sh, order.json): every stack is a candidate
  manual:bootstrap     infra/aws/bootstrap.json, budget.json: applied by hand (the Torre), never by the pipeline
  data-only            a registry/config value: it is written as data, no deploy (DEP9 reads it from SSM/table)
  none                 docs, tests, scripts, units: nothing to deploy

Pure and deterministic: the same list always gives the same JSON (sorted, no clock, no network). Stdlib only.
"""
import json
import re
import subprocess
import sys

# tower_infra modules by the Lambdas whose package holds them (the x of fast:lambda-<x>): the import closure of each handler of
# infra/aws/stacks/40-port.json (http_port, ingress, webhook_consumer), as lambda_package.closure reads it from the imports; a
# test pins this table to it, so a new import fails there until it is listed. A module of no package runs only in the service.
# SLOW-PATH-NO-ROLLOUT-WAIT: the table named the handlers and three of their imports only, so a change to any other module of a
# package (the consumer imports http_port; both import config_data, live_image, ...) changed a Lambda's code with no fast swap,
# and the slow path applied the port stack for it (193 s on 10/11) though nothing of its template had changed.
PORT, INGRESS, WEBHOOKS = 'port', 'ingress', 'webhooks'
EVERY = (INGRESS, PORT, WEBHOOKS)
LAMBDA_MODULES = {
    'ingress': (INGRESS,), 'awsjson': (INGRESS,), 'webhook_consumer': (WEBHOOKS,),
    **{name: (PORT, WEBHOOKS) for name in ('__init__', 'branches', 'canary', 'checks', 'config_data', 'database', 'drills', 'engine', 'http_port',
                                           'observations', 'port', 'subscriptions', 'wake')},
    **{name: EVERY for name in ('ed25519', 'forge_webhooks')},
}
STACK = re.compile(r'^infra/aws/stacks/\d+-([a-z0-9-]+)\.json$')
MODULE = re.compile(r'^infra/service/tower_infra/([A-Za-z0-9_]+)\.py$')

ALL_LAMBDAS = ['fast:lambda-all']
SLOW_IMAGE = 'slow:service-image'

# (regex, targets); a callable target list receives the match. First match wins.
RULES = [
    (r'^infra/aws/stacks/', lambda m: ['slow:stack-' + STACK.match(m.string).group(1)] if STACK.match(m.string) else ['slow:stack-all']),
    (r'^infra/aws/(deploy\.sh|order\.json)$', ['slow:deployer']),
    (r'^infra/aws/(bootstrap|budget)\.json$', ['manual:bootstrap']),
    (r'^infra/aws/', ['slow:deployer']),
    (r'^infra/(db|ingress)/', [SLOW_IMAGE]),
    (r'^infra/service/(Dockerfile|requirements\.txt)$', [SLOW_IMAGE]),
    # PORT-COLD-LAYER: the Lambdas' layer alone reads it (lambda_package.layer; the Dockerfile copies requirements.txt): the
    # port stack takes the new layer, no image is built and no task is replaced
    (r'^infra/service/requirements-lambda\.txt$', ['slow:stack-port']),
    (r'^infra/service/tower_infra/', None),  # per module, see module_targets
    (r'^infra/service/', [SLOW_IMAGE]),
    # STAGED-WORKFLOWS-NONE (the Torre, 16/11/2026): the GitHub workflows staged for the owner to install (D-087) are in no
    # image and no stack; as an image path, #133's staged tower-gate.yml rolled the service's ECS task out at 03:49 and
    # #134, landing in the handover, lost its fast landing
    (r'^services/runner/github/', ['none']),
    (r'^services/runner/', [SLOW_IMAGE]),
    (r'^config/registry/', ['data-only']),
    (r'^config/', ['data-only']),
]


def module_targets(path):
    """tower_infra module -> targets. A module of a Lambda's package swaps that alias (all of them: fast:lambda-all) AND
    rebuilds the service image (the service imports it too); a service-only module is the image alone."""
    match = MODULE.match(path)
    if not match:  # a sub-package or data file of the module: the whole image, conservatively
        return [SLOW_IMAGE]
    lambdas = LAMBDA_MODULES.get(match.group(1), ())
    return (ALL_LAMBDAS if lambdas == EVERY else ['fast:lambda-' + each for each in lambdas]) + [SLOW_IMAGE]


def classify_path(path):
    path = path.strip().lstrip('./')
    for pattern, targets in RULES:
        match = re.match(pattern, path)
        if not match:
            continue
        if targets is None:
            return module_targets(path)
        return list(targets(match) if callable(targets) else targets)
    return ['none']


def classify(paths):
    """{paths: [{path, targets}], targets, fast, slow, manual, route}; route is fast, slow, both, data-only or none."""
    seen = sorted({p.strip().lstrip('./') for p in paths if p.strip()})
    rows = [{'path': p, 'targets': sorted(classify_path(p))} for p in seen]
    targets = sorted({t for row in rows for t in row['targets']})
    fast = [t for t in targets if t.startswith('fast:')]
    slow = [t for t in targets if t.startswith('slow:')]
    manual = [t for t in targets if t.startswith('manual:')]
    if fast and slow:
        route = 'both'
    elif fast:
        route = 'fast'
    elif slow:
        route = 'slow'
    elif 'data-only' in targets or manual:
        route = 'data-only' if 'data-only' in targets else 'none'
    else:
        route = 'none'
    # a fast lambda target already covered by the service image still needs its pointer swap, so both are kept
    return {'paths': rows, 'targets': [t for t in targets if t != 'none'] or ['none'], 'fast': fast, 'slow': slow,
            'manual': manual, 'route': route}


CODE_ONLY = 'infra/service/tower_infra/'  # IMAGE-PREWARM-B2: what a code bundle carries (lambda_package.build_code)
MIGRATIONS = 'infra/db/migrations'
REQUIREMENTS = 'infra/service/requirements.txt'
# IMAGE-PREWARM-C: every path build_code reads (gate_infra.landed_code, merge_train, deploy.sh); lambda_package's
# CODE_INPUTS are these, as paths (D-322: the gate and the train read them here, not from the deploy unit)
CODE_INPUTS = (CODE_ONLY.rstrip('/'), MIGRATIONS, REQUIREMENTS)
# CODE-BESIDE-PORT: a slow target that no ECS task runs on: the port stack (the HTTP API, its Lambdas, the webhook queue). A head
# whose image changes only in code may change it too: the code still goes live by the swap or in place, and the build applies
# that stack alone (live 11/11, #509: one property of the port stack took the code to the image build and two rollouts, 8 min)
BESIDE = ('slow:stack-port',)
# OWNER-STEP-NEEDS-ROLLOUT: files of the package that run from the image, never from a code bundle: the owner's step
# (the init container, with the owner's password, when a task starts). A head that changes one is not code-only: only a
# new image and a rollout run it (mirrored in infra/aws/deploy.sh code_live)
# SUPERVISOR-NEEDS-ROLLOUT: and the task's supervisor (the container's first process, tower_infra.supervisor): it runs for
# the task's whole life on the code the task started with, while its children change code at every landing
# RESTORE-DRILL: and the reading of a restored database (restore_check.py), which the init container runs, from the image
# TASK-POOLER: and the task's pool of connections (pooler.py), which the supervisor starts from the image and keeps
# for the task's whole life
IMAGE_RUN = (CODE_ONLY + 'dbinit.py', CODE_ONLY + 'supervisor.py', CODE_ONLY + 'restore_check.py', CODE_ONLY + 'pooler.py')


def code_only(paths):
    """IMAGE-PREWARM-B2 (docs/operations/aws.md 22.9): (True, why) when these paths need a new service/runner image only for
    the files of infra/service/tower_infra, which a code bundle carries on the image already built; else (False, why), the
    slow path. Not code-only: no image target at all (nothing to prewarm); any other slow or manual target (a stack of the
    ECS tasks, the network or the data, the deployer, the bootstrap; not BESIDE, the port stack: CODE-BESIDE-PORT); any other
    path of the image: Dockerfile, requirements.txt, infra/db (a migration is a real
    change of the database), infra/ingress, services/runner; and the package's files that run from the image (IMAGE_RUN). Paths without a slow target (docs, tests, scripts, a fast
    Lambda's swap, data) do not count either way."""
    found = classify(paths)
    image = [row['path'] for row in found['paths'] if SLOW_IMAGE in row['targets']]
    if not image:
        return False, 'no service/runner image target'
    others = [target for target in found['slow'] + found['manual'] if target != SLOW_IMAGE and target not in BESIDE]
    if others:
        return False, 'also ' + ', '.join(others)
    outside = [path for path in image if not path.startswith(CODE_ONLY) or path in IMAGE_RUN]
    if outside:
        return False, 'the image itself changes: ' + ', '.join(outside[:5])
    beside = [target for target in found['slow'] if target in BESIDE]
    return True, f'{len(image)} file(s) of {CODE_ONLY} only' + (f", beside {', '.join(beside)}" if beside else '')


def changed_files(old, new):
    out = subprocess.run(['git', 'diff', '--name-only', '--no-renames', f'{old}..{new}'], check=True,
                         capture_output=True, text=True).stdout
    return out.splitlines()


def main(argv):
    import argparse
    parser = argparse.ArgumentParser(prog='deploy-classify', description=__doc__.split('\n')[0])
    parser.add_argument('shas', nargs='*', help='OLD NEW: classify the files changed between two commits (git diff)')
    parser.add_argument('--files', help='a file with one path per line, or - for stdin')
    args = parser.parse_args(argv)
    if args.files:
        text = sys.stdin.read() if args.files == '-' else open(args.files, encoding='utf-8').read()
        paths = text.splitlines()
    elif len(args.shas) == 2:
        paths = changed_files(*args.shas)
    else:
        parser.error('give OLD NEW shas or --files FILE')
    print(json.dumps(classify(paths), indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

"""`scripts/service`: the gate and the train as services (GATE-TRAIN-SERVICES, D-086, ADR-41).

  status [--json]          the switches, the train's lock and wake, the queue, the latest merges, this machine's runner
                           and the health checks (contracts/service/status.v1.json with --json)
  health [--json]          the checks alone; exit 1 when one fails, so a monitor can probe it
  metrics                  the Prometheus text exposition of the same numbers
  runner [--once] [--dry-run] [--print-unit]
                           the Tower runner: claims gate and train jobs from the control plane and runs them, no AI
                           session (service_runner.py, D-290); --dry-run prints the route it would take and claims nothing;
                           --print-unit prints a systemd user unit that keeps it up
  liveness                 exit 0 when this machine's runner beat within service.heartbeat_stale_s, else 1 with the reason: the
                           probe of the watch timer (--print-unit <name>) that restarts a hung runner
  pause|resume --reason R  service.paused through the shared store (D-069 item 5): runners take no new job
  requeue|cancel --pr N --reason R
                           refused: the control plane's POST /v1/admin is the only admin route (D-290); the command
                           prints it
The read commands answer with no control plane deployed and no runner running (a missing runner is a warning)."""
import argparse
import getpass
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import service_status  # noqa: E402

ACTOR = 'service'  # the actor of a switch flipped through `scripts/service`, beside the person who ran it


def config_set(name, value, reason):
    """`scripts/config set NAME VALUE --actor A --reason R`: the shared store's audited change (config.changed)."""
    import config_cli
    return config_cli.main(['set', name, value, '--actor', f'{ACTOR}:{getpass.getuser()}', '--reason', reason])


def admin_route(action, pr, reason, sha=None):
    """The control plane's admin call for `action` (D-290): the only route of a requeue or a cancel. The runner reads no
    admin record of its own, so this command writes nothing and names the call an operator with ADMIN_TOKEN makes."""
    body = {'action': action, 'pr': pr, 'reason': reason, **({'sha': sha} if sha else {})}
    return (f"curl -X POST -H 'authorization: Bearer $ADMIN_TOKEN' -H 'content-type: application/json' "
            f"-d '{json.dumps(body)}' {config.get('service.control_url').rstrip('/')}/v1/admin")


def main(argv=None, sources=None):
    parser = argparse.ArgumentParser(prog='scripts/service', description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('status', 'health'):
        sub.add_parser(name, help=f'the service {name}').add_argument('--json', action='store_true')
    sub.add_parser('metrics', help='Prometheus text exposition')
    sub.add_parser('liveness', help='exit 0 when this machine\'s runner beat recently')
    runner = sub.add_parser('runner', help='the Tower runner')
    runner.add_argument('--once', action='store_true', help='one poll and its jobs, then exit')
    runner.add_argument('--print-unit', nargs='?', const='', metavar='NAME',
                        help='print a systemd user unit for this checkout (default the runner; also the liveness watch service and timer)')
    runner.add_argument('--kind', help='the runner kind the printed unit names (OU_RUNNER_KIND: box, vm, actions, session, other)')
    runner.add_argument('--dry-run', action='store_true', help='print the jobs one poll finds; run and save nothing')
    for name in ('pause', 'resume'):
        sub.add_parser(name, help=f'{name} the runners (service.paused)').add_argument('--reason', required=True)
    for name in ('requeue', 'cancel'):
        command = sub.add_parser(name, help=f'{name} the jobs of one PR: refused, prints the control plane admin call')
        command.add_argument('--pr', type=int, required=True)
        command.add_argument('--sha', help='requeue: the head to gate (default: the PR head the runner saw last)')
        command.add_argument('--reason', required=True)
    args = parser.parse_args(argv)
    if args.command in ('pause', 'resume'):
        return config_set('service.paused', 'true' if args.command == 'pause' else 'false', args.reason)
    if args.command in ('requeue', 'cancel'):
        print(f'service: {args.command} #{args.pr} not recorded: the control plane is the only admin route (D-290); '
              f'run\n  {admin_route(args.command, args.pr, args.reason, args.sha)}', file=sys.stderr)
        return 2
    if args.command == 'runner':
        import service_runner
        if args.print_unit is not None:  # the bare flag is the empty name: the runner unit
            try:
                print(service_runner.unit_text(name=args.print_unit, **({'kind': args.kind} if args.kind else {})), end='')
            except KeyError as error:
                parser.error(error.args[0])
            return 0
        try:
            built = service_runner.build()
        except service_runner.RouteError as error:
            print(f'service runner: {error}', file=sys.stderr)
            return 2
        if args.dry_run:  # a claim leases the job, so a dry run claims nothing
            print(f'service runner (dry run): claims from {built.transport.url} as {built.transport.runner["name"]} '
                  f'({built.transport.runner["kind"]}); nothing claimed')
            return 0
        if args.once:
            built.recover()
            built.once()
        else:
            built.serve()
        return 0
    if args.command == 'liveness':
        sources = sources or service_status.Sources()
        name, status, detail = service_status.runner_check(sources.runner(), sources.clock.now())
        print(f'{status} {name}: {detail}')
        return 0 if status == service_status.PASS else 1
    document = service_status.status(sources or service_status.Sources())
    if args.command == 'metrics':
        sys.stdout.write(service_status.metrics(document))
        return 0
    if args.command == 'health':
        health = document['health']
        print(json.dumps(health, indent=1) if args.json else
              '\n'.join(f'{check["status"]} {check["name"]}: {check["detail"]}' for check in health['checks']))
        return 1 if health['status'] == service_status.FAIL else 0
    print(json.dumps(document, indent=1) if args.json else service_status.human(document))
    return 0


if __name__ == '__main__':
    sys.exit(main())

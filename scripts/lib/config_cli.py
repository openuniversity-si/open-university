"""scripts/config: the command line of the configuration registry (D-068). A thin shell over scripts/lib/config.py.

  list [--owner O]                      every parameter with its effective value (* = changed from the registry)
  get NAME                              the effective value as JSON
  describe NAME                         type, range, unit, owner, readers, default, value and change count
  set NAME VALUE --actor A --reason R   override (VALUE is JSON; a bare word is a string); validated, audited
  set NAME --default --actor A --reason R   return to the registry default
  diff [--ref REF]                      overrides against the registry, or registry defaults changed since REF
  history [NAME]                        every change: id, when, who, old -> new, why
  revert CHANGE --actor A --reason R    undo a change (id prefix) with a new change
Keys the AWS service owns (infra/service/tower_infra/config_data.py: SPEC, the one list; DEP9) live in the service's table, not
in git: `set` writes them through the port (PUT /v1/config/NAME; TOWER_PORT_URL and TOWER_PORT_TOKEN) and takes effect in about
a second with no deploy; `get` reads the live value (GET /v1/config/NAME). Every other key keeps the file path above.
--json prints machine-readable output. Exit 1 on a refused change.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

import config


def system_clock():
    """The registry's clock (forge-events.clock); tests pass their own time to main."""
    import forge_events
    return forge_events.clock_from_config().now()


def _value(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _show(value):
    return json.dumps(value, ensure_ascii=False)


def _line(event):
    p = event['payload']
    undo = f' (reverts {p["reverts"][:12]})' if p.get('reverts') else ''
    return (f'{event["event_id"][:12]}  {p["at"]}  {p["actor"]}  {p["name"]}: {_show(p["old"])} -> {_show(p["new"])}'
            f'{undo}  "{p["reason"]}"')


def service_keys():
    """The names the AWS service reads from work.config_value: SPEC of the service's config_data, the one list."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / 'infra' / 'service'))
    from tower_infra import config_data
    return config_data.SPEC


class PortError(Exception):
    pass


def port_call(method, name, body, environ, opener):
    """One request of the tenant port for a service key: the answer as a dict; PortError with a plain message."""
    url, token = environ.get('TOWER_PORT_URL'), environ.get('TOWER_PORT_TOKEN')
    if not url or not token:
        raise PortError(f'{name} is owned by the AWS service: it is read and written through the port '
                        f'(/v1/config/{name}), not git. Set TOWER_PORT_URL and TOWER_PORT_TOKEN (the tenant token) and rerun.')
    request = urllib.request.Request(f'{url.rstrip("/")}/v1/config/{name}', method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
    try:
        with opener(request, timeout=30) as answer:
            return json.loads(answer.read() or b'{}')
    except urllib.error.HTTPError as error:
        raise PortError(f'{method} /v1/config/{name}: {error.code} {error.read().decode("utf-8", "replace")[:300]}') from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
        raise PortError(f'{method} /v1/config/{name}: the port is unreachable ({type(error).__name__})') from None


def main(argv=None, clock=system_clock, root=None, environ=None, opener=urllib.request.urlopen):
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(prog='scripts/config', description=__doc__.splitlines()[0])
    parser.add_argument('--json', action='store_true', help='machine-readable output')
    commands = parser.add_subparsers(dest='command', required=True)
    listed = commands.add_parser('list')
    listed.add_argument('--owner')
    commands.add_parser('get').add_argument('name')
    commands.add_parser('describe').add_argument('name')
    setter = commands.add_parser('set')
    setter.add_argument('name')
    setter.add_argument('value', nargs='?')
    setter.add_argument('--default', action='store_true', help='return to the registry default')
    differ = commands.add_parser('diff')
    differ.add_argument('--ref', help='compare registry defaults with this git ref')
    commands.add_parser('history').add_argument('name', nargs='?')
    reverter = commands.add_parser('revert')
    reverter.add_argument('change')
    for sub in (setter, reverter):
        sub.add_argument('--actor', required=True, help='who changes it')
        sub.add_argument('--reason', required=True, help='why')
        sub.add_argument('--correlation', help='correlation_id of the flow (a PR, a batch)')
    args = parser.parse_args(argv)
    try:
        owned = service_keys() if args.command in ('get', 'set') else {}
        if args.command == 'get' and args.name in owned:
            live = port_call('GET', args.name, None, environ, opener)
            print(_show(live) if args.json else _show(live['value']))
        elif args.command == 'set' and args.name in owned:
            if args.default == (args.value is not None):
                parser.error('set takes either VALUE or --default')
            value = owned[args.name][1] if args.default else _value(args.value)
            before = port_call('GET', args.name, None, environ, opener)
            done = port_call('PUT', args.name, {'value': value, 'reason': f'{args.reason} (actor: {args.actor})'}, environ, opener)
            if args.json:
                print(_show({**done, 'old': before['value'], 'source': 'port'}))
            else:
                print(f'{args.name}: {_show(before["value"])} -> {_show(done["value"])} (version {done["version"]}, written '
                      f'through the port, no git, no deploy)  "{args.reason}"')
        elif args.command == 'get':
            print(_show(config.get(args.name, root)))
        elif args.command == 'list':
            rows = config.listing(args.owner, root)
            if args.json:
                print(_show(rows))
            for row in [] if args.json else rows:
                mark = '*' if row['overridden'] else ' '
                print(f'{mark} {row["name"]} = {_show(row["value"])} {row["unit"]}')
        elif args.command == 'describe':
            item = config.describe(args.name, root)
            if args.json:
                print(_show(item))
            for key, value in [] if args.json else item.items():
                print(f'{key}: {_show(value) if not isinstance(value, str) else value}')
        elif args.command == 'set':
            if args.default == (args.value is not None):
                parser.error('set takes either VALUE or --default')
            common = dict(actor=args.actor, reason=args.reason, now=clock(), root=root, correlation_id=args.correlation)
            event = (config.unset(args.name, **common) if args.default
                     else config.set_value(args.name, _value(args.value), **common))
            print(_show(event) if args.json else _line(event))
        elif args.command == 'revert':
            event = config.revert(args.change, actor=args.actor, reason=args.reason, now=clock(), root=root,
                                  correlation_id=args.correlation)
            print(_show(event) if args.json else _line(event))
        elif args.command == 'history':
            events = config.history(args.name, root)
            print(_show(events) if args.json else '\n'.join(_line(event) for event in events) or 'no changes')
        elif args.command == 'diff':
            rows = config.diff_ref(args.ref, root) if args.ref else config.diff(root)
            if args.json:
                print(_show(rows))
            elif args.ref:
                for row in rows:
                    print(f'{row["kind"]:8} {row["name"]}: {_show(row["old"])} -> {_show(row["new"])}')
            else:
                for row in rows:
                    print(f'{row["name"]}: {_show(row["default"])} -> {_show(row["value"])}  '
                          f'({row["change"][:12]} {row["actor"]} {row["at"]}: "{row["reason"]}")')
            if not rows and not args.json:
                print('no differences')
    except (config.ConfigError, config.StoreError, PortError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

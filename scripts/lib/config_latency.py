"""scripts/config-latency: how long from a config change to the service reading it (DEP9 step 2), in milliseconds.

PUT /v1/config/<key> with the key's CURRENT value and a new reason (a harmless write: the value does not change, the version
does), then watch GET /v1/deploy/status until config_version[<key>] reaches the version the PUT answered: that is the service
(Config.refresh on the tower_config event) saying it now reads it. Prints the milliseconds from the PUT's start to the
observation and from the PUT's answer to it. The watch is the measuring instrument, not a trigger: it has a safety timeout
(--timeout-s) and the interval between looks (--look-ms) bounds the resolution. Env: TOWER_PORT_URL, TOWER_PORT_TOKEN (never
printed). No value is left changed; a key without a row gets one holding its default (the value it already had).
Usage: scripts/config-latency [--key medir.webhook_ack_limit_s] [--timeout-s 30] [--look-ms 50] [--json]
"""
import argparse
import json
import os
import sys
import time

import config_cli


def measure(key, environ, opener, timeout_s=30.0, look_ms=50.0, clock=time.monotonic, sleep=time.sleep, stamp=time.time):
    """{key, value, version, put_ms, observed_ms, after_answer_ms}; PortError when the service never says it read it."""
    current = config_cli.port_call('GET', key, None, environ, opener)['value']
    started = clock()
    done = config_cli.port_call('PUT', key, {'value': current, 'reason': f'config-latency probe {int(stamp())} (value unchanged)'},
                                environ, opener)
    answered = clock()
    while True:
        status = status_call(environ, opener)
        seen = (status.get('config_version') or {}).get(key)
        if seen and int(seen['version']) >= int(done['version']):
            now = clock()
            return {'key': key, 'value': done['value'], 'version': done['version'],
                    'put_ms': round((answered - started) * 1000, 1), 'observed_ms': round((now - started) * 1000, 1),
                    'after_answer_ms': round((now - answered) * 1000, 1)}
        if clock() - started > timeout_s:
            raise config_cli.PortError(f'{key} version {done["version"]} was not observed by the service in {timeout_s:g} s '
                                       '(is the service running the DEP9 build?)')
        sleep(look_ms / 1000)


def status_call(environ, opener):
    import urllib.request
    request = urllib.request.Request(f'{environ["TOWER_PORT_URL"].rstrip("/")}/v1/deploy/status',
                                     headers={'Authorization': f'Bearer {environ["TOWER_PORT_TOKEN"]}'})
    with opener(request, timeout=30) as answer:
        return json.loads(answer.read() or b'{}')


def main(argv=None, environ=None, opener=None, **kwargs):
    import urllib.request
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(prog='scripts/config-latency', description=__doc__.splitlines()[0])
    parser.add_argument('--key', default='medir.webhook_ack_limit_s')
    parser.add_argument('--timeout-s', type=float, default=30.0)
    parser.add_argument('--look-ms', type=float, default=50.0)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    if args.key not in config_cli.service_keys():
        print(f'{args.key} is not a key of the AWS service', file=sys.stderr)
        return 1
    try:
        if not environ.get('TOWER_PORT_URL') or not environ.get('TOWER_PORT_TOKEN'):
            raise config_cli.PortError('set TOWER_PORT_URL and TOWER_PORT_TOKEN (the port and the tenant token)')
        found = measure(args.key, environ, opener or urllib.request.urlopen, args.timeout_s, args.look_ms, **kwargs)
    except config_cli.PortError as error:
        print(str(error), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(found))
    else:
        print(f'{found["key"]} v{found["version"]} (value unchanged: {json.dumps(found["value"])}): the service read it '
              f'{found["observed_ms"]} ms after the PUT started ({found["after_answer_ms"]} ms after the port answered)')
    return 0


if __name__ == '__main__':
    sys.exit(main())

"""PORT7-PROD: the post-deploy PRODUCTION ACK smoke (production is AckPath=sqs) and its rollback to AckPath=lambda; deploy.sh runs it when AckPath=sqs and persists ack_failed in last-build (never a failed build or a bisection).
ACK-CANARY-RETIRE: the canary stack's half (`--canary`, its variant routes and verdicts) left with the experiment: the
shape production runs was chosen on it (09/11) and is pinned by infra-ingress's tests.

After tower-app-port is deployed with AckPath=sqs, POST one deliberately invalid delivery (a fresh webhook-id, a current
webhook-timestamp, a signature no key verifies) to the webhook URL (stack outputs PortUrl + the route) and require:
  1. HTTP 200 or 202 from API Gateway, in under ACK_LIMIT_S (1 s, measured from outside, on the first request);
  2. the consumer's log (/aws/lambda/tower-port-webhooks) to show a `webhook_dropped` line for that delivery id whose reason
     starts with `invalid signature` (consumed and DROPPED, never recorded: webhook_consumer.process raises Dropped before
     forge_webhooks.record, so the registry cannot see it).
If either fails (or the request itself fails) the ACK path is not trusted: rollback() redeploys the stack from the same
template with --parameter-overrides AckPath=lambda, the route goes back to the tower-port-ingress Lambda, and the exit code
is 1 so the deploy is recorded as failed. The last line printed is one JSON object {ok, http_status, ms, body (300 chars, redacted), headers {apigw-requestid, content-type, x-amzn-errortype}, drop: verified|unverified|missing, reason}; an
unreadable consumer log is drop=unverified, a warning that never makes the smoke red. Exit 0: smoke passed, or AckPath is not sqs (nothing to prove). Exit 2: no verdict
(the stack outputs could not be read); no rollback is made on a missing verdict.
scripts/deploy-smoke (DEP7) may call run_smoke()/rollback() from here; infra/aws/deploy.sh calls scripts/ack-smoke itself.
Usage: scripts/ack-smoke [--stack tower-app-port] [--template infra/aws/stacks/40-port.json] [--role-arn ARN]
[--commit SHA] [--wait S] [--no-rollback]. Needs the aws CLI (cloudformation, logs) as the deployer role; prints no secret.
"""
import argparse
import http.client
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

# ACK-SMOKE-SIGNATURE: the forge's tag (forge_webhooks.TAG; a test keeps the two equal) and 64 bytes no key verifies. With the
# tag 'v1,' the consumer saw no signature at all and dropped the smoke as `400: a webhook needs ...`, not as `invalid signature`:
# the first time the deployer could read the consumer's log (09/11, build of 897f33dd) the smoke went red on that, rolled
# production back to AckPath=lambda and the guard kept it there for 19 hours.
SIGNATURE_TAG = 'v1ed,'
UNSIGNED = SIGNATURE_TAG + 'A' * 86 + '=='
ROUTE = '/v1/forge/origin/webhooks'  # forge_webhooks.PATH; a test keeps the two equal
ACK_LIMIT_S = 1.0
CONSUMER_LOG_GROUP = '/aws/lambda/tower-port-webhooks'
STACK = 'tower-app-port'
TEMPLATE = 'infra/aws/stacks/40-port.json'


def run_aws(argv):
    done = subprocess.run(['aws', *argv], capture_output=True, text=True)
    return done.returncode, done.stdout, done.stderr


def post(url, body, headers, timeout=10):
    """(status, seconds, {apigw-requestid, content-type, x-amzn-errortype, body}) of one POST; a connection failure is (None, seconds, {...}).
    http.client sends the header names exactly as given (urllib capitalises them: Webhook-Id); API Gateway resolves $request.header.<name> by the lowercase name."""
    parts = urllib.parse.urlsplit(url)
    connection_class = http.client.HTTPSConnection if parts.scheme == 'https' else http.client.HTTPConnection
    began = time.monotonic()
    info, status = {}, None
    connection = connection_class(parts.netloc, timeout=timeout)
    try:
        connection.request('POST', (parts.path or '/') + ('?' + parts.query if parts.query else ''), body=body, headers=headers)
        answer = connection.getresponse()
        status, info = answer.status, _info(answer, answer)
    except (http.client.HTTPException, OSError) as error:
        info = {'error': type(error).__name__}
    finally:
        connection.close()
    return status, time.monotonic() - began, info


def _info(answer, reader):
    try:
        text = reader.read(2000).decode('utf-8', 'replace')
    except (OSError, ValueError):
        text = ''
    return {'apigw-requestid': answer.headers.get('apigw-requestid'), 'content-type': answer.headers.get('content-type'),
            'x-amzn-errortype': answer.headers.get('x-amzn-ErrorType'), 'body': text}


def clean(text, limit=200):
    """The first `limit` characters of a body, without anything that looks like a secret (long tokens, key=value of a secret)."""
    text = re.sub(r'(?i)([\w-]*(token|secret|password|key|authorization|signature)[\w-]*["\']?\s*[:=]\s*)["\']?[^\s"\',;]{4,}',
                  r'\1[redacted]', str(text or ''))
    text = re.sub(r'[A-Za-z0-9+/_=-]{41,}', '[redacted]', text)
    return text.replace('\n', ' ')[:limit]


def outputs_of(runner, stack):
    code, out, _err = runner(['cloudformation', 'describe-stacks', '--stack-name', stack, '--query',
                              'Stacks[0].Outputs', '--output', 'json'])
    try:
        return {item['OutputKey']: item['OutputValue'] for item in json.loads(out or 'null') or []} if code == 0 else None
    except (ValueError, KeyError, TypeError):
        return None


def dropped(runner, delivery_id, since_ms):
    """(the consumer's drop line for this delivery or None, the aws error when the log could not be read or None)."""
    code, out, err = runner(['logs', 'filter-log-events', '--log-group-name', CONSUMER_LOG_GROUP, '--filter-pattern',
                              f'"{delivery_id}"', '--start-time', str(since_ms), '--output', 'json'])
    if code != 0:
        return None, (err.strip().splitlines() or ['aws logs failed'])[-1]
    try:
        events = json.loads(out or '{}').get('events') or []
    except ValueError:
        return None, 'unreadable aws logs answer'
    for event in events:
        try:
            line = json.loads(event.get('message', ''))
        except ValueError:
            continue
        if isinstance(line, dict) and line.get('webhook_dropped') and line.get('id') == delivery_id:
            return line, None
    return None, None


def run_smoke(outputs, *args, **kwargs):
    """(ok, [what happened]) for a stack whose outputs are `outputs`; check() has the structured result."""
    result, said = check(outputs, *args, **kwargs)
    return result['ok'], said


def check(outputs, runner=run_aws, poster=post, clock=time.time, sleep=time.sleep, wait_s=90, every_s=5,
          new_id=lambda: 'whd_smoke_' + uuid.uuid4().hex[:12]):
    """(result, [what happened]); result = {ok, http_status, ms, body (300 chars, redacted), headers {apigw-requestid, content-type, x-amzn-errortype}, drop: verified|unverified|missing, reason}.
    A drop that could not be observed because the log cannot be read is `unverified`: a warning, never a red."""
    if outputs.get('AckPath') != 'sqs':
        reason = f'AckPath={outputs.get("AckPath")}: the SQS ACK is not on, nothing to prove'
        return {'ok': True, 'http_status': None, 'ms': None, 'body': '', 'headers': {}, 'drop': 'unverified', 'reason': reason}, [reason]
    url = outputs.get('PortUrl', '').rstrip('/') + ROUTE
    delivery_id, now = new_id(), clock()
    body = json.dumps({'type': 'ack.smoke', 'note': 'deliberately unsigned; must be dropped'}).encode()
    headers = {'content-type': 'application/json', 'webhook-id': delivery_id, 'webhook-timestamp': str(int(now)),
               'webhook-signature': UNSIGNED}
    answer = poster(url, body, headers)
    status, seconds = answer[0], answer[1]
    info = answer[2] if len(answer) > 2 and isinstance(answer[2], dict) else {}
    said = [f'POST {url} -> {status} in {seconds:.3f} s']
    ok, drop, reasons = True, 'missing', []
    if status not in (200, 202):
        ok = False
        reasons.append(f'expected 200/202, got {status}')
        said.append(f'FAIL: expected 200/202, got {status}')
        said.append(f'response apigw-requestid={info.get("apigw-requestid")} content-type={info.get("content-type")}'
                    f' x-amzn-ErrorType={info.get("x-amzn-errortype")}' + (f' error={info["error"]}' if info.get('error') else ''))
        # ACK-SMOKE-400: the body of ANY non-2xx (a 400 in 22 ms said nothing), first 300 chars, redacted; '' is said as empty
        said.append(f'response body: {clean(info.get("body"), 300) or "(empty)"}')
    if seconds >= ACK_LIMIT_S:
        ok = False
        reasons.append(f'the ACK took {seconds:.3f} s, the limit is {ACK_LIMIT_S} s')
        said.append(f'FAIL: the ACK took {seconds:.3f} s, the limit is {ACK_LIMIT_S} s')
    if status in (200, 202):  # a refused request queued nothing, so there is nothing to wait for
        waited = 0
        line, unreadable = dropped(runner, delivery_id, int(now * 1000) - 5000)
        while line is None and not unreadable and waited < wait_s:
            sleep(every_s)
            waited += every_s
            line, unreadable = dropped(runner, delivery_id, int(now * 1000) - 5000)
        if unreadable:  # e.g. the deployer role lacks logs:FilterLogEvents: the ACK half is still proved, this half is not
            drop = 'unverified'
            reasons.append(f'consumer log unreadable ({clean(unreadable)}): drop unverified')
            said.append(f'UNVERIFIED: the consumer log cannot be read ({unreadable}); the drop was not observed')
        elif line is None:
            ok = False
            reasons.append(f'no webhook_dropped line after {wait_s} s')
            said.append(f'FAIL: no webhook_dropped line for {delivery_id} in {CONSUMER_LOG_GROUP} after {wait_s} s')
        elif not str(line.get('reason', '')).startswith('invalid signature'):
            ok = False
            reasons.append(f'dropped for the wrong reason: {clean(line.get("reason"))}')
            said.append(f'FAIL: dropped for the wrong reason: {line.get("reason")}')
        else:
            drop = 'verified'
            reasons.append('dropped by the consumer: ' + clean(line['reason']))
            said.append(f'dropped by the consumer: {line["reason"]}')
    headers_seen = {k: clean(info.get(k), 120) for k in ('apigw-requestid', 'content-type', 'x-amzn-errortype') if info.get(k)}
    result = {'ok': ok, 'http_status': status, 'ms': int(seconds * 1000), 'body': clean(info.get('body'), 300),
              'headers': headers_seen, 'drop': drop, 'reason': '; '.join(reasons)[:300]}
    return result, said


def rollback(runner, stack=STACK, template=TEMPLATE, role_arn=None, commit=None):
    """Redeploy the stack from the same template with AckPath=lambda; (ok, output tail). The route returns to the
    tower-port-ingress Lambda (kept whole in the template); the consumer still records both formats."""
    argv = ['cloudformation', 'deploy', '--stack-name', stack, '--template-file', template,
            '--capabilities', 'CAPABILITY_NAMED_IAM', '--no-fail-on-empty-changeset',
            '--parameter-overrides', 'AckPath=lambda', '--tags', 'project=tower']
    if commit:
        argv[-1:] = ['project=tower', f'commit={commit}']
    if role_arn:
        argv[4:4] = ['--role-arn', role_arn]
    code, out, err = runner(argv)
    return code == 0, (out + err).strip()[-300:]


def main(argv=None, runner=run_aws, poster=post, sleep=time.sleep, out=print):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--stack', default=STACK)
    parser.add_argument('--template', default=TEMPLATE)
    parser.add_argument('--role-arn')
    parser.add_argument('--commit')
    parser.add_argument('--wait', type=int, default=90)
    parser.add_argument('--no-rollback', action='store_true')
    args = parser.parse_args(argv)
    outputs = outputs_of(runner, args.stack)
    if outputs is None:
        out(f'ack-smoke: cannot read the outputs of {args.stack}; no verdict, no rollback')
        return 2
    result, said = check(outputs, runner, poster, sleep=sleep, wait_s=args.wait)
    for line in said:
        out('ack-smoke: ' + line)
    code = 0
    if not result['ok']:
        code = 1
        if args.no_rollback:
            out('ack-smoke: FAILED; --no-rollback, AckPath stays sqs')
        else:
            done, tail = rollback(runner, args.stack, args.template, args.role_arn, args.commit)
            out('ack-smoke: FAILED; ' + ('rolled back: AckPath=lambda deployed'
                                          if done else f'ROLLBACK FAILED, set AckPath=lambda by hand: {tail}'))
    out(json.dumps(result, separators=(',', ':')))  # the final line: deploy.sh stores it in last-build.ack_smoke
    return code


if __name__ == '__main__':
    sys.exit(main())

"""LAMBDA-PRUNE (the review's finding 26): the port Lambdas' versions and the packages under artifacts/lambda/ stop piling up.

Every fast swap publishes a version of a port Lambda (DeletionPolicy Retain on the stack's versions too) and every authoring
push uploads its packages to artifacts/lambda/ (the functions' zips by digest, the dependency layers, the head manifests,
the tower-code bundles); only runs/ expired. A published version holds its own copy of the code (it counts against the
region's code storage), so the zip it came from is no longer what it runs. The live service's look, once a day:
  - versions: per function, keeps every version an alias names (its version and its routing weights), the newest
    KEEP_VERSIONS (the live one, the rollback ones before it and any just published), and the newest slow-path version
    (description 'slow deploy of ...': the stack's own, which a stack rollback goes back to); deletes the others;
  - packages: deletes an object under artifacts/lambda/ older than KEEP_DAYS that nothing names: not a version kept above
    (the slow path's description names its code and layer keys), not deploy.live_code (the bundle every task boots), not
    the current task definitions of the cluster's services and families (TOWER_CODE_KEY and every other key in their
    environment). When any of those reads fails, no package is deleted (the versions' part stands on the aliases alone).
It says platform.deploy.prune {state: done, versions, objects, bytes, kept, seconds}; the next pass is EVERY_S after it.
"""
import json
import logging
import re
import time
import uuid

LOG = logging.getLogger('tower_infra.prune')
EVENT = 'platform.deploy.prune'
# GATE-SHUTDOWN (D-314, #17): the ack-ingress and the webhook consumer left the port stack; the API is the port's one function
FUNCTIONS = ('tower-port-api',)
SERVICES = ('tower-service', 'tower-runner')
FAMILIES = ('tower-service', 'tower-service-standby', 'tower-runner')
PREFIX = 'artifacts/lambda/'
KEEP_VERSIONS, KEEP_DAYS, EVERY_S = 10, 30, 86400
SLOW = 'slow deploy of '
KEY = re.compile(r'artifacts/lambda/[A-Za-z0-9._/-]+?\.(?:zip|json)')
CODE = re.compile(r'([0-9a-f]{64})@[0-9a-f]{7,64}')
LAST = (f"select extract(epoch from max(occurred_at))::float8 from log.event where type = '{EVENT}' and tenant_id is null "
        "and payload->>'state' = 'done'")
LIVE_CODE = "select value #>> '{}' from work.config_value where key = 'deploy.live_code'"
SAY = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
       f"values (%(id)s, null, '{EVENT}', clock_timestamp(), 'prune', 'deploy/prune', %(payload)s::jsonb)")


def pages(call, key, marker='Marker', following='NextMarker', **asked):
    """Every item of a paginated AWS list (Lambda's Marker/NextMarker; S3's token with its own names)."""
    token = None
    while True:
        out = call(**asked, **({marker: token} if token else {}))
        yield from out.get(key) or []
        token = out.get(following)
        if not token:
            return


def doomed(versions, aliases, keep=KEEP_VERSIONS):
    """The numbered versions to delete: neither named by an alias, nor among the newest `keep`, nor the newest slow one."""
    numbered = sorted(int(item['Version']) for item in versions if item['Version'].isdigit())
    kept = set(numbered[-keep:]) if keep > 0 else set()
    slow = [int(item['Version']) for item in versions
            if item['Version'].isdigit() and (item.get('Description') or '').startswith(SLOW)]
    if slow:
        kept.add(max(slow))
    for alias in aliases:
        named = [alias.get('FunctionVersion')] + list(((alias.get('RoutingConfig') or {}).get('AdditionalVersionWeights')
                                                       or {}).keys())
        kept.update(int(each) for each in named if each and str(each).isdigit())
    return [number for number in numbered if number not in kept]


def stale(objects, named, now, days=KEEP_DAYS):
    """The objects to delete: older than `days` and not named."""
    limit = now - days * 86400
    return [item for item in objects if item['Key'] not in named and stamp(item['LastModified']) < limit]


def stamp(value):
    return value.timestamp() if hasattr(value, 'timestamp') else float(value)


class Prune:
    def __init__(self, lam, s3, ecs, bucket, cluster, clock=time.time, keep=KEEP_VERSIONS, days=KEEP_DAYS):
        self.lam, self.s3, self.ecs, self.bucket, self.cluster = lam, s3, ecs, bucket, cluster
        self.clock, self.keep, self.days, self.next_at = clock, keep, days, None

    def step(self, db):
        """One pass when EVERY_S has gone by since the last one the log says was done; None otherwise."""
        now = self.clock()
        if self.next_at is None:
            last = (db.rows(LAST) or [(None,)])[0][0]
            self.next_at = (float(last) + EVERY_S) if last is not None else now
        if now < self.next_at:
            return None
        said = self.run(db)
        self.next_at = self.clock() + EVERY_S
        return said

    def run(self, db):
        began = self.clock()
        deleted, kept, named = {}, {}, set()
        for function in FUNCTIONS:
            try:
                versions = list(pages(self.lam.list_versions_by_function, 'Versions', FunctionName=function))
                aliases = list(pages(self.lam.list_aliases, 'Aliases', FunctionName=function))
            except Exception as error:  # noqa: BLE001 - a function that is gone has no version to prune
                if 'ResourceNotFound' not in type(error).__name__ + str(error):
                    raise
                LOG.info('prune: %s does not exist: nothing of it to prune', function)
                continue
            gone = []
            for number in doomed(versions, aliases, self.keep):
                try:
                    self.lam.delete_function(FunctionName=function, Qualifier=str(number))
                    gone.append(number)
                except Exception as error:  # noqa: BLE001 - the next pass tries it again
                    LOG.warning('prune: version %s of %s not deleted: %s', number, function, error)
            deleted[function] = gone
            left = [item for item in versions if not (item['Version'].isdigit() and int(item['Version']) in gone)]
            kept[function] = sum(1 for item in left if item['Version'].isdigit())
            for item in left:
                named.update(KEY.findall(item.get('Description') or ''))
        objects, size, why = [], 0, None
        try:
            named |= self.referenced(db)
            listed = list(pages(self.s3.list_objects_v2, 'Contents', marker='ContinuationToken',
                                following='NextContinuationToken', Bucket=self.bucket, Prefix=PREFIX))
            objects = stale(listed, named, began, self.days)
            for start in range(0, len(objects), 1000):
                batch = objects[start:start + 1000]
                out = self.s3.delete_objects(Bucket=self.bucket, Delete={
                    'Objects': [{'Key': item['Key']} for item in batch], 'Quiet': True})
                failed = {item.get('Key') for item in out.get('Errors') or []}
                objects = [item for item in objects if item['Key'] not in failed]
            size = sum(int(item.get('Size') or 0) for item in objects)
        except Exception as error:  # noqa: BLE001 - fail-safe: no package is deleted without every reference read
            why = str(error)[:300]
            LOG.warning('prune: packages kept, a reference could not be read: %s', error)
            objects = []
        payload = {'state': 'done', 'versions': deleted, 'kept': kept, 'objects': len(objects), 'bytes': size,
                   'named': len(named), 'seconds': round(self.clock() - began, 3)}
        if why:
            payload['packages_skipped'] = why
        db.rows(SAY, {'id': f'{EVENT}:{uuid.uuid4()}', 'payload': json.dumps(payload)})
        LOG.info('prune: %s', payload)
        return payload

    def referenced(self, db):
        """The keys deploy.live_code and the cluster's current task definitions name (raises when one cannot be read)."""
        named = set()
        for (value,) in db.rows(LIVE_CODE):
            found = CODE.fullmatch((value or '').strip())
            if found:
                named.add(f'{PREFIX}tower-code/{found.group(1)}.zip')
        definitions = {service['taskDefinition'] for service in
                       self.ecs.describe_services(cluster=self.cluster, services=list(SERVICES)).get('services') or []
                       if service.get('taskDefinition')}
        for definition in sorted(definitions) + list(FAMILIES):
            try:
                found = self.ecs.describe_task_definition(taskDefinition=definition)['taskDefinition']
            except Exception as error:  # noqa: BLE001 - a family that does not exist names nothing
                if definition in FAMILIES and 'Unable to describe task definition' in str(error):
                    continue
                raise
            for container in found.get('containerDefinitions') or []:
                for item in container.get('environment') or []:
                    named.update(KEY.findall(item.get('value') or ''))
        return named


def start(scope, stop, wait, active=None, environ=None, make=None):
    """The look in a daemon thread (the live service's alone); None without the bucket and cluster (a local run). Its
    clients are made at its first active look."""
    import os
    import threading
    environ = os.environ if environ is None else environ
    bucket, cluster = environ.get('TOWER_ARTIFACT_BUCKET', '').strip(), environ.get('TOWER_STANDBY_CLUSTER', '').strip()
    if make is None and not (bucket and cluster):
        LOG.info('prune: off (no bucket or cluster)')
        return None

    def made():
        import boto3
        from botocore.config import Config
        config = Config(connect_timeout=3, read_timeout=30, retries={'max_attempts': 2})
        region = environ.get('AWS_REGION')
        return Prune(boto3.client('lambda', region_name=region, config=config),
                     boto3.client('s3', region_name=region, config=config),
                     boto3.client('ecs', region_name=region, config=config), bucket, cluster)
    look = None

    def loop():
        nonlocal look
        while not stop.is_set():
            if active is None or active():
                try:
                    look = look or (make or made)()
                    with scope() as db:
                        look.step(db)
                except Exception:  # noqa: BLE001 - the next notification looks again
                    LOG.exception('prune: look failed')
            wait(60)
    thread = threading.Thread(target=loop, name='prune', daemon=True)
    thread.start()
    return thread

"""The AI session executor (P4 F3; ARQUITETURA-ALVO §6): a job's brief runs as a cloud session of a subscription
(Claude Code, Codex, Cursor), launched, followed, resumed and ended by the infrastructure like any other run (D-305: the core's
unit is the execution of work, not an AI session).

A provider is the caller's, one per subscription: launch(spec) answers the session's id; follow(session) answers what
the session is now, {"state": "running" | "waiting" | "ended", "until": <ISO time a waiting quota resets>, "outcome",
"error", "result", "tokens": {<model>: <tokens>}, "usage": {<meter>: <quantity>}}, where usage carries what else the
session metered (an API call's tokens in and out and its seconds, api_sessions.py); resume(session) after its quota
reset; end(session) when its job was stopped or cancelled. The job's input is a data: URI of JSON, {"provider": "<name>", "brief": "<text>", ...}; the rest
is the provider's.

start(run) launches the session, records its id as the run's external_id and leaves the run handed over. follow(db), on
every tick of the service, renews each open session run's lease and moves it: a session waiting on its quota makes the
run and the job wait until the reset, then resumes it; a session that ended ends the run with its outcome, its result
and its tokens per model as run.usage (meters tokens:<model>, which the limits sum); a job stopped or cancelled ends its
session and its run. A provider that is not configured refuses the run, so a missing subscription never keeps the
service from running. The database is any object with rows(sql, params). Standard library only.
"""
from datetime import datetime, timezone

from . import forge, mechanisms, runner

OPEN = """select r.id::text, j.fencing_token, r.external_id, r.state, j.input_uri,
       j.wait_reason = 'limit' and not work.hold_over(j.id)
from work.run r join work.job j on j.lease_run_id = r.id join work.executor e on e.name = r.executor
where e.adapter = %(adapter)s and r.state in ('running', 'waiting') and r.external_id is not null
order by r.id"""
RECORD = 'update work.run set external_id = %(session)s where id = %(run)s::uuid and external_id is null returning id'
GONE = ('stopped', 'cancelled')


def understood(spec):
    return isinstance(spec, dict) and isinstance(spec.get('provider'), str) and isinstance(spec.get('brief'), str) \
        and bool(spec['brief'].strip())


def when(stamp):
    return datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))


class Sessions:
    def __init__(self, connect, providers, adapter='session', lease='15 minutes'):
        self.connect, self.providers, self.adapter, self.lease = connect, providers, adapter, lease

    def start(self, run):
        """Launch the run's session and leave the run handed over; or answer how it ended when it cannot start."""
        spec = forge.decode(run.get('input_uri'))
        if not understood(spec):
            return forge.failed('not_understood', 'a session job needs {"provider": "<name>", "brief": "<text>"}')
        provider = self.providers.get(spec['provider'])
        if provider is None:
            return forge.failed('refused', f"no provider {spec['provider']} is configured for this executor")
        try:
            session = str(provider.launch(spec))
        except Exception as error:  # noqa: BLE001 - no key, the account's limit, an API refusal: a refused run, named
            return forge.failed('refused', f'{type(error).__name__}: {error}')
        with self.connect() as db:
            db.rows(RECORD, {'run': run['run'], 'session': session})
            mechanisms.relay(db, run['run'], run['fence'], 'run.running', {'session': session})
        return None

    def follow(self, db, now=None):
        """One pass over the open session runs; answers {run: what happened to it}."""
        now, moved = now or datetime.now(timezone.utc), {}
        for run_id, fence, session, state, uri, held in db.rows(OPEN, {'adapter': self.adapter}):
            run = {'run': run_id, 'fence': int(fence)}
            provider = self.providers.get((forge.decode(uri) or {}).get('provider'))
            job = runner.renew(db, run, self.lease)
            if provider is None or job is None:  # a provider gone or a lease gone: the reaper has the run
                continue
            if job in GONE:
                provider.end(session)
                mechanisms.finish(db, run, {'outcome': job, 'error': job})
                moved[run_id] = job
                continue
            seen = provider.follow(session)
            if seen.get('state') == 'ended':
                usage = {f'tokens:{model}': count for model, count in (seen.get('tokens') or {}).items()}
                usage.update(seen.get('usage') or {})  # an API call's tokens in and out and its seconds (D-310)
                mechanisms.finish(db, run, {'outcome': seen.get('outcome', 'succeeded'), 'error': seen.get('error'),
                                            'result': seen.get('result'), 'usage': usage})
                moved[run_id] = 'ended'
            elif held in (True, 't'):  # a wait limit (AWS12) holds the run until its reset: the provider does not resume it
                continue
            elif seen.get('state') == 'waiting' and state != 'waiting':
                mechanisms.relay(db, run_id, run['fence'], 'run.waiting', {'until': seen.get('until'),
                                                                           'reason': 'quota'})
                moved[run_id] = 'waiting'
            elif seen.get('state') == 'waiting' and seen.get('until') and now >= when(seen['until']):
                provider.resume(session)
                mechanisms.relay(db, run_id, run['fence'], 'run.running', {'session': session, 'resumed': True})
                moved[run_id] = 'resumed'
            elif seen.get('state') == 'running' and state == 'waiting':
                mechanisms.relay(db, run_id, run['fence'], 'run.running', {'session': session, 'resumed': True})
                moved[run_id] = 'resumed'
        return moved

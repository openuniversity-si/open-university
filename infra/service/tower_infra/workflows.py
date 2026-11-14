"""The dispatcher of the service on DBOS (P3 F3): one workflow per run, started by a loop that reaps and dispatches.

Every tick gives back the jobs whose lease expired and dispatches what can go now (tower_infra.mechanisms). Each claimed
run becomes the workflow run_job, whose workflow id is the run id, so a run is handed to its executor once even when the
loop or the whole service starts again: DBOS answers the existing workflow, and recovers the one a dead service left in
the middle. run_job hands the run to its executor's adapter; an adapter that finishes at once answers how it ended and
run_job ends the run, one that works outside relays and ends the run later through the database. An adapter that is
not registered leaves its run to expire, so a job never runs on a guess; the executors of P4 register here.
Only in the image: DBOS.
"""
import contextlib
import time

from dbos import DBOS, SetWorkflowID

from . import database, mechanisms

ADAPTERS = {}
LEFT = []  # LAUNCH-AFTER-CLAIM: claimed runs whose workflows wait for a launch that failed
ENGINE = {}


def register(name, adapter):
    """An adapter is an object with start(run) -> None, or {'outcome', 'error', 'result', 'signature'} when it ended."""
    ADAPTERS[name] = adapter


@contextlib.contextmanager
def connected():
    raw = ENGINE['engine'].raw_connection()
    try:
        yield database.Database(raw.driver_connection)
    finally:
        raw.close()


@DBOS.step()
def hand_over(run):
    adapter = ADAPTERS.get(run['adapter'])
    return None if adapter is None else adapter.start(run)


@DBOS.step()
def finish(run, ended):
    signature = ended.get('signature')
    with connected() as db:
        return mechanisms.finish(db, run, ended, bytes.fromhex(signature) if signature else None)


@DBOS.workflow()
def run_job(run):
    ended = hand_over(run)
    return finish(run, ended) if ended else 'handed over'


def tick(lease, dispatched=None, scope=None, first=None, clock=time.monotonic, launch=None, reap_after=False):
    """One pass of the loop: reap, dispatch, and start the workflow of every claimed run; answers the runs started.
    dispatched(parts) runs once the claims are committed, before the workflows start (IMAGE-SWAP-SERVICE-READY: the
    service's image_live is recorded there). IMAGE-SWAP-TICK: scope gives the pass its connection (the loop's own kept
    one; None: a pooled one, as before); first() is called when the pass's first claim is committed, while it goes on
    claiming; parts times the pass: connect_s (until it has a usable connection), reap_s, dispatch_s (the dispatch until
    its first committed claim, or all of it when it claimed nothing), pass_s (the three, with every claim) and jobs (how
    many it claimed or answered from the cache). LAUNCH-AFTER-CLAIM: launch() runs after dispatched and before the
    workflows start (a late service's DBOS.launch: the claims are the role's work, the workflows need DBOS).
    SWAP-SECOND: reap_after (a late service's first pass) claims first and reaps after: the reap gives back leases that
    ended (a pass later is no loss), and it was 0.11 to 0.25 s before the first claim at the drills of 12/11."""
    began, firsts = clock(), []

    def claimed(_):
        if not firsts:
            firsts.append(clock())
            if first is not None:
                first()
    with (scope or connected)() as db:
        ready = clock()
        if not reap_after:
            mechanisms.reap(db)
        reaped = clock()
        made = mechanisms.dispatch(db, lease, claimed=claimed)
        if reap_after:
            mechanisms.reap(db)
        ended = clock()
    if dispatched is not None:
        dispatched({'connect_s': ready - began, 'reap_s': reaped - ready, 'dispatch_s': (firsts or [ended])[0] - reaped,
                    'pass_s': ended - began, 'jobs': len(made)})
    if launch is not None:
        try:
            launch()
        except Exception:
            # LAUNCH-AFTER-CLAIM: the claims are committed and DBOS could not be launched: their workflows start at the
            # next pass, after a launch that works, never lost to their lease's end
            LEFT.extend(run for run in made if not run['cached'])
            raise
    started = []
    while LEFT:
        run = LEFT.pop(0)
        with SetWorkflowID(run['run']):
            DBOS.start_workflow(run_job, run)
        started.append(run['run'])
    for run in made:
        if run['cached']:
            continue
        with SetWorkflowID(run['run']):
            DBOS.start_workflow(run_job, run)
        started.append(run['run'])
    return started

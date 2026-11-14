"""MERGE-READY (criterion 2: the landing's merge): the merge of the base's train front started ahead, at its join.

A delivery joins the base's train (platform.train.joined; work.train NOTIFYs tower_train) 4.1 to 4.4 s before its landing's
run (13/11 23:57 to 00:35 UTC: the gate is in between). At each wake of tower_train, and each minute, the live service reads
the front of the base's queue and asks the forge to have its merge ready (forge.OriginForge.ready: the CLI started, waiting
for its body in a FIFO); with no front, the one kept is stopped. The landing releases it (forge.OriginForge.released).
"""
import logging
import threading

from .pregate import REPO, TENANT_ID
from . import engine  # ENGINE-REPO

LOG = logging.getLogger('tower_infra.merge_ready')
BASE = 'mod/roadmap-integration'
FRONT = ("select pr, head from work.train where tenant_id = %(tenant)s::uuid and base = %(base)s and ended_at is null "
         "and lease_until > clock_timestamp() order by id limit 1")


class Look:
    @property
    def repo(self):
        """ENGINE-REPO: the one given, else the engine's repository as configured now (engine.repo())."""
        return self._repo or engine.repo()

    def __init__(self, forge, base=BASE, repo=None, tenant=None):
        from . import config_data
        self.forge, self.base, self._repo = forge, base, repo
        self.tenant, self.tenant_id = tenant or config_data.TENANT, None

    def step(self, db):
        """The front's merge made ready; (pr, head) or None when the queue is empty (the kept one is stopped then)."""
        if self.tenant_id is None:
            found = db.rows(TENANT_ID, {'tenant': self.tenant})
            self.tenant_id = found[0][0] if found else None
            if self.tenant_id is None:
                return None
        rows = db.rows(FRONT, {'tenant': self.tenant_id, 'base': self.base})
        if not rows:
            with self.forge.lock:
                self.forge.drop()
            return None
        pr, head = str(rows[0][0]), str(rows[0][1])
        self.forge.ready(self.repo, pr, head)
        return pr, head


def start(scope, stop, wait, forge, active=None):
    """The look in a daemon thread, woken by tower_train."""
    look = Look(forge)
    import atexit

    def dropped():  # MERGE-READY-ORPHAN: a process that ends leaves no merge waiting behind it
        with forge.lock:
            forge.drop()
    atexit.register(dropped)

    def loop():
        while not stop.is_set():
            if active is None or active():
                try:
                    with scope() as db:
                        look.step(db)
                except Exception:  # noqa: BLE001 - the next wake looks again; a landing merges as before without it
                    LOG.exception('merge_ready: look failed')
            else:  # not the live role (a standby, a successor not yet promoted): nothing kept
                with forge.lock:
                    forge.drop()
            wait(60)
        with forge.lock:
            forge.drop()
    thread = threading.Thread(target=loop, name='merge-ready', daemon=True)
    thread.start()
    return thread

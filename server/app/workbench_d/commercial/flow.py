"""Optional project-wide submission fence. Standalone D keeps its original API."""
import json
import os
import time
from contextlib import contextmanager


def initialize(store):
    with guard(store,create=True):pass
    with store.connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS execution_members(build TEXT PRIMARY KEY,epoch INTEGER);
        """)


def state(store, db=None):
    path=store.root/'flow-state.json'
    if not path.is_file():return None
    return json.loads(path.read_text(encoding='utf8'))


@contextmanager
def guard(store,create=False):
    """Short dispatch fence independent of long draft/export transactions."""
    path=store.root/'flow-state.json'
    if not path.is_file() and not create:
        yield None
        return
    lock=open(store.root/'flow.lock','a+b')
    try:
        if os.name=='nt':
            import msvcrt
            if os.fstat(lock.fileno()).st_size==0:lock.write(b'0');lock.flush()
            lock.seek(0)
            started=time.monotonic()
            while True:
                try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);break
                except OSError:
                    if time.monotonic()-started>30:raise
                    time.sleep(.01)
        else:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX)
        before=state(store)
        value=dict(before or {'epoch':0,'stopped':False})
        yield value
        if before!=value:
            temporary=store.root/('flow-'+str(os.getpid())+'.partial')
            with temporary.open('w',encoding='utf8') as output:
                json.dump(value,output);output.flush();os.fsync(output.fileno())
            os.replace(temporary,path)
    finally:lock.close()


def stop(store):
    with guard(store,create=True) as fence:
        if not fence['stopped']:fence.update(epoch=fence['epoch']+1,stopped=True)
    with store.connect() as db:
        rows=db.execute("SELECT id FROM builds WHERE status IN ('queued','running')").fetchall()
    return {**state(store),"builds":[r[0] for r in rows]}


def resume(store, epoch):
    with guard(store) as fence:
        if not fence or fence['epoch'] != epoch:
            raise ValueError("STOP_EPOCH_CHANGED: a new quote and user authorization are required")
        fence['stopped']=False


def admit(store, db, expected=None):
    current = state(store, db)
    if current and (current["stopped"] or expected is not None and expected != current["epoch"]):
        raise ValueError("FLOW_STOPPED: new work requires an exact quote authorization")
    return current


def dispatch_allowed(store, db, build, current=None):
    current = current if current is not None else state(store)
    b = db.execute("SELECT cancel FROM builds WHERE id=?", (build,)).fetchone()
    if b and b[0]:
        return False
    if current:
        member = db.execute("SELECT epoch FROM execution_members WHERE build=?", (build,)).fetchone()
        return not current["stopped"] and member is not None and member[0] == current["epoch"]
    return True

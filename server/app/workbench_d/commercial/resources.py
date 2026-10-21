"""One cross-process heavy slot; nested work reuses its owner's lease.

The OS lock, not an expired timestamp, grants ownership. A dead owner's verified
children must disappear before takeover. CPU affinity covers Python and inherited
children; Windows Jobs additionally fence child trees. RSS is aggregate process
RSS (shared pages can be counted twice), with a watchdog rather than a false
claim that FFmpeg thread count bounds the whole operation.
"""
import contextvars,json,os,tempfile,threading,time,uuid
from contextlib import contextmanager
from pathlib import Path
import psutil

_active=contextvars.ContextVar('d_heavy_lease',default=None)
POLICY={'version':1,'slots':1,'cpu_cores':4,'memory_bytes':4*1024**3,
        'decoder_threads':2,'filter_threads':2,'max_video_inputs':4,
        'max_audio_inputs':8,'max_static_states':32,'filter_buffered_frames':64}

def current():return _active.get()
def root():
    path=Path(os.environ.get('D_HEAVY_ROOT') or Path(tempfile.gettempdir())/'workbench-d-heavy-v1').resolve()
    path.mkdir(parents=True,exist_ok=True);return path

def write(path,value):
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.partial')
    with tmp.open('w',encoding='utf8') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)

def _lock(f):
    if os.name=='nt':
        import msvcrt
        f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
    else:
        import fcntl
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)

def _same(record):
    try:
        p=psutil.Process(record['pid'])
        return p if abs(p.create_time()-record['created'])<.01 else None
    except (psutil.NoSuchProcess,psutil.AccessDenied):return None

def _reap(state,check):
    # Only the previous token's recorded, creation-time-matched trees.
    targets=[]
    for child in state.get('children',[]):
        p=_same(child)
        if p:
            targets.extend(p.children(recursive=True));targets.append(p)
    for p in targets:
        try:p.kill()
        except psutil.NoSuchProcess:pass
    deadline=time.monotonic()+10
    while any(p.is_running() for p in targets):
        check()
        if time.monotonic()>deadline:raise RuntimeError('Previous heavy tree did not exit; slot not reused')
        time.sleep(.05)

class Lease:
    def __init__(self,path,category,check,wait):
        self.path=path;self.parent=psutil.Process();self.check_callback=check;self.started=time.perf_counter()
        self.token=uuid.uuid4().hex;self.mutex=threading.RLock();self.done=threading.Event()
        self.error=None;self.trees=[];self.old_affinity=self.parent.cpu_affinity()
        self.cpus=self.old_affinity[:POLICY['cpu_cores']]
        if not self.cpus:raise RuntimeError('Cannot determine an enforceable CPU affinity')
        self.parent.cpu_affinity(self.cpus)
        cpu=self.parent.cpu_times();self.cpu_start=cpu.user+cpu.system
        self.metrics={'category':category,'wait_seconds':wait,'peak_tree_rss_bytes':0,
                      'children_cpu_seconds':0.,'sample_seconds':.05,'policy':POLICY,
                      'affinity':self.cpus,'commands':0,'memory_enforcement':'Windows child Job hard limit plus whole-tree RSS watchdog; parent allocation checked cooperatively'}
        self.state={'token':self.token,'pid':self.parent.pid,'created':self.parent.create_time(),'category':category,
                    'children':[],'heartbeat':time.time(),'status':'active'}
        try:
            write(path,self.state)
            self.thread=threading.Thread(target=self.monitor,daemon=True);self.thread.start()
        except BaseException:
            self.parent.cpu_affinity(self.old_affinity)
            raise
    def monitor(self):
        last=0
        while not self.done.wait(.05):
            try:
                total=0
                for p in [self.parent,*self.parent.children(recursive=True)]:
                    try:total+=p.memory_info().rss
                    except psutil.NoSuchProcess:pass
                self.metrics['peak_tree_rss_bytes']=max(total,self.metrics['peak_tree_rss_bytes'])
                if total>POLICY['memory_bytes']:raise MemoryError('Heavy operation exceeded whole-tree RSS budget')
                if time.monotonic()-last>=1:
                    with self.mutex:
                        saved=json.loads(self.path.read_text())
                        if saved['token']!=self.token:raise InterruptedError('Heavy lease owner changed')
                        self.state['heartbeat']=time.time();write(self.path,self.state)
                    last=time.monotonic()
            except Exception as exc:
                self.error=exc
                # Stop native work immediately; Python observes the error at its next checkpoint.
                for tree in list(self.trees):
                    try:tree.terminate()
                    except Exception:pass
                return
    def check(self):
        self.check_callback()
        if self.error:raise self.error
    def register(self,tree):
        try:
            process=psutil.Process(tree.process.pid)
            record={'pid':process.pid,'created':process.create_time()}
        except psutil.NoSuchProcess:record=None
        with self.mutex:
            self.trees.append(tree);self.metrics['commands']+=1
            if record:self.state['children'].append(record)
            if not self.owns_record():raise InterruptedError('Heavy lease owner changed before media registration')
            write(self.path,self.state)
    def finished(self,tree,stats):
        with self.mutex:
            if tree in self.trees:self.trees.remove(tree)
            self.metrics['children_cpu_seconds']+=stats.get('cpu_seconds',0)
            self.state['children']=[r for r in self.state['children'] if r['pid']!=tree.process.pid]
            if self.owns_record():write(self.path,self.state)
    def owns_record(self):
        try:return json.loads(self.path.read_text())['token']==self.token
        except (OSError,ValueError,KeyError):return False
    def summary(self):
        cpu=self.parent.cpu_times()
        return {**self.metrics,'wall_seconds':time.perf_counter()-self.started,
                'tree_cpu_seconds':cpu.user+cpu.system-self.cpu_start+self.metrics['children_cpu_seconds']}
    def close(self):
        self.done.set();self.thread.join(timeout=2)
        try:
            for tree in list(self.trees):tree.close()
        finally:
            self.parent.cpu_affinity(self.old_affinity)
            self.state.update(status='cleanup_failed' if self.trees else 'released',metrics=self.summary(),heartbeat=time.time())
            if self.owns_record():write(self.path,self.state)

@contextmanager
def slot(category='media',check=lambda:None,progress=lambda **kw:None):
    existing=current()
    if existing:
        existing.check();check();yield existing;return
    directory=root();f=(directory/'heavy.lock').open('a+b')
    if os.fstat(f.fileno()).st_size==0:f.write(b'0');f.flush()
    started=time.perf_counter();lease=None;context=None
    try:
        while True:
            check()
            try:_lock(f);break
            except (OSError,BlockingIOError):
                progress(stage='waiting_local',resource='heavy-slot')
                time.sleep(.1)
        state_path=directory/'owner.json'
        if state_path.is_file():_reap(json.loads(state_path.read_text()),check)
        lease=Lease(state_path,category,check,time.perf_counter()-started)
        context=_active.set(lease)
        yield lease
        lease.check()
    finally:
        try:
            if lease:lease.close()
        finally:
            if context is not None:_active.reset(context)
            f.close()

def scoped_check(store):
    from .flow import state
    initial=state(store)
    def check():
        now=state(store)
        if initial and now and now['epoch']!=initial['epoch']:raise InterruptedError('Project stopped during local work')
    return check

def heavy(method):
    """Public engine/draft entry acquires BEFORE its transaction."""
    from functools import wraps
    @wraps(method)
    def invoke(self,*args,**kwargs):
        with slot(method.__name__,scoped_check(self.store)):
            return method(self,*args,**kwargs)
    return invoke


def operation(category):
    """Free-function heavy work, including its Python stage, shares the same slot."""
    import inspect
    from functools import wraps
    def decorate(fn):
        signature=inspect.signature(fn)
        @wraps(fn)
        def invoke(*args,**kwargs):
            bound=signature.bind(*args,**kwargs);bound.apply_defaults()
            with slot(category,bound.arguments.get('check',lambda:None)) as lease:
                if 'check' in signature.parameters:bound.arguments['check']=lease.check
                return fn(*bound.args,**bound.kwargs)
        return invoke
    return decorate

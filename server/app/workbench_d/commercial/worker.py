"""Detached worker. A renewable lease fences status commits across restarts."""
from copy import deepcopy
import json, os, sys, threading
from pathlib import Path
from .store import Store,canonical
from .schema import Project
from .render import render,sha,identity
from .capture import capture


def run(build_id,store=None):
    store=store or Store();token=store.claim(build_id)
    if token is None: return
    done=threading.Event();lost=threading.Event()
    def heartbeat():
        while not done.wait(1):
            try:
                if not store.heartbeat(build_id,token):lost.set();return
            except Exception:lost.set();return
    thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
    def check():
        if lost.is_set(): raise InterruptedError('cancelled or execution lease lost')
        with store.connect() as db:
            from .flow import dispatch_allowed
            if not dispatch_allowed(store,db,build_id):raise InterruptedError('global flow stopped or superseded')
            b=store.build(build_id,db)
            if b['cancel'] or b['owner']!=token: raise InterruptedError('cancel requested or execution lease lost')
    def checkpoint(node,value):
        check()
        with store.transaction() as db:
            b=store.build(build_id,db)
            if b['cancel'] or b['owner']!=token: raise InterruptedError('lease lost before checkpoint')
            db.execute("UPDATE nodes SET status='succeeded',result=? WHERE build=? AND id=?",(canonical(value),build_id,node))
            store.event(db,build_id,'node_completed',{'node':node})
    try:
        b=store.build(build_id);spec=deepcopy(b['spec'])
        if identity(any(t['kind']=='capture' for t in spec['tasks']))!=b['identity']: raise ValueError('runtime identity changed; create a new frozen build')
        # Fenced attempts never write the same directory after lease expiry.
        base=store.root/'builds'/build_id/f'attempt-{b["attempt"]}';base.mkdir(exist_ok=True,parents=True)
        completed={n['id']:n['result'] for n in b['nodes'] if n['status']=='succeeded'}
        for key,value in completed.items():
            if not Path(value['path']).is_file() or sha(value['path'])!=value['sha256']: raise ValueError(f'checkpoint corrupted: {key}')
            for artifact in value.get('artifacts',[]):
                if not Path(artifact['path']).is_file() or sha(artifact['path'])!=artifact['sha256']:raise ValueError(f'checkpoint artifact corrupted: {key}')
        pending={t['id']:t for t in spec['tasks']}
        while pending:
            ready=[t for t in pending.values() if set(t['depends_on'])<=completed.keys()]
            if not ready: raise ValueError('unresolvable execution graph')
            for task in ready:
                check();tid=task['id']
                if tid not in completed:
                    assets={a['id']:a for a in spec['assets']}
                    inputs=[assets[ref] for ref in task['inputs']]
                    execution=dict(tool={'capture':'Playwright / Chromium','media':'D media / FFmpeg / Pillow','speech':'D isolated model adapter','generation':'D provider adapter'}[task['kind']],operation=task['operation'],provider=task['provider'],model=task['model'])
                    if task['kind']=='generation':
                        from .providers import config_for
                        config,model=config_for(task);execution['model']=model.get('wire_model',task['model'])
                    if task['kind']=='speech':
                        from .speech import adapters
                        adapter=adapters().get(task['provider'],{});execution['adapterHash']=adapter.get('script_sha256');execution['weightHashes']=[w.get('sha256') for w in adapter.get('weights',[])]
                    with store.transaction() as db:
                        owned=store.build(build_id,db)
                        if owned['owner']!=token or owned['cancel']:raise InterruptedError('lease lost before task execution')
                        db.execute("UPDATE nodes SET status='running',result=? WHERE build=? AND id=?",(canonical(dict(execution=execution)),build_id,tid))
                    if task['kind']=='capture':
                        from .schema import Capture
                        value=capture(Capture.model_validate(task['capture']),base/tid,check)
                    elif task['kind']=='media':
                        from .media import process
                        value=process(task,inputs,base/tid,check)
                    elif task['kind']=='speech':
                        from .speech import execute
                        value=execute(task,inputs,base/tid,check)
                    else:
                        from .providers import execute
                        value=execute(store,b,task,inputs,base/tid,check)
                    if task['kind']!='capture' and value['kind']!=task['output_kind']:raise ValueError('task result differs from declared output kind')
                    value['execution']=execution;checkpoint(tid,value);completed[tid]=value
                value=completed[tid]
                spec['assets'].append(dict(id=tid,path=value['path'],sha256=value['sha256'],kind=value['kind'],
                                           license='task-derived; source/provider rights remain applicable',source=task['capture']['url'] if task['kind']=='capture' else 'd-task:'+tid))
                del pending[tid]
        from .brand import requires_review
        spec['brand_review_required']=requires_review(spec)
        spec['tasks']=[];doc=Project.model_validate(spec)
        if '$render' in completed: result=completed['$render']
        else:
            with store.connect() as db:
                row=db.execute('SELECT document FROM render_plans WHERE build=?',(build_id,)).fetchone()
            plan=json.loads(row['document']) if row else None
            result=render(doc,base/'render',check,lambda **p:store.update(build_id,token,progress=p),plan=plan,cache_root=store.root/'static-cache')
            checkpoint('$render',result)
        check();store.update(build_id,token,status='succeeded',result=result,owner=None,lease=0)
    except Exception as exc:
        try:
            terminal='cancelled' if isinstance(exc,InterruptedError) else 'failed'
            with store.transaction() as db:
                owned=store.build(build_id,db)
                if owned['owner']==token:db.execute("UPDATE nodes SET status=? WHERE build=? AND status='running'",(terminal,build_id))
            store.update(build_id,token,status=terminal,error=str(exc),owner=None,lease=0)
        except RuntimeError: pass # Another lease owns the task; never overwrite it.
    finally: done.set();thread.join(timeout=2)


if __name__=='__main__': run(sys.argv[1])

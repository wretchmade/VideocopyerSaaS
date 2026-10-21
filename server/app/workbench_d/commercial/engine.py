"""D-owned project and build service. No upstream CLI or source format dependency."""
from copy import deepcopy
import json, os, shutil, subprocess, sys, time
from pathlib import Path
from .store import Store,canonical,fingerprint,uid
from .schema import Project,upgrade
from .render import sha,identity
from .resources import heavy


class Engine:
    def __init__(self,root=None): self.store=Store(root)

    def snapshot_assets(self,document):
        value=upgrade(document).model_dump(mode='json')
        for asset in value['assets']:
            source=Path(asset['path']).expanduser().resolve()
            if not source.is_file() or sha(source)!=asset['sha256']: raise ValueError(f'asset missing or changed: {asset["id"]}')
            suffix=source.suffix.lower()
            if len(suffix)>10 or any(c not in '.abcdefghijklmnopqrstuvwxyz0123456789' for c in suffix): raise ValueError('invalid asset extension')
            target=self.store.root/'assets'/(asset['sha256']+suffix);target.parent.mkdir(exist_ok=True)
            if not target.is_file():
                temp=target.with_suffix('.'+uid()+'.partial');shutil.copyfile(source,temp)
                if sha(temp)!=asset['sha256']: temp.unlink();raise ValueError('asset changed while importing')
                os.replace(temp,target)
            if sha(target)!=asset['sha256']: raise ValueError('stored asset corrupted')
            asset['path']=str(target)
        return value

    def create(self,args):
        def operation(db):
            name=args.get('name','Untitled').strip()
            if not name or len(name)>255: raise ValueError('name must be 1..255 characters')
            doc=self.snapshot_assets(args.get('document',{})); pid=uid()
            db.execute('INSERT INTO projects VALUES(?,?,0)',(pid,name))
            db.execute('INSERT INTO revisions VALUES(?,?,?,?)',(pid,0,canonical(doc),fingerprint(doc)))
            return self.store.project(pid,db=db)
        return self.store.mutate(args.get('commandId'),{'op':'create',**args},operation)

    def edit(self,args):
        def operation(db):
            p=self.store.project(args['projectId'],db=db)
            if p['authorRevision']!=args['baseRevision']: raise ValueError('REVISION_CONFLICT: reload the project')
            doc=self.snapshot_assets(args['document']);rev=p['authorRevision']+1
            db.execute('INSERT INTO revisions VALUES(?,?,?,?)',(p['projectId'],rev,canonical(doc),fingerprint(doc)))
            db.execute('UPDATE projects SET revision=? WHERE id=?',(rev,p['projectId']))
            return self.store.project(p['projectId'],db=db)
        return self.store.mutate(args.get('commandId'),{'op':'edit',**args},operation)

    @heavy
    def check(self,args):
        from .resources import current
        check=current().check
        p=self.store.project(args['projectId'],args.get('revision'))
        document=upgrade(p['document'])
        for a in document.assets:
            check()
            if not Path(a.path).is_file() or sha(a.path)!=a.sha256: raise ValueError(f'asset changed: {a.id}')
        from .render import Rasterizer
        Rasterizer(document,self.store.root/'validation',check).prepare(decode=False)
        unsupported=[];limitations=[]
        from .providers import config_for,quote_task
        from .speech import adapters,ready,OPERATIONS as SPEECH
        from .media import OPERATIONS as MEDIA
        for t in document.tasks:
            try:
                if t.kind=='generation':
                    config,_=config_for(t.model_dump());q=quote_task(t.model_dump())
                    if not os.environ.get(config.get('credential_env','')):raise ValueError('credential reference unavailable')
                    if not q['ready']:raise ValueError('fresh quote required')
                elif t.kind=='media' and t.operation not in MEDIA:raise ValueError('unknown local media operation')
                elif t.kind=='speech':
                    config=adapters().get(t.provider,{})
                    if t.operation not in SPEECH or t.operation not in config.get('operations',[]) or not ready(config):raise ValueError('MODEL_NOT_READY: configured adapter and weights required')
            except ValueError as exc:unsupported.append(t.id);limitations.append(f'{t.id}: {exc}')
        from .brand import preflight
        return dict(valid=True,executable=not unsupported,projectId=p['projectId'],revision=p['authorRevision'],brand=preflight(document),
                    frames=document.frames,duration=document.fps.seconds(document.frames),
                    unsupported=unsupported,limitations=limitations)

    def plan(self,args):
        p=self.store.project(args['projectId'],args.get('revision'));check=self.check(args)
        nodes=[dict(id=t['id'],kind=t['kind'],depends_on=t['depends_on']) for t in p['document']['tasks']]
        nodes.append(dict(id='$render',kind='render',depends_on=[n['id'] for n in nodes]))
        from .providers import quote_task
        from .ledger import Ledger
        quotes=[]
        for task in p['document']['tasks']:
            if task['kind']=='generation':
                try:quotes.append(quote_task(task))
                except ValueError as exc:quotes.append(dict(task=task['id'],error=str(exc)))
        from .render_plan import choose
        return {**check,'nodes':nodes,'paidRequests':len(quotes),'quotes':quotes,'budgets':Ledger(self.store).budgets(p['projectId'],p['authorRevision']),'engine':identity(any(t['kind']=='capture' for t in p['document']['tasks'])),'documentHash':p['sha256'],'renderPlan':choose(upgrade(p['document']))}

    def submit(self,args,execution=None):
        payload={'op':'build',**args,**({'execution':execution} if execution else {})}
        # Completed command receipts remain readable even after quotes/runtime expire.
        if args.get('commandId'):
            with self.store.connect() as db:
                receipt=db.execute('SELECT payload,response FROM receipts WHERE id=?',(args['commandId'],)).fetchone()
            if receipt:
                if receipt['payload']!=fingerprint(payload):raise ValueError('IDEMPOTENCY_CONFLICT: commandId was used with a different payload')
                result=json.loads(receipt['response']);self.launch(result['buildId']);return result
        # Resource admission/preflight precedes any core write transaction.
        expected=self.store.project(args['projectId'],args.get('revision'))
        doc=upgrade(expected['document']);checked=self.check(args)
        if not checked['executable']:raise ValueError('; '.join(checked['limitations']))
        runtime=identity(any(t.kind=='capture' for t in doc.tasks))
        if execution and execution['runtime']!=runtime:raise ValueError('runtime changed after quote')
        from .render_plan import choose
        render_plan=choose(doc,frozen=(execution or {}).get('render_plan'))
        def operation(db):
            from .flow import admit
            flow=admit(self.store,db,execution.get('epoch') if execution else None)
            p=self.store.project(args['projectId'],args.get('revision'),db)
            if 'revision' not in args: raise ValueError('revision required for a frozen build')
            if p['sha256']!=expected['sha256']:raise ValueError('project changed during render preflight')
            key=fingerprint(dict(project=p['projectId'],revision=p['authorRevision'],spec=p['document'],runtime=runtime,**({'execution':execution} if execution else {})))
            prior=db.execute('SELECT id FROM builds WHERE fingerprint=?',(key,)).fetchone()
            if prior: return dict(buildId=prior['id'],projectId=p['projectId'],revision=p['authorRevision'])
            bid=uid()
            db.execute("INSERT INTO builds(id,project,revision,spec,identity,fingerprint,status) VALUES(?,?,?,?,?,?,'queued')",
                       (bid,p['projectId'],p['authorRevision'],canonical(p['document']),canonical(runtime),key))
            db.execute('INSERT INTO render_plans VALUES(?,?)',(bid,canonical(render_plan)))
            for node in [t.id for t in doc.tasks]+['$render']: db.execute("INSERT INTO nodes VALUES(?,?,'pending',NULL)",(bid,node))
            if flow:db.execute('INSERT INTO execution_members VALUES(?,?)',(bid,flow['epoch']))
            for node,value in (execution or {}).get('reuse',{}).items():
                if node not in {t.id for t in doc.tasks}:raise ValueError('unknown reuse node')
                if not Path(value['path']).is_file() or sha(value['path'])!=value['sha256']:raise ValueError('reused output changed')
                db.execute("UPDATE nodes SET status='succeeded',result=? WHERE build=? AND id=?",(canonical(value),bid,node))
            self.store.event(db,bid,'queued',{'revision':p['authorRevision']})
            return dict(buildId=bid,projectId=p['projectId'],revision=p['authorRevision'])
        result=self.store.mutate(args.get('commandId'),payload,operation)
        self.launch(result['buildId']);return result

    def launch(self,bid):
        row=self.store.build(bid)
        from .flow import state
        fence=state(self.store)
        if fence and fence['stopped']:return
        if row['status'] not in ('queued','running') or (row['owner'] and row['lease']>time.time()): return
        env={**os.environ,'D_CORE_DATA':str(self.store.root.parent)}
        api=Path(__file__).resolve().parents[3]
        env['PYTHONPATH']=str(api)+os.pathsep+env.get('PYTHONPATH','')
        log=self.store.root/'worker.log'
        with log.open('ab') as stream:
            subprocess.Popen([sys.executable,'-m','app.workbench_d.commercial.worker',bid],cwd=api,env=env,
                stdin=subprocess.DEVNULL,stdout=stream,stderr=stream,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),start_new_session=os.name!='nt')

    def status(self,bid):
        self.launch(bid)
        return self.store.build(bid)

    def recover(self):
        with self.store.connect() as db: ids=[r['id'] for r in db.execute("SELECT id FROM builds WHERE status IN ('queued','running')")]
        for bid in ids: self.launch(bid)
        return ids

    def cancel(self,args):
        def operation(db):
            b=self.store.build(args['buildId'],db)
            if b['status'] not in ('succeeded','failed','cancelled'):
                db.execute("UPDATE builds SET cancel=1,status=CASE WHEN owner IS NULL OR lease<? THEN 'cancelled' ELSE status END WHERE id=?",(time.time(),b['id']))
                self.store.event(db,b['id'],'cancel_requested',{})
            return dict(buildId=b['id'],cancelRequested=b['status'] not in ('succeeded','failed'))
        return self.store.mutate(args.get('commandId'),{'op':'cancel',**args},operation)

    def retry(self,args):
        payload={'op':'retry',**args}
        if args.get('commandId'):
            with self.store.connect() as db:
                receipt=db.execute('SELECT payload,response FROM receipts WHERE id=?',(args['commandId'],)).fetchone()
            if receipt:
                if receipt['payload']!=fingerprint(payload):raise ValueError('IDEMPOTENCY_CONFLICT: commandId was used with a different payload')
                result=json.loads(receipt['response']);self.launch(result['buildId']);return result
        frozen=self.store.build(args['buildId'])
        runtime=identity(any(t['kind']=='capture' for t in frozen['spec']['tasks']))
        def operation(db):
            from .flow import admit
            fence=admit(self.store,db)
            b=self.store.build(args['buildId'],db)
            if fence:
                member=db.execute('SELECT epoch FROM execution_members WHERE build=?',(b['id'],)).fetchone()
                if not member or member[0]!=fence['epoch']:raise ValueError('new execution authorization required after stop')
            if runtime!=b['identity']:raise ValueError('legacy runtime changed; preserve receipts and create a new revision')
            if b['status'] not in ('failed','cancelled'): raise ValueError('retry requires failed or cancelled build')
            db.execute("UPDATE builds SET status='queued',owner=NULL,lease=0,cancel=0,error=NULL WHERE id=?",(b['id'],))
            self.store.event(db,b['id'],'retry_requested',{})
            return dict(buildId=b['id'])
        result=self.store.mutate(args.get('commandId'),payload,operation);self.launch(result['buildId']);return result

    def deliver(self,args):
        def operation(db):
            b=self.store.build(args['buildId'],db)
            if b['status']!='succeeded': raise ValueError('delivery requires successful build')
            result=b['result'];source=Path(result['path'])
            if not source.is_file() or sha(source)!=result['sha256']: raise ValueError('delivery integrity check failed')
            from .brand import requires_review
            brand_review=None
            if requires_review(b['spec']):
                row=db.execute('SELECT * FROM brand_reviews WHERE build=? AND sha256=? AND approved=1',(b['id'],result['sha256'])).fetchone()
                if not row:raise ValueError('BRAND_REVIEW_REQUIRED: inspect the rendered branding and record d_review_brand_build before delivery')
                brand_review=dict(row)
            did=fingerprint({'commandId':args['commandId'],'buildId':b['id']})[:32]
            folder=self.store.root/'deliveries'/did;folder.mkdir(parents=True,exist_ok=True)
            target=folder/source.name;shutil.copyfile(source,target)
            receipt=dict(deliveryId=did,buildId=b['id'],projectId=b['project'],revision=b['revision'],path=str(target),sha256=sha(target),frames=result['frames'])
            if brand_review:receipt['brandReview']=brand_review
            (folder/'receipt.json').write_text(canonical(receipt),encoding='utf8')
            return receipt
        return self.store.mutate(args.get('commandId'),{'op':'deliver',**args},operation)

    @heavy
    def preview(self,args):
        from .render_artifacts import final_frame,composition_reference
        from .resources import current
        p=self.store.project(args['projectId'],args.get('revision'));doc=upgrade(p['document'])
        n=args.get('frame',0)
        if type(n)!=int or not 0<=n<doc.frames: raise ValueError('frame outside timeline')
        with self.store.connect() as db:
            built=db.execute("SELECT result FROM builds WHERE project=? AND revision=? AND status='succeeded' ORDER BY rowid DESC LIMIT 1",(p['projectId'],p['authorRevision'])).fetchone()
        if built:return {**final_frame(json.loads(built['result']),n,current().check),'revision':p['authorRevision']}
        if doc.tasks:raise ValueError('Render this task-backed revision before previewing a captured frame')
        folder=self.store.root/'previews'/p['projectId']/str(p['authorRevision']);folder.mkdir(exist_ok=True,parents=True)
        return {**composition_reference(doc,folder,n,current().check),'revision':p['authorRevision']}

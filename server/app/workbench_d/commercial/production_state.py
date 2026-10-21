"""D-owned review, visible-view receipts and portable workflow archives."""
from copy import deepcopy
from pathlib import Path
import json,time,shutil,os,re
from .store import canonical,fingerprint,uid
from .render import sha
from .schema import upgrade


def checked_file(path,digest):
    path=Path(path)
    if not path.is_file() or sha(path)!=digest:raise ValueError('file missing or changed: '+str(path))
    return path


class ProductionState:
    def __init__(self,engine):
        self.engine=engine;self.store=engine.store
        with self.store.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY,project TEXT,revision INTEGER,build TEXT,manifest TEXT);
            CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY,review TEXT,frame INTEGER,body TEXT,state TEXT,version INTEGER);
            CREATE TABLE IF NOT EXISTS feedback_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT,at REAL,body TEXT);
            CREATE TABLE IF NOT EXISTS feedback_sync(review TEXT,external TEXT,payload TEXT,PRIMARY KEY(review,external));
            CREATE TABLE IF NOT EXISTS views(project TEXT,revision INTEGER,version INTEGER,document TEXT,PRIMARY KEY(project,revision));
            CREATE TABLE IF NOT EXISTS visible_receipts(id TEXT PRIMARY KEY,project TEXT,revision INTEGER,document_hash TEXT,view_version INTEGER,session TEXT,at REAL);
            CREATE TABLE IF NOT EXISTS workflow_index(id TEXT PRIMARY KEY,name TEXT,manifest_hash TEXT,path TEXT);
            CREATE TABLE IF NOT EXISTS workflow_archives(id TEXT PRIMARY KEY,name TEXT,manifest_hash TEXT,path TEXT);
            ''')

    def mutate(self,op,args,fn):return self.store.mutate(args['commandId'],{'op':op,**args},fn)

    def prepare_studio(self,args):
        def apply(db):
            b=self.store.build(args['buildId'],db)
            if b['status']!='succeeded':raise ValueError('review needs a successful frozen build')
            source=checked_file(b['result']['path'],b['result']['sha256']);rid=fingerprint(args)[:32]
            folder=self.store.root/'reviews'/rid;folder.mkdir(parents=True,exist_ok=True);target=folder/('review'+source.suffix);shutil.copyfile(source,target)
            document=dict(reviewId=rid,projectId=b['project'],revision=b['revision'],buildId=b['id'],documentHash=fingerprint(b['spec']),media=dict(path=str(target),sha256=sha(target)),frames=b['spec']['frames'],fps=b['spec']['fps'])
            (folder/'review.json').write_text(canonical(document),encoding='utf8')
            from .review_copy import write
            portable=write(folder,document);document['portable']=dict(path=str(portable),sha256=sha(portable))
            db.execute('INSERT INTO reviews VALUES(?,?,?,?,?)',(rid,b['project'],b['revision'],b['id'],canonical(document)))
            return document
        return self.mutate('prepare_studio',args,apply)

    def review(self,rid,db):
        r=db.execute('SELECT manifest FROM reviews WHERE id=?',(rid,)).fetchone()
        if not r:raise ValueError('review not found')
        value=json.loads(r['manifest']);checked_file(value['media']['path'],value['media']['sha256']);return value

    def add_comment(self,db,review,frame,body):
        if type(frame)!=int or not 0<=frame<review['frames']:raise ValueError('feedback frame outside review')
        if not isinstance(body,str) or not body.strip() or len(body)>4000:raise ValueError('feedback needs 1..4000 characters')
        fid=uid();db.execute("INSERT INTO feedback VALUES(?,?,?,?,'open',0)",(fid,review['reviewId'],frame,body))
        self.feedback_event(db,fid,dict(action='created',body=body,frame=frame));return fid

    def feedback_event(self,db,fid,value):db.execute('INSERT INTO feedback_events(id,at,body) VALUES(?,?,?)',(fid,time.time(),canonical(value)))

    def add_feedback(self,args):
        def apply(db):
            review=self.review(args['reviewId'],db);fid=self.add_comment(db,review,args['frame'],args['body'])
            return dict(feedbackId=fid,version=0,state='open',**{k:review[k] for k in ('projectId','revision','buildId')})
        return self.mutate('add_feedback',args,apply)

    def feedback_state(self,args,state):
        def apply(db):
            row=db.execute('SELECT * FROM feedback WHERE id=?',(args['feedbackId'],)).fetchone()
            if not row:raise ValueError('feedback not found')
            if row['version']!=args['baseVersion']:raise ValueError('FEEDBACK_CONFLICT')
            db.execute('UPDATE feedback SET state=?,version=version+1 WHERE id=?',(state,row['id']));self.feedback_event(db,row['id'],dict(action=state,note=args.get('note','')))
            return dict(feedbackId=row['id'],version=row['version']+1,state=state)
        return self.mutate('feedback_'+state,args,apply)

    def get_feedback(self,args):
        with self.store.connect() as db:
            review=self.review(args['reviewId'],db)
            rows=[dict(r) for r in db.execute('SELECT * FROM feedback WHERE review=? ORDER BY frame,id',(args['reviewId'],))]
            for r in rows:r['events']=[{**dict(e),'body':json.loads(e['body'])} for e in db.execute('SELECT * FROM feedback_events WHERE id=? ORDER BY seq',(r['id'],))]
            return dict(review=review,comments=rows)

    def sync_feedback(self,args):
        def apply(db):
            review=self.review(args['reviewId'],db)
            if args['documentHash']!=review['documentHash']:raise ValueError('review revision hash mismatch')
            imported=[]
            for item in args['comments']:
                if not isinstance(item.get('externalId'),str) or not item['externalId']:raise ValueError('external comment id required')
                hashed=fingerprint(item);prior=db.execute('SELECT payload FROM feedback_sync WHERE review=? AND external=?',(review['reviewId'],item['externalId'])).fetchone()
                if prior:
                    if prior['payload']!=hashed:raise ValueError('SYNC_CONFLICT: external comment changed')
                    continue
                imported.append(self.add_comment(db,review,item['frame'],item['body']))
                db.execute('INSERT INTO feedback_sync VALUES(?,?,?)',(review['reviewId'],item['externalId'],hashed))
            return dict(imported=imported,revision=review['revision'])
        return self.mutate('sync_feedback',args,apply)

    def save_view(self,args):
        def apply(db):
            p=self.store.project(args['projectId'],args['revision'],db);v=args['view']
            if not isinstance(v,dict) or set(v)-{'viewport','groups'}:raise ValueError('invalid view fields')
            from .stage4_schema import CanvasView
            v=CanvasView.model_validate(v).model_dump(mode='json')
            task_ids={t['id'] for t in p['document']['tasks']};layer_ids={l['id'] for l in p['document']['layers']}
            ids={f'task:{id}' for id in task_ids}|{f'layer:{id}' for id in layer_ids}|(task_ids^layer_ids)
            members=[m for g in v['groups'] for m in g['members']]
            if len({g['id'] for g in v['groups']})!=len(v['groups']):raise ValueError('duplicate group id')
            if len(members)!=len(set(members)) or set(members)-ids:raise ValueError('duplicate or missing canvas member')
            for group in v['groups']:group['members']=[('task:' if m in task_ids else 'layer:')+m if ':' not in m else m for m in group['members']]
            normalized=[m for g in v['groups'] for m in g['members']]
            if len(normalized)!=len(set(normalized)):raise ValueError('duplicate canvas member aliases')
            row=db.execute('SELECT version FROM views WHERE project=? AND revision=?',(p['projectId'],p['authorRevision'])).fetchone();version=row['version'] if row else 0
            if args['baseVersion']!=version:raise ValueError('VIEW_CONFLICT')
            db.execute('INSERT OR REPLACE INTO views VALUES(?,?,?,?)',(p['projectId'],p['authorRevision'],version+1,canonical(v)))
            return dict(version=version+1,view=v)
        return self.mutate('save_view',args,apply)

    def canvas_status(self,args):
        with self.store.connect() as db:
            p=self.store.project(args['projectId'],args['revision'],db);row=db.execute('SELECT * FROM views WHERE project=? AND revision=?',(p['projectId'],p['authorRevision'])).fetchone()
            receipts=[dict(r) for r in db.execute('SELECT * FROM visible_receipts WHERE project=? AND revision=? ORDER BY at DESC LIMIT 20',(p['projectId'],p['authorRevision']))]
            default=dict(viewport=dict(x=0,y=0,zoom=1),groups=[dict(id='tasks',title='01 / 素材与模型',x=24,y=24,members=['task:'+t['id'] for t in p['document']['tasks']],collapsed=False),dict(id='composition',title='02 / 画面与字幕',x=390,y=24,members=['layer:'+l['id'] for l in p['document']['layers']],collapsed=False)])
            return dict(projectId=p['projectId'],revision=p['authorRevision'],documentHash=p['sha256'],version=row['version'] if row else 0,view=json.loads(row['document']) if row else default,visibleReceipts=receipts)

    def record_view(self,args):
        def apply(db):
            p=self.store.project(args['projectId'],args['revision'],db)
            if args['documentHash']!=p['sha256']:raise ValueError('displayed document hash mismatch')
            row=db.execute('SELECT version FROM views WHERE project=? AND revision=?',(p['projectId'],p['authorRevision'])).fetchone()
            if args['viewVersion']!=(row['version'] if row else 0):raise ValueError('displayed view version mismatch')
            if not args['session'] or args['visibility']!='visible':raise ValueError('visible browser session required')
            rid=uid();db.execute('INSERT INTO visible_receipts VALUES(?,?,?,?,?,?,?)',(rid,p['projectId'],p['authorRevision'],p['sha256'],args['viewVersion'],args['session'],time.time()))
            return dict(receiptId=rid,revision=p['authorRevision'],evidence='browser rendered+visible acknowledgement; not proof of human attention')
        return self.mutate('record_view',args,apply)

    def archive_workflow(self,args):
        def apply(db):
            p=self.store.project(args['projectId'],args['revision'],db);wid=fingerprint(args)[:32];folder=self.store.root/'workflows'/wid;folder.mkdir(parents=True,exist_ok=True)
            doc=deepcopy(p['document'])
            def no_credentials(value):
                if isinstance(value,dict):
                    if any(re.sub('[^a-z]','',k.lower()) in ('apikey','accesstoken','refreshtoken','authorization','password','secret','privatekey','credentials') for k in value):raise ValueError('workflow cannot archive credential fields')
                    for item in value.values():no_credentials(item)
                elif isinstance(value,list):
                    for item in value:no_credentials(item)
            no_credentials(doc)
            for asset in doc['assets']:
                source=checked_file(asset['path'],asset['sha256']);relative='assets/'+asset['sha256']+source.suffix
                target=folder/relative;target.parent.mkdir(exist_ok=True);shutil.copyfile(source,target);asset['path']=relative
            for task in doc['tasks']:task['provider']=None if task['kind'] in ('generation','speech') else task['provider'];task['budget']=None;task['max_cost_micros']=0
            parameters=args.get('parameterDeclarations',[])
            for parameter in parameters:self.validate_parameter(parameter['path'])
            dependencies=dict(projectFormat=1,components=sorted({l['component'] for l in doc['layers'] if l['kind']=='component'}),operations=[dict(kind=t['kind'],operation=t['operation'],model=t['model']) for t in doc['tasks']],implementation={f.name:sha(f) for f in Path(__file__).parent.glob('*.py')})
            manifest=dict(format='d-workflow-1',id=wid,name=args['name'],source=dict(projectId=p['projectId'],revision=p['authorRevision'],documentHash=p['sha256']),document=doc,dependencies=dependencies,parameters=parameters,bindingsRequired=[t['id'] for t in doc['tasks'] if t['kind'] in ('generation','speech')])
            path=folder/'workflow.json';path.write_text(canonical(manifest),encoding='utf8')
            row=(wid,args['name'],sha(path),str(path));db.execute('INSERT INTO workflow_archives VALUES(?,?,?,?)',row);db.execute('INSERT INTO workflow_index VALUES(?,?,?,?)',row);return dict(workflowId=wid,path=str(path),sha256=sha(path))
        return self.mutate('archive_workflow',args,apply)

    def list_workflows(self,args):
        with self.store.connect() as db:return [dict(r) for r in db.execute('SELECT * FROM workflow_index WHERE name LIKE ? ORDER BY name',('%'+args.get('query','')+'%',))]

    def rebuild_index(self,args):
        def apply(db):
            manifests=[]
            for archived in db.execute('SELECT * FROM workflow_archives'):
                path=checked_file(archived['path'],archived['manifest_hash'])
                value=json.loads(path.read_text(encoding='utf8'))
                if value.get('format')!='d-workflow-1' or value['id']!=path.parent.name:raise ValueError('invalid workflow archive')
                manifests.append((value['id'],value['name'],sha(path),str(path)))
            db.execute('DELETE FROM workflow_index');db.executemany('INSERT INTO workflow_index VALUES(?,?,?,?)',manifests)
            return dict(indexed=len(manifests))
        return self.mutate('rebuild_index',args,apply)

    def workflow(self,wid):
        with self.store.connect() as db:r=db.execute('SELECT * FROM workflow_index WHERE id=?',(wid,)).fetchone()
        if not r:raise ValueError('workflow not indexed')
        path=checked_file(r['path'],r['manifest_hash']);return json.loads(path.read_text(encoding='utf8')),path.parent

    def validate_parameter(self,path):
        if not re.fullmatch(r'(width|height|frames|background|layers\.\d+\.(text|color|x|y|width|height|font_size|props\.[A-Za-z_]+)|audio\.\d+\.volume|tasks\.\d+\.prompt)',path):raise ValueError('parameter cannot modify identities, assets, credentials or budgets')

    def reuse_document(self,args):
        manifest,folder=self.workflow(args['workflowId']);doc=deepcopy(manifest['document']);replacements=args.get('replacements',{});issues=[]
        if manifest.get('format')!='d-workflow-1':raise ValueError('WORKFLOW_MIGRATION_REQUIRED: unsupported archive version')
        for name,digest in manifest.get('dependencies',{}).get('implementation',{}).items():
            path=Path(__file__).parent/name
            if not path.is_file() or sha(path)!=digest:issues.append('dependency changed; explicit re-archive/migration required: '+name)
        if set(replacements)-{a['id'] for a in doc['assets']}:raise ValueError('unknown replacement asset')
        for asset in doc['assets']:
            if asset['id'] in replacements:
                replacement=replacements[asset['id']]
                if replacement['kind']!=asset['kind']:raise ValueError('replacement kind mismatch')
                asset.update({k:v for k,v in replacement.items() if k!='id'})
            else:
                path=(folder/asset['path']).resolve()
                if not path.is_relative_to(folder.resolve()):raise ValueError('workflow asset escapes archive')
                asset['path']=str(path)
            try:checked_file(asset['path'],asset['sha256'])
            except ValueError as exc:issues.append(str(exc))
        for binding in args.get('bindings',[]):
            task=next((t for t in doc['tasks'] if t['id']==binding['taskId']),None)
            if not task:raise ValueError('unknown task binding')
            task['provider']=binding['provider'];task['model']=binding.get('model',task['model'])
        for task in doc['tasks']:
            task['budget']=None;task['max_cost_micros']=0
            if task['kind'] in ('generation','speech') and not task['provider']:issues.append('binding required: '+task['id'])
        allowed={p['path'] for p in manifest['parameters']}
        for path,value in args.get('parameters',{}).items():
            if path not in allowed:raise ValueError('parameter was not declared by workflow')
            self.validate_parameter(path)
            parts=path.split('.');target=doc
            for part in parts[:-1]:target=target[int(part)] if isinstance(target,list) else target[part]
            target[int(parts[-1]) if isinstance(target,list) else parts[-1]]=value
        return upgrade(doc).model_dump(mode='json'),issues

    def preflight_reuse(self,args):
        doc,issues=self.reuse_document(args);return dict(compatible=not issues,issues=issues,documentHash=fingerprint(doc),budgetInherited=False,credentialsInherited=False)

    def instantiate_workflow(self,args):
        def apply(db):
            doc,issues=self.reuse_document(args)
            if issues:raise ValueError('; '.join(issues))
            doc=self.engine.snapshot_assets(doc);pid=uid();db.execute('INSERT INTO projects VALUES(?,?,0)',(pid,args['name']));db.execute('INSERT INTO revisions VALUES(?,?,?,?)',(pid,0,canonical(doc),fingerprint(doc)))
            return self.store.project(pid,db=db)
        return self.mutate('instantiate_workflow',args,apply)

    def retention_check(self,args):
        digest=args['sha256'];refs=[]
        if not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError('sha256 required')
        with self.store.connect() as db:
            for row in db.execute('SELECT * FROM revisions'):
                if digest in row['document']:refs.append(dict(kind='revision',projectId=row['project'],revision=row['revision']))
            for row in db.execute('SELECT id,result FROM builds WHERE result IS NOT NULL'):
                if digest in row['result']:refs.append(dict(kind='build',id=row['id']))
            for row in db.execute('SELECT id,manifest FROM reviews'):
                if digest in row['manifest']:refs.append(dict(kind='review',id=row['id']))
            tables={r['name'] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'draft_revisions' in tables:
                for row in db.execute('SELECT * FROM draft_revisions'):
                    if digest in row['manifest'] or digest in row['spec']:refs.append(dict(kind='draft',id=row['draft'],revision=row['revision']))
            if 'draft_installations' in tables:
                for row in db.execute('SELECT * FROM draft_installations'):
                    if digest in row['manifest']:refs.append(dict(kind='installation',id=row['id']))
        for path in (self.store.root/'workflows').glob('*/workflow.json'):
            if digest in path.read_text(encoding='utf8'):refs.append(dict(kind='workflow',id=path.parent.name))
        for path in (self.store.root/'deliveries').glob('*/receipt.json'):
            if digest in path.read_text(encoding='utf8'):refs.append(dict(kind='delivery',id=path.parent.name))
        return dict(sha256=digest,references=refs,deletable=not refs,action='report only; no deletion')

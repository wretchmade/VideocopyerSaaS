"""Production entry points shared by HTTP, MCP and the D editor."""
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from .engine import Engine
from .schema import Project,BrandPlacement

router=APIRouter(prefix='/api/d-production',tags=['d-production-core'])

OPERATIONS={
    'review_brand_build':('Record visual brand review of an exact rendered output hash; approval is caller-declared and gates brand-aware delivery',['commandId','buildId','sha256','approved','note']),
    'bind_brand_lock':('Pin an original image to a fixed screen position or reviewed per-frame planar coordinates; creates an immutable revision, does not generate or track',['commandId','projectId','baseRevision','layerId','placement']),
    'capabilities':('Inspect independent components, effects, media and provider/model coverage',[]),
    'storage_status':('Inspect storage configuration and credential references without reading secrets',[]),
    'authorize_budget':('Authorize a capped account/currency budget for one exact project revision',['commandId','projectId','revision','account','currency','limitMicros','concurrency']),
    'reconcile_request':('Attach a confirmed provider task ID to an ambiguous submission without resubmitting',['commandId','requestId','remoteId']),
    'transfer_workspace':('Import a licensed, supported existing D workspace revision without changing its database',['commandId','workspace_id','expected_revision']),
    'create_project':('Create a D project and import checksum-pinned local assets',['commandId','name']),
    'edit_project':('Commit an immutable D revision with optimistic concurrency',['commandId','projectId','baseRevision','document']),
    'list_projects':('List D production projects',[]),
    'inspect_project':('Read an exact project revision',['projectId']),
    'check_project':('Validate the D project, asset identities and executable boundary',['projectId']),
    'plan_build':('Plan the local dependency graph with runtime identities',['projectId']),
    'submit_build':('Submit a frozen local render; retries with the same commandId do not execute twice',['commandId','projectId','revision']),
    'build_status':('Query and recover durable execution state',['buildId']),
    'inspect_build':('Read execution, node checkpoints, output and errors',['buildId']),
    'cancel_build':('Cancel queued or running execution',['commandId','buildId']),
    'retry_build':('Explicitly resume failed or cancelled execution from validated checkpoints',['commandId','buildId']),
    'preview_frame':('Render an exact frame PNG from a D revision',['projectId','frame']),
    'deliver_mp4':('Verify and archive a successful MP4 or alpha MOV with a delivery receipt',['commandId','buildId']),
}


def tools():
    from .stage4_api import tools as stage4_tools
    properties={'account':{'type':'string'},'currency':{'type':'string'},'limitMicros':{'type':'integer','minimum':0},'concurrency':{'type':'integer','minimum':1,'maximum':100},'requestId':{'type':'string'},'remoteId':{'type':'string'},'workspace_id':{'type':'string'},'expected_revision':{'type':'integer','minimum':1},'commandId':{'type':'string','minLength':1},'name':{'type':'string'},'projectId':{'type':'string'},
                'buildId':{'type':'string'},'revision':{'type':'integer','minimum':0},'baseRevision':{'type':'integer','minimum':0},
                'frame':{'type':'integer','minimum':0},'document':Project.model_json_schema()}
    properties['layerId']={'type':'string'}
    properties.update(sha256={'type':'string','pattern':'^[0-9a-f]{64}$'},approved={'type':'boolean'},note={'type':'string','minLength':1,'maxLength':4000})
    properties['placement']=BrandPlacement.model_json_schema()
    optional={'create_project':['document'],'inspect_project':['revision'],'check_project':['revision'],
              'plan_build':['revision'],'preview_frame':['revision']}
    definitions=properties['document'].pop('$defs',{})
    placement_definitions=properties['placement'].pop('$defs',{})
    return [dict(name='d_'+name,description=description,inputSchema={'type':'object','properties':{k:properties[k] for k in required+optional.get(name,[])},
                'required':required,'additionalProperties':False,**({'$defs':definitions} if 'document' in required+optional.get(name,[]) else {'$defs':placement_definitions} if 'placement' in required else {})}) for name,(description,required) in OPERATIONS.items()]+stage4_tools()


def dispatch(name,args,engine=None):
    name=name.removeprefix('d_')
    from .stage4_api import SPECS,dispatch as stage4_dispatch
    if name not in OPERATIONS and name not in SPECS: raise ValueError('Unsupported independent D operation')
    definition=next(t for t in tools() if t['name']=='d_'+name)['inputSchema']
    if not isinstance(args,dict):raise ValueError('command arguments must be an object')
    if set(args)-definition['properties'].keys(): raise ValueError('unknown command arguments')
    if set(definition['required'])-args.keys(): raise ValueError('missing required command arguments')
    types={'string':str,'integer':int,'boolean':bool,'object':dict,'array':list}
    for key,value in args.items():
        spec=definition['properties'][key];expected=types.get(spec.get('type'))
        if expected and type(value)!=expected:raise ValueError('invalid argument type: '+key)
        if 'minimum' in spec and value<spec['minimum']:raise ValueError('argument below minimum: '+key)
        if 'maximum' in spec and value>spec['maximum']:raise ValueError('argument above maximum: '+key)
    engine=engine if engine is not None else Engine()
    if name in SPECS:return stage4_dispatch(engine,name,args)
    if name=='bind_brand_lock':
        from .brand import bind
        return bind(engine,args)
    if name=='review_brand_build':
        from .brand import review_build
        return review_build(engine,args)
    if name=='capabilities':
        from .components import catalog as components
        from .providers import catalog as providers
        from .speech import readiness
        from .media import OPERATIONS as media
        return dict(components=components(),providers=providers(),models=readiness(),media=media,
                    brandProtection=dict(modes=['screen','planar'],bindingTool='d_bind_brand_lock',
                                         automaticTracking=False,modelIdentityGuaranteed=False,
                                         planarInput='frozen plate, one reviewed sample per frame, explicit visibility masks'))
    if name=='storage_status':
        from .storage import status
        return status()
    if name in ('authorize_budget','reconcile_request'):
        from .ledger import Ledger
        ledger=Ledger(engine.store)
        return ledger.authorize(args) if name=='authorize_budget' else ledger.reconcile(args)
    if name=='transfer_workspace':
        from .bridge import read_workspace
        # Resolve source only inside a persisted receipt, so a successful retry
        # remains valid even if the legacy workspace later changes.
        def transfer(db):
            source=read_workspace(args['workspace_id'],args['expected_revision'])
            from .store import uid,canonical,fingerprint
            document=engine.snapshot_assets(source['document']);pid=uid()
            db.execute('INSERT INTO projects VALUES(?,?,0)',(pid,source['name']))
            db.execute('INSERT INTO revisions VALUES(?,?,?,?)',(pid,0,canonical(document),fingerprint(document)))
            return {**engine.store.project(pid,db=db),'source':source['source']}
        return engine.store.mutate(args['commandId'],{'op':name,**args},transfer)
    if name=='create_project':return engine.create(args)
    if name=='edit_project':return engine.edit(args)
    if name=='list_projects':
        with engine.store.connect() as db:
            return [dict(projectId=r['id'],name=r['name'],authorRevision=r['revision']) for r in db.execute('SELECT * FROM projects ORDER BY rowid DESC')]
    if name=='inspect_project':return engine.store.project(args['projectId'],args.get('revision'))
    if name=='check_project':return engine.check(args)
    if name=='plan_build':return engine.plan(args)
    if name=='submit_build':return engine.submit(args)
    if name in ('build_status','inspect_build'):
        result=engine.status(args['buildId'])
        if name=='inspect_build':
            import json
            from .ledger import Ledger
            result['remoteRequests']=[{k:v for k,v in row.items() if k not in ('response','payload')} for row in Ledger(engine.store).inspect(args['buildId'])]
            with engine.store.connect() as db:
                result['events']=[{**dict(r),'data':json.loads(r['data'])} for r in db.execute('SELECT * FROM events WHERE build=? ORDER BY seq',(args['buildId'],))]
        return result
    if name=='cancel_build':return engine.cancel(args)
    if name=='retry_build':return engine.retry(args)
    if name=='preview_frame':return engine.preview(args)
    if name=='deliver_mp4':return engine.deliver(args)


@router.get('/status')
def status():return dict(engine='d-core-1',upstreamRuntime=False,stages=[1,2,3,4,5],packageVersion='2.0.0-beta.1',modelQualityVerified=False,nativeDraftUIVerified=False)


@router.get('/schema')
def schema():return Project.model_json_schema()


@router.get('/projects')
def projects():return dispatch('list_projects',{})


@router.post('/projects')
def create(args:dict):return invoke('create_project',args)


@router.get('/projects/{project_id}')
def inspect(project_id:str):return invoke('inspect_project',dict(projectId=project_id))


@router.post('/commands/{operation}')
def invoke(operation:str,args:dict):
    try:return dispatch(operation,args)
    except (ValueError,FileNotFoundError,KeyError) as exc:raise HTTPException(422,detail=str(exc)) from exc


@router.get('/files/{kind}/{identity}/{filename:path}')
def file(kind:str,identity:str,filename:str):
    store=Engine().store
    if kind not in ('builds','previews','deliveries','reviews','drafts','workflows'):raise HTTPException(404)
    root=(store.root/kind).resolve();target=(root/identity/filename).resolve()
    if not target.is_relative_to(root) or not target.is_file() or target.suffix not in ('.png','.mp4','.mov','.json','.zip'):raise HTTPException(404)
    return FileResponse(target)

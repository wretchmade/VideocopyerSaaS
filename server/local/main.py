import asyncio, json, os, secrets, subprocess, sys, time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import select
from . import db, projects, production, bridge, gateway
from . import storage, commands, coordinator
from .config import DATA, ROOT, CONFIG, PORT, contained

CSRF=secrets.token_urlsafe(32)
ACTIVE=set()

@asynccontextmanager
async def lifespan(app):
    async with gateway.connection_pool():
        with db.transaction() as c:
            for p in db.all(c,'project'):
                if p['status'] in {'running','starting'}:
                    p['status']='interrupted';db.put(c,'project',p['id'],p,p['id'],True)
            for q in db.all(c,'question'):
                if q['status']=='pending':q['status']='interrupted';db.put(c,'question',q['id'],q,q['project'],True)
        coordinator.recover()
        try:production.setup_media()
        except Exception:pass
        env={**os.environ,'PYTHONPATH':str(ROOT/'server')}
        with open(DATA/'worker.log','ab') as log:
            worker=subprocess.Popen([sys.executable,'-m','local.worker'],cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        inbox_task=asyncio.create_task(coordinator.run())
        try:yield
        finally:
            inbox_task.cancel()
            await asyncio.gather(inbox_task,return_exceptions=True)
            await asyncio.gather(*(r.close() for r in bridge.RUNNERS.values()),return_exceptions=True)
            worker.terminate()
            try:worker.wait(timeout=5)
            except subprocess.TimeoutExpired:worker.kill()

app=FastAPI(title='VideoCopyer local',lifespan=lifespan,docs_url=None,redoc_url=None)

@app.middleware('http')
async def security(request,call_next):
    host=request.headers.get('host','')
    allowed={f'127.0.0.1:{PORT}',f'localhost:{PORT}'}
    if host not in allowed:return JSONResponse({'detail':'Invalid local host'},403)
    origin=request.headers.get('origin')
    if origin and origin not in {f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'}:return JSONResponse({'detail':'Invalid origin'},403)
    if request.method not in {'GET','HEAD'} and not request.url.path.startswith('/gateway/'):
        if not secrets.compare_digest(request.headers.get('x-vc-token',''),CSRF):return JSONResponse({'detail':'请刷新页面后重试'},403)
    try:response=await call_next(request)
    except ValueError as exc:return JSONResponse({'detail':str(exc)},409)
    response.headers['X-Content-Type-Options']='nosniff';response.headers['Referrer-Policy']='no-referrer'
    response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"
    return response

@app.exception_handler(ValueError)
async def invalid(request,exc):return JSONResponse({'detail':str(exc)},409)

from app.creative_templates.contracts import TemplateError
from .template_api import router as template_router
app.include_router(template_router)

@app.exception_handler(TemplateError)
async def invalid_template(request,exc):
    return JSONResponse({"detail":str(exc),"issues":exc.issues},409)

@app.exception_handler(InterruptedError)
async def interrupted(request,exc):return JSONResponse({'detail':'本地处理已停止或执行状态已变化，请检查当前修订。'},409)

@app.get('/api/bootstrap')
def bootstrap():
    with db.transaction() as c:
        usage=db.all(c,'usage');used=sum(x['reserved_micros'] for x in usage if x['state']!='released')
    return {'token':CSRF,'agent_runtime':bridge.runtime_name(),'codex_version':'0.163.0' if bridge.runtime_name()=='codex' else None,'model':CONFIG.get('planning',{}).get('model'),'budget_micros':round(CONFIG.get('test_budget_cny',0)*1e6),'reserved_micros':used,'database':db.engine.dialect.name,'paid_configured':bool(CONFIG.get('media_profile'))}

@app.get('/api/projects')
def list_projects():
    with db.transaction() as c:return db.all(c,'project')

@app.post('/api/projects')
async def create_project(request:Request):
    body=await request.json();text=body.get('text','').strip()
    if not text or len(text)>20000:raise ValueError('需求需为 1 至 20000 个字符')
    return projects.create(body['command_id'],text)

@app.get('/api/projects/{pid}')
def get_project(pid):return bridge.public_snapshot(pid)

@app.post('/api/projects/{pid}/files')
async def upload(pid,file:UploadFile=File(...)):
    data=await file.read(100*1024*1024+1);row=await asyncio.to_thread(projects.add_file,pid,file.filename or 'file',data)
    return {k:v for k,v in row.items() if k!='path'}

@app.get('/api/projects/{pid}/files/{fid}')
def download(pid,fid):
    with db.transaction() as c:f=db.get(c,'file',fid,pid)
    return FileResponse(contained(f['path']),filename=f['name'],content_disposition_type='inline' if f['kind'] in {'image','video','audio'} else 'attachment')

@app.post('/api/projects/{pid}/files/{fid}/storage')
async def publish_file(pid,fid):return await asyncio.to_thread(storage.publish,pid,fid)

@app.put('/api/projects/{pid}/plan')
async def save_plan(pid,request:Request):
    b=await request.json();return projects.save_plan(pid,b['base_revision'],b['plan'],b['command_id'])

async def run_turn(pid,text,files,selected):
    try:await bridge.runner(pid).turn(text,files,selected)
    except Exception as exc:
        with db.transaction() as c:
            p=db.get(c,'project',pid);p['status']='interrupted' if str(exc)=='用户已停止当前运行' else 'failed';db.put(c,'project',pid,p,pid,True)
            db.emit(c,pid,'agent/error',{'message':str(exc)});projects.message(c,pid,'system',str(exc))
    finally:ACTIVE.discard(pid)

@app.post('/api/projects/{pid}/messages')
async def send(pid,request:Request):
    from .template_api import body as strict_body
    b=await strict_body(request);text=b.get('text','').strip()
    from . import templates
    with db.transaction() as c:template_project=db.get(c,'project',pid).get('template_instance')
    if b.get('template_mount') or b.get('composer_id') or template_project:
        result=await asyncio.to_thread(templates.send,b,pid)
        with db.transaction() as c:item=db.get(c,'agent_inbox',result['run_id'],pid)
        await asyncio.to_thread(commands.apply_user_intent,item)
        return result
    if not text or len(text)>20000:raise ValueError('消息需为 1 至 20000 个字符')
    with db.transaction() as c:
        def action():
            p=db.get(c,'project',pid)
            for fid in b.get('file_ids',[]):db.get(c,'file',fid,pid)
            if not b.get('initial'):projects.message(c,pid,'user',text,selected=b.get('selected'))
            p['status']='starting';db.put(c,'project',pid,p,pid,True)
            inbox_id='user:'+db.digest({'project':pid,'command':b['command_id']})[:40]
            from app.workbench_d.commercial import flow
            fence=flow.state(production.engine(pid).store) or {'epoch':0}
            commands.enqueue(c,pid,inbox_id,text,fence['epoch'])
            inbox=db.get(c,'agent_inbox',inbox_id,pid)
            inbox.update(user=True,file_ids=b.get('file_ids',[]),selected=b.get('selected'),intent=commands.user_intent(c,pid,text))
            db.put(c,'agent_inbox',inbox_id,inbox,pid,True)
            return {'accepted':True,'run_id':inbox_id}
        before=len(db.all(c,'command'));result=db.once(c,b['command_id'],{'op':'message','project':pid,**b},action);fresh=len(db.all(c,'command'))>before
    with db.transaction() as c:inbox=db.get(c,'agent_inbox',result['run_id'],pid)
    await asyncio.to_thread(commands.apply_user_intent,inbox)
    if fresh:
        if pid in bridge.RUNNERS and bridge.RUNNERS[pid].active:
            # Interrupt then prioritize persisted user message; never reject a live-turn edit.
            await bridge.RUNNERS[pid].stop()
    return result

@app.post('/api/projects/{pid}/stop')
async def stop(pid):
    result=await asyncio.to_thread(commands.stop,pid)
    if pid in bridge.RUNNERS:await bridge.RUNNERS[pid].stop()
    return result

@app.post('/api/projects/{pid}/questions/{qid}')
async def answer(pid,qid,request:Request):
    b=await request.json()
    r=bridge.RUNNERS.get(pid)
    if not r:raise ValueError('提问会话已中断，请在对话中发送答案并继续')
    return await r.answer(qid,b['answer'])

@app.get('/api/projects/{pid}/events')
async def events(pid,request:Request,after:int=0):
    with db.transaction() as c:db.get(c,'project',pid)
    after=max(after,int(request.headers.get('last-event-id','0') or 0))
    async def stream():
        cursor=after
        while not await request.is_disconnected():
            with db.transaction() as c:rows=c.execute(select(db.events).where(db.events.c.project==pid,db.events.c.seq>cursor).order_by(db.events.c.seq).limit(200)).mappings().all()
            for row in rows:
                cursor=row['seq'];yield f'id: {cursor}\ndata: '+db.dump({'seq':cursor,'kind':row['kind'],'data':json.loads(row['body'])})+'\n\n'
            if not rows:yield ': keepalive\n\n'
            await asyncio.sleep(.5)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})

@app.post('/gateway/{pid}/responses')
async def provider(pid,request:Request):return await gateway.responses(pid,request)

@app.post('/gateway/{pid}/tools')
async def mcp_call(pid,request:Request):
    token=request.headers.get('authorization','').removeprefix('Bearer ')
    if bridge.GATEWAY_TOKENS.get(token)!=pid:raise HTTPException(403,'Private project tool boundary')
    body=await request.json()
    try:
        result=await bridge.runner(pid).invoke(body['name'],body.get('arguments',{}),str(body.get('_meta',{}).get('progressToken',db.uid())))
        content=result.pop('_contentItems',None) if isinstance(result,dict) else None
        if content:
            return {'content':[{'type':'image','data':x['imageUrl'].split(',',1)[1],'mimeType':'image/jpeg'} for x in content]}
        response={'content':[{'type':'text','text':db.dump(result)}],'isError':False}
        if body['name'] in {'stop_production','d_cancel_build'}:
            from starlette.background import BackgroundTask
            return JSONResponse(response,background=BackgroundTask(bridge.runner(pid).stop))
        return response
    except Exception as exc:
        return {'content':[{'type':'text','text':str(exc)}],'isError':True}

@app.get('/api/projects/{pid}/quote')
def quote(pid,revision:int):return production.quote(pid,revision)

@app.post('/api/projects/{pid}/native/quote')
async def native_quote(pid,request:Request):
    b=await request.json();return await asyncio.to_thread(commands.prepare,pid,b.get('regenerate_nodes'))

@app.post('/api/projects/{pid}/quotes/{qid}/confirm')
async def confirm_quote(pid,qid,request:Request):
    b=await request.json()
    with db.transaction() as c:q=db.get(c,'quote',qid,pid)
    if q['mode']=='native':return await asyncio.to_thread(commands.confirm,pid,qid,b['command_id'])
    return await asyncio.to_thread(production.submit,pid,q['revision'],b['command_id'],q['quote_hash'])

@app.post('/api/projects/{pid}/tools/{name}')
async def project_tool(pid,name,request:Request):
    b=await request.json()
    result=await asyncio.to_thread(commands.dispatch,pid,name,b)
    if name in {'stop_production','d_cancel_build'}:await bridge.runner(pid).stop()
    return result

@app.post('/api/projects/{pid}/native/visible')
async def visible(pid,request:Request):
    b=await request.json();e=commands.engine(pid)
    with db.transaction() as c:p=db.get(c,'project',pid)
    from app.workbench_d.commercial.production_state import ProductionState
    state=ProductionState(e)
    view=state.canvas_status({'projectId':p['native_project'],'revision':b['revision']})
    if view['version']!=b.get('view_version',0):raise ValueError('画布布局已变化，需重新呈现再登记可见回执')
    return state.record_view({'commandId':b['command_id'],'projectId':p['native_project'],'revision':b['revision'],
                             'documentHash':b['document_hash'],'viewVersion':view['version'],'session':b['session'],'visibility':'visible'})

@app.post('/api/projects/{pid}/local-access')
async def local_access(pid,request:Request):
    b=await request.json()
    with db.transaction() as c:
        return commands.grant_local(c,pid,b['path'],b['purpose'],b['command_id'])

@app.post('/api/projects/{pid}/produce')
async def produce(pid,request:Request):
    b=await request.json();return production.submit(pid,b['revision'],b['command_id'],b['quote_hash'])

@app.post('/api/projects/{pid}/tasks/{tid}/{action}')
async def task_control(pid,tid,action):
    if action not in {'stop','resume'}:raise ValueError('未知操作')
    result=await asyncio.to_thread(production.control,pid,tid,action)
    if action=='stop':await bridge.runner(pid).stop()
    return result

@app.get('/api/projects/{pid}/tasks/{tid}/requests')
def task_requests(pid,tid,refresh:bool=False):return production.requests(pid,tid,refresh)

@app.post('/api/projects/{pid}/tasks/{tid}/requests/{rid}/reconcile')
async def reconcile(pid,tid,rid,request:Request):
    b=await request.json();return await asyncio.to_thread(production.reconcile,pid,tid,rid,b['remote_id'],b.get('confirmed',False),b['command_id'])

@app.post('/api/projects/{pid}/deliver')
async def delivery(pid,request:Request):
    b=await request.json();return await asyncio.to_thread(production.deliver,pid,b['task_id'],b.get('allow_baked',False),b['command_id'])

@app.get('/api/projects/{pid}/deliveries/{did}/{kind}')
def output(pid,did,kind):
    if kind not in {'preview','zip'}:raise ValueError('未知交付文件')
    with db.transaction() as c:r=db.get(c,'delivery',did,pid)
    p=contained(r[kind+'_path'])
    if production.sha(p)!=r[kind+'_sha256']:raise ValueError('交付文件完整性检查失败')
    return FileResponse(p,filename=p.name,content_disposition_type='inline' if kind=='preview' else 'attachment',media_type='video/mp4' if kind=='preview' else 'application/zip')

@app.get('/{path:path}')
def frontend(path):
    root=(ROOT/'dist').resolve();p=(root/path).resolve()
    if not p.is_relative_to(root):raise HTTPException(404)
    if p.is_file():return FileResponse(p)
    if (root/'index.html').is_file():return FileResponse(root/'index.html')
    return JSONResponse({'detail':'请先运行 npm run build'},503)

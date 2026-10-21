"""Local D adapter. Every build is pinned to an immutable web plan revision."""
import hashlib, json, os, shutil, time, zipfile
from pathlib import Path
from . import db
from .config import DATA, ROOT, CONFIG, contained
from .credentials import media_endpoint, media_key
from app.workbench_d.commercial.engine import Engine
from app.workbench_d.commercial.drafts import Drafts, requires_companion
from app.workbench_d.commercial.ledger import Ledger
from app.workbench_d.commercial.schema import Layer
from app.workbench_d.commercial.render import sha

_ENGINES={}
def engine(pid):
    root=DATA/'projects'/pid/'execution'
    key=str(root)
    if key not in _ENGINES:_ENGINES[key]=Engine(root)
    return _ENGINES[key]

def generation_key(plan,shot):
    model=media_endpoint()['modelId'] if CONFIG.get('media_profile') else 'unconfigured'
    refs=[shot['file_id']]+[x['reference_file_id'] for x in plan['characters'] if x['id'] in shot['character_ids']]
    # File IDs are immutable and their bytes are verified again by compile_plan.
    from app.workbench_d.commercial import render
    implementation=hashlib.sha256(b''.join(p.read_bytes() for p in sorted(Path(render.__file__).parent.iterdir()) if p.suffix in ('.py','.mjs'))).hexdigest()
    return db.digest({'description':shot['description'],'reference':refs,'characters':[x for x in plan['characters'] if x['id'] in shot['character_ids']],'aspect':plan['aspect'],'model':model,'resolution':'720p','generate_audio':False,'attempt':shot.get('generation_attempt',''),'implementation':implementation})

def setup_media():
    os.environ['D_HEAVY_ROOT']=str(DATA/'resources')
    os.environ['D_JIANYING_PYTHON']=str(ROOT/'.venv-jianying/Scripts/python.exe')
    for key in ['ffmpeg','ffprobe']:
        if CONFIG.get(key):os.environ['D_'+key.upper()]=CONFIG[key]
    # Only this backend/worker receives the provider credential. Bridge env is allowlisted.
    if not CONFIG.get('media_profile'):return
    endpoint=media_endpoint()
    config={'ark':{'service':'ark','base_url':endpoint['baseUrl'].removesuffix('/api/v3'),'account':'vc-selected-ark','currency':'CNY','credential_env':'VC_MEDIA_KEY','models':{'seedance-2':{'wire_model':endpoint['modelId'],'output_kind':'video','documentation':'https://docs.volcengine.com/docs/ark/create-video-generation-task-api','quote':{'upperMicros':33000000,'expires':int(time.time())+86400},'defaults':{'watermark':False},'max_reference_bytes':15*1024*1024}}}}
    path=DATA/'providers.json'
    # A restart must not silently change the identity of in-flight builds.
    if path.is_file():
        prior=json.loads(path.read_text(encoding='utf8'))
        if (prior.get('ark',{}).get('models',{}).get('seedance-2',{}).get('wire_model')!=endpoint['modelId']
            or prior.get('ark',{}).get('base_url')!=config['ark']['base_url']):
            raise ValueError('媒体配置与冻结执行版本不同；请先完成旧请求核对再更新供应商配置')
    else:path.write_text(db.dump(config),encoding='utf8')
    os.environ['D_PROVIDERS']=str(path);os.environ['VC_MEDIA_KEY']=media_key()

def compile_plan(c,pid,revision):
    row=db.get(c,'plan',f'{pid}:{revision}',pid);plan=row['plan']
    if not plan['shots']:raise ValueError('请先添加分镜并保存规划')
    width,height={'16:9':(960,540),'9:16':(540,960),'1:1':(720,720)}[plan['aspect']]
    doc={'width':width,'height':height,'fps':{'num':24,'den':1},'frames':1,'assets':[],'layers':[],'audio':[],'tasks':[],'background':'#101820'}
    files={}
    def asset(fid,kind=None):
        if fid in files:return files[fid]
        f=db.get(c,'file',fid,pid)
        if kind and f['kind']!=kind:raise ValueError('素材类型不匹配')
        if sha(contained(f['path']))!=f['sha256']:raise ValueError('素材哈希发生变化')
        a={'id':fid,'kind':f['kind'],'path':f['path'],'sha256':f['sha256'],'license':'user supplied; user responsible for usage rights','source':'file:'+fid}
        doc['assets'].append(a);files[fid]=a;return a
    font=Path(CONFIG.get('font','C:/Windows/Fonts/msyh.ttc'))
    if any(s['subtitle'] for s in plan['shots']):
        if not font.is_file():raise ValueError('请配置可用的中文字幕字体')
        doc['assets'].append({'id':'font','kind':'font','path':str(font),'sha256':sha(font),'license':'system font; local usage; redistribution requires rights','source':'local-font'})
    at=0
    for s in plan['shots']:
        frames=round(s['duration']*24);source=None;kind=None
        if s['file_id'] and not s['generate']:
            a=asset(s['file_id']);source=a['id'];kind=a['kind']
            if kind not in {'image','video'}:raise ValueError('分镜画面需为图片或视频')
        elif s['generate']:
            if s['duration']>15:raise ValueError('当前媒体模型单镜头最多 15 秒')
            # Reuse exact generation inputs across revisions after a successful build.
            cache_key=generation_key(plan,s)
            try:
                cached=db.get(c,'generated',pid+':'+cache_key,pid)
                if cached['duration'] < s['duration']+s['source_start']:raise ValueError('缓存素材时长不足')
                a=asset(cached['file_id']);source=a['id'];kind='video'
            except ValueError:
                refs=[]
                if s['file_id']:refs.append(s['file_id'])
                refs.extend(x['reference_file_id'] for x in plan['characters'] if x['id'] in s['character_ids'] and x['reference_file_id'])
                refs=list(dict.fromkeys(refs))
                for fid in refs:asset(fid,'image')
                source='gen_'+s['id'];kind='video'
                prompt=s['description']+'\n'+ '\n'.join(x['name']+': '+x['description'] for x in plan['characters'] if x['id'] in s['character_ids'])
                doc['tasks'].append({'id':source,'kind':'generation','provider':'ark','model':'seedance-2','prompt':prompt,'inputs':refs,'input_roles':['reference_image']*len(refs),'output_kind':'video','options':{'duration':int(s['duration']),'resolution':'720p','ratio':plan['aspect'],'generate_audio':False},'max_cost_micros':33000000})
        else:raise ValueError('镜头 '+s['title']+' 尚未选择素材或生成方式')
        doc['layers'].append({'id':s['id'],'kind':kind,'asset':source,'start':at,'end':at+frames,'source_start':round(s['source_start']*24),'width':width,'height':height,'track':0,'fit':'cover'})
        if s['subtitle']:
            doc['layers'].append({'id':'sub_'+s['id'],'kind':'text','text':s['subtitle'],'start':at,'end':at+frames,'x':round(width*.06),'y':height-round(height*.18),'width':round(width*.88),'height':round(height*.14),'fonts':['font'],'font_size':round(height*.045),'text_align':'center','color':'#ffffff','track':10})
        at+=frames
    doc['frames']=at
    if plan.get('audio_file_id'):
        a=asset(plan['audio_file_id'],'audio');doc['audio'].append({'asset':a['id'],'start':0,'end':at,'volume':1})
    return doc,plan

def quote(pid,revision):
    from app.workbench_d.commercial import flow
    flow.initialize(engine(pid).store)
    with db.transaction() as c:
        p=db.get(c,'project',pid)
        if p.get('execution_mode')=='native':raise ValueError('此项目已采用 D 原生修订，请从当前工程重新报价')
        if p.get('template_instance'):raise ValueError('模板项目须通过模板编译与原生报价校验')
        doc,plan=compile_plan(c,pid,revision)
        cost=sum(x['max_cost_micros'] for x in doc['tasks'])
        epoch=flow.state(engine(pid).store)['epoch']
        q={'id':db.uid(),'project':pid,'mode':'legacy','status':'pending','expires':time.time()+900,'epoch':epoch,'revision':revision,'paid_tasks':len(doc['tasks']),'maximum_micros':cost,'currency':'CNY','frames':doc['frames'],'duration':doc['frames']/24,'baked':[l['id'] for l in doc['layers'] if requires_companion(Layer.model_validate(l))],'bill_status':'保守预留；实际费用待供应商对账','document_hash':db.digest(doc),'quote_hash':db.digest({'document':doc,'epoch':epoch})}
        for old in db.all(c,'quote',pid):
            if old['status']=='pending':
                if old['quote_hash']==q['quote_hash'] and old['expires']>time.time():return old
                old['status']='superseded';db.put(c,'quote',old['id'],old,pid,True)
        db.put(c,'quote',q['id'],q,pid);db.emit(c,pid,'quote/prepared',q)
        return q

def submit(pid,revision,command,quote_hash):
    with db.transaction() as c:
        def action():
            p=db.get(c,'project',pid)
            if p.get('execution_mode')=='native':raise ValueError('此项目已采用 D 原生修订，请确认当前原生报价')
            if p['revision']!=revision:raise ValueError('规划已更新，请重新确认制作范围')
            doc,plan=compile_plan(c,pid,revision)
            from app.workbench_d.commercial import flow
            epoch=flow.state(engine(pid).store)['epoch']
            matching=[q for q in db.all(c,'quote',pid) if q['quote_hash']==quote_hash and q['revision']==revision and q['epoch']==epoch]
            if not matching or matching[-1]['expires']<=time.time() or matching[-1]['status']=='superseded':raise ValueError('报价已过期或停止状态已变化，请重新确认')
            quoted=matching[-1]
            if db.digest(doc)!=quoted['document_hash']:raise ValueError('素材或制作范围发生变化，请重新确认')
            for old in db.all(c,'task',pid):
                if old['revision']==revision and old.get('epoch',0)==epoch:return old
            tid=db.uid();maximum=sum(t['max_cost_micros'] for t in doc['tasks'])
            if maximum:db.reserve(c,tid,pid,maximum,'media',{'revision':revision,'document':db.digest(doc)})
            keys={'gen_'+s['id']:{'key':generation_key(plan,s),'duration':s['duration'],'name':s['title']} for s in plan['shots'] if s['generate']}
            row={'id':tid,'project':pid,'revision':revision,'document':doc,'document_hash':db.digest(doc),'generation_keys':keys,'status':'queued','stage':'准备制作','build_id':None,'created':time.time(),'epoch':epoch,'quote_id':quoted['id']}
            quoted.update(status='authorized',task_id=tid);db.put(c,'quote',quoted['id'],quoted,pid,True)
            db.put(c,'task',tid,row,pid);db.emit(c,pid,'task/queued',{'id':tid,'revision':revision});return row
        return db.once(c,command,{'op':'submit','project':pid,'revision':revision,'quote_hash':quote_hash},action)

def tick():
    with db.transaction() as c:tasks=db.all(c,'task')
    for task in tasks:
        if task['status'] not in {'queued','running','reconciling','stopping'}:continue
        if task.get('native'):
            from .commands import tick_native
            try:tick_native(task)
            except Exception as exc:
                with db.transaction() as c:
                    latest=db.get(c,'task',task['id'],task['project'])
                    if not latest.get('stop_requested'):
                        latest.update(status='failed',error=str(exc));db.put(c,'task',task['id'],latest,task['project'],True)
                        from .commands import enqueue
                        enqueue(c,task['project'],'terminal:'+task['id'],'制作失败：'+str(exc),task['epoch'])
                        db.emit(c,task['project'],'task/updated',{'id':task['id'],'status':'failed','error':str(exc)})
            continue
        pid=task['project'];tid=task['id'];e=engine(pid)
        try:
            if task.get('stop_requested') and task.get('build_id'):
                e.cancel({'commandId':'global-stop-'+tid,'buildId':task['build_id']})
            if not task.get('build_id'):
                # Record exact cross-store mutation input before changing D. A restart
                # must replay the same baseRevision, not derive a newer one.
                with db.transaction() as c:
                    task=db.get(c,'task',tid,pid)
                    if not task.get('core_intent'):
                        p=db.get(c,'project',pid)
                        if p.get('legacy_core_project'):
                            old=e.store.project(p['legacy_core_project'])
                            intent={'method':'edit','args':{'commandId':'web-create-'+tid,'projectId':old['projectId'],'baseRevision':old['authorRevision'],'document':task['document']}}
                        else:
                            intent={'method':'create','args':{'commandId':'web-create-'+tid,'name':p['title'],'document':task['document']}}
                        task['core_intent']=intent
                        db.put(c,'task',tid,task,pid,True)
                # Snapshot control state, then wait/submit outside its transaction.
                with db.transaction() as c:
                    task=db.get(c,'task',tid,pid)
                from app.workbench_d.commercial import flow
                from app.workbench_d.commercial.resources import slot
                fence=flow.state(e.store)
                if task.get('stop_requested') or fence and fence['epoch']!=task.get('epoch',0):continue
                def check():
                    now=flow.state(e.store)
                    if now and now['epoch']!=task.get('epoch',0):raise InterruptedError('Project stopped during preflight')
                with slot('legacy-build-preflight',check):
                    if fence:flow.resume(e.store,task.get('epoch',0))
                    intent=task['core_intent']
                    created=getattr(e,intent['method'])(intent['args'])
                    with db.transaction() as c:
                        p=db.get(c,'project',pid)
                        if not p.get('legacy_core_project'):
                            p['legacy_core_project']=created['projectId'];db.put(c,'project',pid,p,pid,True)
                    rev=created['authorRevision']
                    if task['document']['tasks']:
                        Ledger(e.store).authorize({'commandId':'web-budget-'+tid,'projectId':created['projectId'],'revision':rev,'account':'vc-selected-ark','currency':'CNY','limitMicros':sum(t['max_cost_micros'] for t in task['document']['tasks']),'concurrency':1})
                    built=e.submit({'commandId':'web-build-'+tid,'projectId':created['projectId'],'revision':rev})
                    task.update(build_id=built['buildId'],core_project=created['projectId'],core_revision=rev,status='running')
                    with db.transaction() as c:
                        latest=db.get(c,'task',tid,pid)
                        if latest.get('stop_requested'):task.update(stop_requested=True,status='stopping')
                        db.put(c,'task',tid,task,pid,True)
            status=e.store.build(task['build_id']);requests=Ledger(e.store).inspect(task['build_id'])
            if not task.get('stop_requested'):e.launch(task['build_id'])
            task.update(status='reconciling' if any(r['state'] in {'unknown','submitting'} for r in requests) else status['status'],stage=status.get('progress',{}),nodes=status.get('nodes',[]),error=status.get('error'))
            if status['status']=='succeeded':task.update(status='succeeded',result=status['result'])
        except Exception as exc:task.update(status='failed',error=str(exc))
        with db.transaction() as c:
            old=db.get(c,'task',tid)
            if old.get('stop_requested'):
                task['stop_requested']=True
                if task['status'] not in {'succeeded','failed','cancelled'}:task['status']='stopping'
            db.put(c,'task',tid,task,pid,True)
            if db.digest(old)!=db.digest(task):db.emit(c,pid,'task/updated',{'id':tid,'status':task['status'],'error':task.get('error')})
            if task['status'] in {'succeeded','failed','cancelled'}:
                from .commands import enqueue
                enqueue(c,pid,'terminal:'+tid,'制作任务 '+tid+' 状态 '+task['status']+'，请检查结果并继续审片和交付。',task.get('epoch',0))
            if task['status']=='succeeded' and task['document']['tasks']:
                row=db.get(c,'usage',tid);row.update(state='succeeded',bill_status='待供应商对账');db.put(c,'usage',tid,row,pid,True)
            for node in task.get('nodes',[]):
                info=task.get('generation_keys',{}).get(node['id'])
                if not info or node['status']!='succeeded' or not node.get('result'):continue
                key=pid+':'+info['key']
                try:db.get(c,'generated',key);continue
                except ValueError:pass
                output=node['result'];fid=db.uid();source=contained(output['path']);target=DATA/'projects'/pid/'files'/(fid+source.suffix)
                target.parent.mkdir(exist_ok=True);shutil.copyfile(source,target)
                if sha(target)!=output['sha256']:raise ValueError('生成素材哈希不一致')
                file={'id':fid,'project':pid,'name':info['name']+source.suffix,'kind':'video','size':target.stat().st_size,'sha256':output['sha256'],'path':str(target),'generated_by':tid}
                db.put(c,'file',fid,file,pid);db.put(c,'generated',key,{'project':pid,'file_id':fid,'duration':info['duration'],'build_id':task['build_id']},pid)
                db.emit(c,pid,'file/added',{'id':fid,'name':file['name']})

def control(pid,tid,action):
    from .commands import stop,prepare
    if action=='stop':
        with db.transaction() as c:db.get(c,'task',tid,pid)
        return stop(pid)
    if action=='resume':
        with db.transaction() as c:db.get(c,'task',tid,pid)
        return {'status':'waiting_user','quote':prepare(pid)}
    raise ValueError('未知操作')

def requests(pid,tid,refresh=False):
    with db.transaction() as c:t=db.get(c,'task',tid,pid)
    if not t.get('build_id'):return []
    rows=[{k:r.get(k) for k in ['id','task','state','remote','cost','error']} for r in Ledger(engine(pid).store).inspect(t['build_id'])]
    if refresh and any(r['remote'] for r in rows):
        import httpx
        endpoint=media_endpoint();key=media_key()
        with httpx.Client(timeout=30,follow_redirects=False,trust_env=False) as client:
            for row in rows:
                if not row['remote']:continue
                try:
                    response=client.get(endpoint['baseUrl'].rstrip('/')+'/contents/generations/tasks/'+row['remote'],headers={'Authorization':'Bearer '+key})
                    if response.status_code==200:
                        value=response.json();row.update(remote_status=value.get('status'),provider_usage=value.get('usage'))
                    else:row['query_status']='HTTP '+str(response.status_code)
                except Exception:row['query_status']='查询暂不可用；未重新提交'
    return rows

def reconcile(pid,tid,rid,remote_id,confirmed,command):
    if not confirmed:raise ValueError('请先在服务商确认此远程 ID 属于该请求')
    import re
    if not re.fullmatch(r'cgt-[A-Za-z0-9-]{1,100}',remote_id):raise ValueError('无效的 Ark 任务标识')
    rows=requests(pid,tid)
    if not any(r['id']==rid and r['state'] in {'submitting','unknown'} for r in rows):raise ValueError('此请求无需手工核对')
    import httpx
    endpoint=media_endpoint()
    with httpx.Client(timeout=30,follow_redirects=False,trust_env=False) as client:
        r=client.get(endpoint['baseUrl'].rstrip('/')+'/contents/generations/tasks/'+remote_id,headers={'Authorization':'Bearer '+media_key()})
    if r.status_code!=200 or r.json().get('id')!=remote_id or r.json().get('model')!=endpoint['modelId']:raise ValueError('远程任务与当前账户/模型不匹配')
    result=Ledger(engine(pid).store).reconcile({'commandId':command,'requestId':rid,'remoteId':remote_id})
    with db.transaction() as c:db.emit(c,pid,'request/reconciled',{'id':rid,'remote':remote_id})
    control(pid,tid,'resume');return result

def deliver(pid,tid,allow_baked,command):
    from app.workbench_d.commercial.resources import slot,scoped_check
    with slot('paired-delivery',scoped_check(engine(pid).store)) as lease:
        return _deliver(pid,tid,allow_baked,command,lease.check)


def _deliver(pid,tid,allow_baked,command,check):
    os.environ['D_JIANYING_PYTHON']=str(ROOT/'.venv-jianying/Scripts/python.exe')
    for key in ['ffmpeg','ffprobe']:
        if CONFIG.get(key):os.environ['D_'+key.upper()]=CONFIG[key]
    with db.transaction() as c:
        task=db.get(c,'task',tid,pid)
        if task['status']!='succeeded':raise ValueError('制作成功后才能交付')
        installer_hash=sha(ROOT/'scripts/install_draft.py')
        did=db.digest({'task':tid,'baked':allow_baked,'installer':installer_hash,'packager':2})[:32]
        receipt=db.once(c,command,{'op':'delivery','project':pid,'task':tid,'baked':allow_baked},lambda:{'intent':did})
        # Old command receipts still return the original immutable delivery.
        if receipt.get('zip_path'):return receipt
        try:existing=db.get(c,'delivery',did,pid)
        except ValueError:existing=None
    if existing:
        if sha(existing['zip_path'])!=existing['zip_sha256'] or sha(existing['preview_path'])!=existing['preview_sha256']:raise ValueError('已有交付损坏；拒绝覆盖不可变交付')
        return existing
    # No control-store write lock during rendering, serialization or packaging.
    e=engine(pid);d=Drafts(e)
    receipt=e.deliver({'commandId':'delivery-'+tid,'buildId':task['build_id']})
    choice=d.choose_export({'commandId':'choice-'+tid+'-'+str(allow_baked),'deliveryId':receipt['deliveryId'],'format':'jianying','allowBaked':allow_baked})
    draft=d.export_draft({'commandId':'export-'+tid+'-'+str(allow_baked),'choiceId':choice['choiceId'],'name':'VideoCopyer-'+str(task['revision'])})
    folder=DATA/'projects'/pid/'deliveries'/did;folder.mkdir(parents=True,exist_ok=True)
    movie=folder/'preview.mp4'
    if not movie.exists():
        pending=folder/'preview.partial.mp4'
        try:
            shutil.copyfile(receipt['path'],pending);check();os.replace(pending,movie)
        finally:
            if pending.exists():pending.unlink()
    if sha(movie)!=receipt['sha256']:raise ValueError('交付预览完整性校验失败')
    zpath=folder/'jianying.zip';source=Path(draft['path'])
    members={name:contained(source/name,source) for name in draft['files'] if not name.startswith(('frames-','raster/'))}
    if (source/'d-manifest.json').is_file():members['d-manifest.json']=source/'d-manifest.json'
    manifest={'project':pid,'revision':task['revision'],'build_id':task['build_id'],'preview_sha256':sha(movie),'document_hash':task['document_hash'],'editor_ui_verified':False,'limitations':draft['limitations'],'baked':draft['baked'],'files':{name:sha(path) for name,path in members.items()}}
    temp=folder/(db.uid()+'.partial')
    from .artifact_io import zip_member
    try:
        with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
            for name,path in members.items():zip_member(z,path,'draft/'+name,check)
            z.writestr('manifest.json',db.dump(manifest));z.write(ROOT/'scripts/install_draft.py','install_draft.py');z.writestr('README.txt','关闭剪映。运行 python install_draft.py --destination 新目录。不要直接打开 ZIP 内草稿。实机兼容性尚待验收。')
        check()
    except BaseException:
        if temp.exists():temp.unlink()
        raise
    with db.transaction() as c:
        try:
            existing=db.get(c,'delivery',did,pid)
            temp.unlink()
            return existing
        except ValueError:pass
        os.replace(temp,zpath)
        row={'id':did,'project':pid,'revision':task['revision'],'task_id':tid,'build_id':task['build_id'],'preview_path':str(movie),'zip_path':str(zpath),'preview_sha256':sha(movie),'zip_sha256':sha(zpath),'installer_sha256':installer_hash,'limitations':draft['limitations'],'baked':draft['baked'],'editor_ui_verified':False}
        db.put(c,'delivery',did,row,pid);db.emit(c,pid,'delivery/created',{'id':did,'revision':row['revision']})
        return row

import hashlib, mimetypes, time
from pathlib import Path
from . import db
from .config import DATA, contained
from .models import Plan

def create(command, text):
    with db.transaction() as c:
        def action():
            pid=db.uid(); folder=DATA/'projects'/pid; folder.mkdir(parents=True)
            p={'id':pid,'project':pid,'title':text[:45] or '未命名项目','revision':0,'thread_id':None,'status':'idle','created':time.time()}
            db.put(c,'project',pid,p,pid)
            db.put(c,'plan',pid+':0',{'project':pid,'revision':0,'plan':Plan(title=p['title']).model_dump(),'hash':db.digest({})},pid)
            message(c,pid,'user',text)
            db.emit(c,pid,'project/created',{'id':pid})
            return p
        return db.once(c,command,{'op':'create','text':text},action)

def message(c,pid,role,text,**extra):
    mid=db.uid(); value={'id':mid,'project':pid,'role':role,'text':text,'at':time.time(),**extra}
    db.put(c,'message',mid,value,pid); db.emit(c,pid,'message',value); return value

def save_plan(pid,base,plan,command):
    plan=Plan.model_validate(plan).model_dump()
    with db.transaction() as c:
        def action():
            p=db.get(c,'project',pid)
            if p['revision']!=base: raise ValueError('规划已更新，请刷新后再保存')
            refs=[x['file_id'] for x in plan['shots'] if x['file_id']]+[x['reference_file_id'] for x in plan['characters'] if x['reference_file_id']]
            if plan['audio_file_id']: refs.append(plan['audio_file_id'])
            for fid in refs: db.get(c,'file',fid,pid)
            rev=base+1; row={'project':pid,'revision':rev,'plan':plan,'hash':db.digest(plan)}
            db.put(c,'plan',f'{pid}:{rev}',row,pid)
            p.update(revision=rev,title=plan['title']); db.put(c,'project',pid,p,pid,True)
            db.emit(c,pid,'plan/saved',row); return row
        return db.once(c,command,{'op':'plan','project':pid,'base':base,'plan':plan},action)

def snapshot(pid):
    with db.transaction() as c:
        p=db.get(c,'project',pid)
        from sqlalchemy import select,func
        cursor=c.execute(select(func.max(db.events.c.seq)).where(db.events.c.project==pid)).scalar() or 0
        return {**p,'event_cursor':cursor, 'planning':db.get(c,'plan',f'{pid}:{p["revision"]}'), **{k:db.all(c,kind,pid) for k,kind in [('messages','message'),('files','file'),('tasks','task'),('deliveries','delivery'),('questions','question'),('usage','usage')]}}

def add_file(pid,name,data):
    suffix=Path(name).suffix.lower()
    kinds={'.png':'image','.jpg':'image','.jpeg':'image','.webp':'image','.mp4':'video','.mov':'video','.wav':'audio','.mp3':'audio','.m4a':'audio','.txt':'text','.srt':'text','.md':'text'}
    if suffix not in kinds: raise ValueError('支持图片、视频、音频与文本附件')
    if not data or len(data)>100*1024*1024: raise ValueError('附件需为 1 字节至 100 MB')
    sha=hashlib.sha256(data).hexdigest()
    with db.transaction() as c:
        db.get(c,'project',pid)
        for f in db.all(c,'file',pid):
            if f['sha256']==sha and f['name']==name: return f
        fid=db.uid(); path=DATA/'projects'/pid/'files'/(fid+suffix); path.parent.mkdir(exist_ok=True); path.write_bytes(data)
        if kinds[suffix]=='image':
            from PIL import Image
            try:
                with Image.open(path) as im: im.verify()
            except Exception:
                path.unlink(); raise ValueError('图片文件无法解码')
        row={'id':fid,'project':pid,'name':Path(name).name,'kind':kinds[suffix],'size':len(data),'sha256':sha,'path':str(path)}
        db.put(c,'file',fid,row,pid); db.emit(c,pid,'file/added',{k:v for k,v in row.items() if k!='path'}); return row

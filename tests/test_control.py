import os, sys, json, io, tempfile
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
os.environ['VC_DATA']=tempfile.mkdtemp(prefix='vc-tests-')
sys.path.insert(0,str(ROOT/'server'))
from local import db,projects,production
from local.config import CONFIG
from local.main import app,CSRF
from fastapi.testclient import TestClient
from PIL import Image

def new():return projects.create(db.uid(),'测试项目')
def image(pid):
    stream=io.BytesIO();Image.new('RGB',(32,32),'navy').save(stream,format='PNG')
    return projects.add_file(pid,'sample.png',stream.getvalue())
def plan(fid):return {'title':'测试','shots':[{'id':'s1','title':'镜头','file_id':fid,'duration':1,'subtitle':'测试'}]}

def test_create_idempotency_and_collision():
    key=db.uid();a=projects.create(key,'需求');assert projects.create(key,'需求')['id']==a['id']
    assert len(projects.snapshot(a['id'])['messages'])==1
    with pytest.raises(ValueError):projects.create(key,'不同需求')

def test_plan_cas_and_immutable_history():
    p=new();f=image(p['id']);key=db.uid();a=projects.save_plan(p['id'],0,plan(f['id']),key)
    assert projects.save_plan(p['id'],0,plan(f['id']),key)==a
    with pytest.raises(ValueError):projects.save_plan(p['id'],0,plan(f['id']),db.uid())
    with db.transaction() as c:assert db.get(c,'plan',p['id']+':0')['plan']['shots']==[]

def test_file_ownership():
    p=new();other=new();f=image(other['id'])
    with pytest.raises(ValueError):projects.save_plan(p['id'],0,plan(f['id']),db.uid())
    client=TestClient(app,base_url='http://127.0.0.1:8765')
    assert client.get(f'/api/projects/{p["id"]}/files/{f["id"]}').status_code==409

def test_origin_and_write_protection():
    client=TestClient(app,base_url='http://127.0.0.1:8765')
    assert client.get('/api/bootstrap',headers={'Host':'evil.example'}).status_code==403
    assert client.get('/api/bootstrap',headers={'Origin':'https://evil.example'}).status_code==403
    assert client.post('/api/projects',json={}).status_code==403

def test_total_budget_atomic_and_unknown_retained():
    with db.transaction() as c:
        request=db.uid();amount=int(CONFIG['test_budget_cny']*1e6)
        db.reserve(c,request,'p',amount,'media',{})
        assert db.reserve(c,request,'p',amount,'media',{})['id']==request
        row=db.get(c,'usage',request);row['state']='reconciling';db.put(c,'usage',request,row,'p',True)
        with pytest.raises(ValueError):db.reserve(c,db.uid(),'p',1,'planning',{})
        row['state']='released';db.put(c,'usage',request,row,'p',True)

def test_build_revision_binding_and_dedupe():
    p=new();f=image(p['id']);projects.save_plan(p['id'],0,plan(f['id']),db.uid())
    q=production.quote(p['id'],1)
    a=production.submit(p['id'],1,db.uid(),q['quote_hash'])
    assert production.submit(p['id'],1,db.uid(),q['quote_hash'])['id']==a['id']
    changed=plan(f['id']);changed['shots'][0]['subtitle']='新版本'
    projects.save_plan(p['id'],1,changed,db.uid())
    with pytest.raises(ValueError):production.submit(p['id'],1,db.uid(),q['quote_hash'])
    with db.transaction() as c:assert db.get(c,'task',a['id'])['document']['layers'][1]['text']=='测试'

def test_file_bytes_integrity():
    p=new();f=image(p['id']);projects.save_plan(p['id'],0,plan(f['id']),db.uid())
    Path(f['path']).write_bytes(b'corrupted')
    with pytest.raises(ValueError):production.quote(p['id'],1)

def test_agent_never_exposes_platform_paths():
    from local.bridge import public_snapshot
    p=new();image(p['id'])
    assert 'path' not in public_snapshot(p['id'])['files'][0]

def test_unknown_command_not_paid_again():
    p=new();f=image(p['id']);projects.save_plan(p['id'],0,plan(f['id']),db.uid())
    q=production.quote(p['id'],1);a=production.submit(p['id'],1,'once-'+p['id'],q['quote_hash'])
    with db.transaction() as c:
        a['status']='reconciling';db.put(c,'task',a['id'],a,p['id'],True)
    assert production.submit(p['id'],1,db.uid(),q['quote_hash'])['id']==a['id']

def test_cross_process_budget_admission():
    import concurrent.futures, subprocess
    env={**os.environ,'PYTHONPATH':str(ROOT/'server')}
    source="from local import db;\ntry:\n with db.transaction() as c: db.reserve(c,db.uid(),'concurrent',70000000,'media',{})\n print('accepted')\nexcept ValueError: print('blocked')"
    def run(_):return subprocess.check_output([sys.executable,'-c',source],env=env,text=True).strip()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,range(2)))
    assert sorted(results)==['accepted','blocked']

def test_zip_relocation_no_overwrite_and_no_traversal(tmp_path):
    import importlib.util,zipfile
    spec=importlib.util.spec_from_file_location('installer',ROOT/'scripts/install_draft.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    destination=tmp_path/'existing';destination.mkdir()
    with pytest.raises(ValueError,match='已存在'):module.install(tmp_path/'absent.zip',destination)
    package=tmp_path/'malicious.zip'
    with zipfile.ZipFile(package,'w') as z:z.writestr('manifest.json',json.dumps({'files':{'../escape.txt':'0'*64}}))
    with pytest.raises(ValueError):module.install(package,tmp_path/'new')
    assert not (tmp_path/'escape.txt').exists()

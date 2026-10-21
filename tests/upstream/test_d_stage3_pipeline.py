import json,os,time,threading,wave,struct
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import pytest
from PIL import Image,ImageChops
from app.workbench_d.commercial.schema import Project
from app.workbench_d.commercial.engine import Engine
from app.workbench_d.commercial.worker import run
from app.workbench_d.commercial.render import sha,Rasterizer,command,binary,render
from app.workbench_d.commercial.media import process
from app.workbench_d.commercial.ledger import Ledger
from app.workbench_d.commercial.speech import normalize_transcript
from app.workbench_d.commercial.components import SCENES,EFFECTS

def asset(path,kind='image',id='source'):return dict(id=id,kind=kind,path=str(path),sha256=sha(path),license='test-created',source='test fixture')
def task(**kwargs):return dict(id='generated',kind='generation',model='fixture',provider='mock',depends_on=[],inputs=[],input_roles=[],options={},output_kind='image',budget=None,max_cost_micros=10,prompt='fixture',**kwargs)

@pytest.fixture
def mock(tmp_path,monkeypatch):
    picture=tmp_path/'mock.png';Image.new('RGBA',(64,64),'#c08040').save(picture)
    state={'posts':0,'gets':0,'ambiguous':False,'running':False,'cancel':0}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            state['posts']+=1;state['body']=json.loads(self.rfile.read(int(self.headers['Content-Length'])));state['key']=self.headers['Idempotency-Key']
            if state['ambiguous']:self.connection.close();return
            self.send_response(200);self.end_headers();self.wfile.write(b'{"id":"remote-1"}')
        def do_GET(self):
            self.send_response(200);self.end_headers()
            if self.path=='/asset':self.wfile.write(picture.read_bytes());return
            state['gets']+=1;self.wfile.write(json.dumps({'status':'cancelled' if state['cancel'] else 'running' if state['running'] else 'succeeded','outputs':[url+'/asset',url+'/asset']}).encode())
        def do_DELETE(self):state['cancel']+=1;self.send_response(200);self.end_headers();self.wfile.write(b'{}')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);url=f'http://127.0.0.1:{server.server_port}'
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    config=tmp_path/'providers.json';config.write_text(json.dumps({'mock':{'base_url':url,'account':'test-account','currency':'USD','credential_env':'D_TEST_FAKE_KEY','models':{'fixture':{'output_kind':'image','documentation':'local mock contract','fields':[],'submit':'/submit','poll':'/poll/{id}','cancel':'/cancel/{id}','output_path':'outputs','poll_seconds':.1,'quote':{'upperMicros':10,'expires':time.time()+3600}}}}}))
    monkeypatch.setenv('D_PROVIDERS',str(config));monkeypatch.setenv('D_TEST_FAKE_KEY','test-only-not-a-secret');monkeypatch.setattr(Engine,'launch',lambda *a:None)
    engine=Engine(tmp_path/'data')
    yield engine,state
    server.shutdown();server.server_close();thread.join()

def project(engine):
    p=engine.create(dict(commandId='create',name='remote',document=dict(width=64,height=64,frames=2,tasks=[task()],layers=[dict(id='image',kind='image',asset='generated',width=64,height=64,end=2)])))
    ledger=Ledger(engine.store);grant=ledger.authorize(dict(commandId='grant',projectId=p['projectId'],revision=0,account='test-account',currency='USD',limitMicros=20,concurrency=1))
    b=engine.submit(dict(commandId='submit',projectId=p['projectId'],revision=0));return b['buildId'],ledger

def test_generation_dag_multiple_artifacts_recovery(mock):
    engine,state=mock;bid,ledger=project(engine);run(bid,engine.store)
    b=engine.store.build(bid);assert b['status']=='succeeded',b['error'];assert state['posts']==1
    node=next(n for n in b['nodes'] if n['id']=='generated');assert len(node['result']['artifacts'])==2
    assert all(sha(a['path'])==a['sha256'] for a in node['result']['artifacts'])
    run(bid,engine.store);assert state['posts']==1
    assert ledger.inspect(bid)[0]['state']=='succeeded'
    assert state['key']==ledger.inspect(bid)[0]['id']

def test_ambiguous_submission_never_repaid(mock):
    engine,state=mock;bid,ledger=project(engine);state['ambiguous']=True;run(bid,engine.store)
    assert engine.store.build(bid)['status']=='failed';assert state['posts']==1
    node=next(n for n in engine.store.build(bid)['nodes'] if n['id']=='generated')
    assert node['status']=='failed' and node['result']['execution']['model']=='fixture'
    engine.retry(dict(commandId='retry1',buildId=bid));run(bid,engine.store)
    assert 'SUBMISSION_UNKNOWN' in engine.store.build(bid)['error'];assert state['posts']==1
    rid=ledger.inspect(bid)[0]['id'];ledger.reconcile(dict(commandId='reconcile',requestId=rid,remoteId='remote-1'))
    engine.retry(dict(commandId='retry2',buildId=bid));run(bid,engine.store)
    assert engine.store.build(bid)['status']=='succeeded';assert state['posts']==1


@pytest.mark.parametrize('phase',['unknown','accepted','download','cancel'])
def test_expired_quote_recovery_never_submits_again(mock,monkeypatch,phase):
    import types
    import app.workbench_d.commercial.providers as providers
    engine,state=mock;bid,ledger=project(engine)
    if phase in ('unknown','accepted','cancel'):
        state['ambiguous']=True;run(bid,engine.store)
    else:
        original=providers.request
        def fail_download(url,*args,**kwargs):
            if url.endswith('/asset'):raise OSError('fixture download interrupted')
            return original(url,*args,**kwargs)
        monkeypatch.setattr(providers,'request',fail_download);run(bid,engine.store);monkeypatch.setattr(providers,'request',original)
    rid=ledger.inspect(bid)[0]['id']
    if phase in ('accepted','cancel'):ledger.reconcile(dict(commandId='reconcile-expiry',requestId=rid,remoteId='remote-1'))
    monkeypatch.setattr(providers,'time',types.SimpleNamespace(time=lambda:time.time()+7200,monotonic=time.monotonic,sleep=time.sleep))
    # New service instances reconstruct both the host and ledger from disk.
    resumed=Engine(engine.store.root.parent);resumed.retry(dict(commandId='expired-retry',buildId=bid))
    if phase=='cancel':state['cancel']=1
    run(bid,resumed.store);b=resumed.store.build(bid)
    assert state['posts']==1
    if phase=='unknown':assert 'SUBMISSION_UNKNOWN' in b['error'] and state['gets']==0
    elif phase=='cancel':assert b['status']=='failed' and ledger.inspect(bid)[0]['state']=='failed'
    else:assert b['status']=='succeeded',b['error'];assert state['gets']>0


def test_expired_quote_blocks_new_post_and_reservation(mock,monkeypatch):
    import types
    import app.workbench_d.commercial.providers as providers
    engine,state=mock;bid,ledger=project(engine)
    monkeypatch.setattr(providers,'time',types.SimpleNamespace(time=lambda:time.time()+7200,monotonic=time.monotonic,sleep=time.sleep))
    run(bid,engine.store)
    assert 'fresh pinned price quote required' in engine.store.build(bid)['error']
    assert state['posts']==0 and ledger.inspect(bid)==[]


def test_expired_quote_recovery_in_fresh_host_and_worker_process(mock):
    import subprocess,sys
    engine,state=mock;bid,ledger=project(engine);state['ambiguous']=True;run(bid,engine.store)
    rid=ledger.inspect(bid)[0]['id'];ledger.reconcile(dict(commandId='process-reconcile',requestId=rid,remoteId='remote-1'))
    # Only provider pricing time advances. Lease/heartbeat/worker clocks remain real.
    code="""
import sys,time,types
from app.workbench_d.commercial.engine import Engine
from app.workbench_d.commercial.worker import run
import app.workbench_d.commercial.providers as providers
providers.time=types.SimpleNamespace(time=lambda:time.time()+7200,monotonic=time.monotonic,sleep=time.sleep)
Engine.launch=lambda *args:None
engine=Engine(sys.argv[1]);engine.retry(dict(commandId='fresh-host-retry',buildId=sys.argv[2]))
run(sys.argv[2],engine.store)
assert engine.store.build(sys.argv[2])['status']=='succeeded',engine.store.build(sys.argv[2])['error']
"""
    result=subprocess.run([sys.executable,'-c',code,str(engine.store.root.parent),bid],capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stdout+result.stderr
    assert state['posts']==1 and state['gets']>0
    assert ledger.inspect(bid)[0]['remote']=='remote-1'

def test_budget_atomic_reservation_and_dispatch(mock):
    engine,state=mock;bid,ledger=project(engine);build=engine.store.build(bid)
    def reserve(n):
        try:return ledger.reserve(build,{**task(),'id':'t'+str(n)},'test-account',{'n':n},'USD')
        except ValueError:return None
    with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(reserve,range(8)))
    good=[r for r in rows if r];assert len(good)==1
    rid=good[0]['id']
    with ThreadPoolExecutor(max_workers=8) as pool:claimed=list(pool.map(lambda _:ledger.claim_dispatch(rid),range(8)))
    assert sum(claimed)==1
    with pytest.raises(ValueError,match='matching'):ledger.reserve(build,task(),'other-account',{},'USD')
    with pytest.raises(ValueError,match='matching'):ledger.reserve(build,task(),'test-account',{},'EUR')
    with pytest.raises(ValueError,match='matching'):ledger.reserve({**build,'revision':1},task(),'test-account',{},'USD')

def test_remote_cancel_does_not_resubmit(mock):
    engine,state=mock;bid,ledger=project(engine);state['running']=True
    worker=threading.Thread(target=run,args=(bid,engine.store));worker.start()
    deadline=time.monotonic()+15
    while state['gets']==0 and time.monotonic()<deadline:time.sleep(.1)
    assert state['gets'];engine.cancel(dict(commandId='cancel',buildId=bid));worker.join(10);assert not worker.is_alive()
    assert state['posts']==1 and state['cancel']==1
    assert engine.store.build(bid)['status']=='cancelled'
    engine.retry(dict(commandId='retry',buildId=bid));run(bid,engine.store);assert state['posts']==1

def test_media_edges_motion_audio_and_dag(tmp_path,monkeypatch):
    source=tmp_path/'source.png';im=Image.new('RGBA',(64,64),'lime');im.paste('red',(16,16,48,48));im.save(source)
    inp=[asset(source)];key=process(dict(operation='chroma-key',options={}),inp,tmp_path/'key',lambda:None)
    result=Image.open(key['path']);assert result.getpixel((0,0))[3]==0;assert result.getpixel((32,32))==(255,0,0,255)
    frames=tmp_path/'frames';frames.mkdir()
    for n in range(4):
        im=Image.new('RGBA',(64,64),'lime');im.paste('red',(8+n*5,16,24+n*5,32));im.save(frames/f'{n:08d}.png')
    video=tmp_path/'source.mov';command([binary('ffmpeg'),'-v','error','-y','-framerate','4','-i',frames/'%08d.png','-c:v','png',video])
    matte=process(dict(operation='video-matte',options={}),[asset(video,'video')],tmp_path/'matte',lambda:None)
    for n in range(4):
        out=process(dict(operation='extract-frame',options={'frame':n}),[matte],tmp_path/('frame'+str(n)),lambda:None)
        frame=Image.open(out['path']);assert frame.getpixel((0,0))[3]==0;assert frame.getpixel((12+n*5,20))[3]==255
    audio=tmp_path/'audio.wav'
    with wave.open(str(audio),'wb') as wav:wav.setparams((1,2,48000,0,'NONE','none'));wav.writeframes(struct.pack('<h',10000)*48000)
    cut=process(dict(operation='audio-edit',options={'start':.1,'duration':.5,'fade_in':.1,'fade_out':.1}),[asset(audio,'audio')],tmp_path/'audio',lambda:None)
    with wave.open(cut['path'],'rb') as wav:
        assert wav.getnframes()==24000;data=struct.unpack('<'+'h'*24000,wav.readframes(24000));assert data[0]==0 and abs(data[-1])<10 and data[12000]==10000
    monkeypatch.setattr(Engine,'launch',lambda *a:None);engine=Engine(tmp_path/'data')
    p=engine.create(dict(commandId='create',name='media',document=dict(width=64,height=64,frames=3,assets=inp,tasks=[dict(id='key',kind='media',operation='chroma-key',inputs=['source'],output_kind='image')],layers=[dict(id='keyed',kind='image',asset='key',width=64,height=64,end=3)])))
    bid=engine.submit(dict(commandId='build',projectId=p['projectId'],revision=0))['buildId'];run(bid,engine.store)
    assert engine.store.build(bid)['status']=='succeeded',engine.store.build(bid)['error']

def test_transcript_provenance_missing_and_corrected_text():
    transcript=normalize_transcript({'words':[{'text':'Hello','start':0,'end':.2},{'text':'中','start':None,'end':None},{'text':'文','start':.3,'end':.4}]},'a'*64,'Hello 中文')
    assert transcript['words'][1]['missing'] and transcript['words'][1]['startSample'] is None
    assert transcript['words'][2]['startSample']==4800
    assert len({w['wordId'] for w in transcript['words']})==3
    with pytest.raises(ValueError):normalize_transcript({'words':[]},'a'*64,'Hello')


def test_reference_wire_protocols_and_unverified_contract_blocking():
    from app.workbench_d.commercial.provider_contracts import payload,contract,validate_contract
    t={**task(),'model':'seedance-2','inputs':['first','last','voice'],'input_roles':['first_frame','last_frame','reference_audio'],'output_kind':'video'}
    inputs=[{'kind':k} for k in ('image','image','audio')];urls=['https://fixture/first','https://fixture/last','https://fixture/voice']
    beat=payload(t,contract('beatapi',t['model'],'video'),inputs,urls)
    assert beat['images']==urls[:2] and beat['reference_audios']==urls[2:]
    ark=payload(t,contract('ark',t['model'],'video'),inputs,urls)
    assert [v.get('role') for v in ark['content'][1:]]==t['input_roles']
    pollo=payload(t,contract('pollo','minimax-h3','video'),inputs,urls)
    assert pollo['input']['imageTail']==urls[1] and pollo['input']['refs']==[{'type':'audio','url':urls[2]}]
    for provider in ('hiapi','monid','hypihub'):
        with pytest.raises(ValueError,match='pinned'):validate_contract(t,contract(provider,t['model'],'video'))


def test_local_model_process_boundary_and_seed_vc_adapter(tmp_path,monkeypatch):
    import sys
    from app.workbench_d.commercial.speech import execute
    import app.workbench_d.commercial.model_driver as driver
    audio=tmp_path/'source.wav'
    with wave.open(str(audio),'wb') as wav:wav.setparams((1,2,16000,0,'NONE','none'));wav.writeframes(struct.pack('<h',1000)*16000)
    # This is explicitly a protocol fixture, never a voice quality acceptance.
    entry=tmp_path/'fixture_seed_cli.py';entry.write_text('import sys,pathlib,shutil\na=sys.argv\nout=pathlib.Path(a[a.index("--output")+1]);out.mkdir(exist_ok=True)\nshutil.copyfile(a[a.index("--source")+1],out/"fixture.wav")\n')
    model=tmp_path/'fixture.weights';model.write_text('protocol fixture, not model weights')
    config=tmp_path/'adapters.json';config.write_text(json.dumps({'seed-vc-fixture':{'python':sys.executable,'script':driver.__file__,'script_sha256':sha(driver.__file__),'license':'D-owned adapter; model separate','operations':['voice-convert'],'weights':[dict(name=name,path=str(path),sha256=sha(path),license='test fixture') for name,path in [('entry',entry),('model',model),('config',model)]]}}))
    monkeypatch.setenv('D_MODEL_ADAPTERS',str(config))
    t={**task(),'kind':'speech','operation':'voice-convert','provider':'seed-vc-fixture','output_kind':'audio'}
    value=execute(t,[asset(audio,'audio'),asset(audio,'audio','reference')],tmp_path/'run',lambda:None)
    assert value['sha256']==sha(audio) and value['source_hashes']==[sha(audio),sha(audio)]
    assert 'requires independent acceptance' in value['quality']


def test_corrected_transcript_drives_captions(tmp_path):
    transcript=normalize_transcript({'words':[{'text':'Agpyj','start':0,'end':.5},{'text':'中','start':.5,'end':1}]},'a'*64,'Agpyj 中')
    file=tmp_path/'transcript.json';file.write_text(json.dumps(transcript));font=asset(Path(os.environ['D_TEST_FONT']),'font','font')
    spec=dict(width=320,height=100,frames=30,assets=[font,asset(file,'transcript','transcript')],layers=[dict(id='caption',kind='text',transcript='transcript',fonts=['font'],font_size=24,end=30,width=320,height=100)])
    r=Rasterizer(Project.model_validate(spec),tmp_path);r.prepare();a=r.frame(0);b=r.frame(20)
    assert ImageChops.difference(a.convert('RGB'),b.convert('RGB')).getbbox()
    transcript['words'][1].update(missing=True,startSample=None,endSample=None);file.write_text(json.dumps(transcript));spec['assets'][1]=asset(file,'transcript','transcript')
    with pytest.raises(ValueError,match='unaligned'):Rasterizer(Project.model_validate(spec),tmp_path).prepare()

def test_every_component_and_effect_renders_real_frames(tmp_path):
    font=asset(Path(os.environ['D_TEST_FONT']),'font','font');contact=Image.new('RGB',(4*320,7*180),'#eeeeee')
    hashes={}
    for i,name in enumerate(SCENES+EFFECTS):
        props=dict(title='Agpyj 中文',items=[{'label':'Alpha','value':3},{'label':'Beta','value':2},{'label':'Gamma','value':1}],units=[dict(x=.2,y=.5,dx=.5)],text='Agpyj 中文',spans=[dict(text='Agpyj ',color='#fecc20'),dict(text='中文',color='#ffffff')])
        layer=dict(id='component',kind='component',component=name,props=props,fonts=['font'],font_size=16,end=12,width=320,height=180)
        doc=Project.model_validate(dict(width=320,height=180,frames=12,background='#596878',assets=[font],layers=[layer]));r=Rasterizer(doc,tmp_path/name);r.prepare()
        first=r.frame(0);last=r.frame(11);middle=r.frame(5);folder=tmp_path/name;folder.mkdir(exist_ok=True);middle.save(folder/'middle.png');hashes[name]=sha(folder/'middle.png');contact.paste(middle.convert('RGB'),((i%4)*320,(i//4)*180))
        if name in ('Column','TopThree','Ranking','TierBoard','LastWar','LastWarHybrid','Flash','ScanLines','DirectionalMatte','WhipVeil','GlitchVeil','Grain','LightLeak','Bokeh','TVStatic'):assert ImageChops.difference(first.convert('RGB'),middle.convert('RGB')).getbbox(),name
    assert len(set(hashes.values()))>=len(hashes)-1
    contact.save(tmp_path/'components-contact.png')
    (tmp_path/'components.json').write_text(json.dumps(hashes,indent=2))
    # Actual encoded parametric scene, separate from still-frame evidence.
    movie=render(Project.model_validate(dict(width=320,height=180,frames=12,assets=[font],layers=[dict(id='rank',kind='component',component='Ranking',props=dict(items=['One','Two']),fonts=['font'],font_size=16,end=12,width=320,height=180)])),tmp_path/'encoded')
    assert movie['frames']==12

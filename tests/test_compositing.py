"""Offline media and resource regressions; no provider credentials or requests."""
import copy,json,os,subprocess,sys,time
from pathlib import Path
import pytest
from PIL import Image,ImageChops
from app.workbench_d.commercial.render import render,legacy_render,binary,command,sha
from app.workbench_d.commercial.schema import upgrade
from app.workbench_d.commercial.render_plan import choose
from app.workbench_d.commercial.render_artifacts import final_frame,legacy_reference
from app.workbench_d.commercial.resources import slot,current

@pytest.fixture
def document(tmp_path):
    video=tmp_path/'source.mp4'
    command([binary('ffmpeg'),'-v','error','-y','-f','lavfi','-i','testsrc2=size=320x180:rate=30:duration=1',
             '-an','-c:v','libopenh264','-b:v','1000000','-pix_fmt','yuv420p',video])
    logo=tmp_path/'logo.png';Image.new('RGBA',(40,30),(15,125,210,128)).save(logo)
    font=Path(os.environ['D_TEST_FONT'])
    def asset(id,kind,p):return dict(id=id,kind=kind,path=str(p),sha256=sha(p),license='test',source='offline')
    return dict(width=320,height=180,frames=12,fps=dict(num=30,den=1),assets=[
        asset('v','video',video),asset('logo','image',logo),asset('font','font',font)],layers=[
        dict(id='a',kind='video',asset='v',end=6,width=320,height=180),
        dict(id='b',kind='video',asset='v',start=6,end=12,source_start=15,width=320,height=180),
        dict(id='logo',kind='image',asset='logo',x=275,y=5,end=12,width=40,height=30,track=2),
        dict(id='caption',kind='text',text='边缘 / Alpha',fonts=['font'],font_size=18,stroke=1,shadow=[2,2],
             x=10,y=135,width=300,height=40,start=2,end=10,track=3)])

def test_stream_all_frames_and_boundaries(document,tmp_path):
    p=upgrade(document);old=legacy_render(p,tmp_path/'old');new=render(p,tmp_path/'new')
    assert new['render_plan']['route']=='ffmpeg'
    assert new['result_version']==2 and 'frame_hashes' not in new
    assert len(list((tmp_path/'new').rglob('*.png')))==3
    for n in range(p.frames):
        a=final_frame(old,n);b=final_frame(new,n)
        with Image.open(a['path']) as x,Image.open(b['path']) as y:
            # Same-size SDR geometry must retain exact pixels, including cut and text endpoints.
            assert ImageChops.difference(x.convert('RGB'),y.convert('RGB')).getbbox() is None,n
    assert final_frame(new,6)['cache_hit']
    assert legacy_reference(old,6)['evidence_kind']=='pre_encode_reference'

def test_copy_eligibility_and_subtitle_cache(document,tmp_path):
    doc=copy.deepcopy(document);doc['frames']=30;doc['layers']=doc['layers'][:1];doc['layers'][0]['end']=30
    p=upgrade(doc);out=render(p,tmp_path/'copy')
    assert out['render_plan']['route']=='copy-file' and out['video_encodes']==0
    assert out['sha256']==doc['assets'][0]['sha256']
    cache=tmp_path/'cache'
    first=render(upgrade(document),tmp_path/'first',cache_root=cache)
    edited=copy.deepcopy(document);edited['layers'][-1]['text']='只改字幕'
    second=render(upgrade(edited),tmp_path/'second',cache_root=cache)
    assert first['static_cache_hits']==0 and second['static_cache_hits']==1
    assert not upgrade(edited).tasks and first['sha256']!=second['sha256']
    assert Path(first['path']).is_file()

def test_fallback_and_cancel_partial(document,tmp_path):
    document['layers'][-1]['fade_in']=2
    assert choose(upgrade(document))['route']=='legacy-png'
    out=render(upgrade(document),tmp_path/'fallback')
    assert out['result_version']==1 and out['frame_hashes']
    doc=copy.deepcopy(document);doc['layers'][-1]['fade_in']=0
    calls=0
    def check():
        nonlocal calls
        calls+=1
        if calls>18:raise InterruptedError('fixture stop')
    with pytest.raises(InterruptedError):render(upgrade(doc),tmp_path/'stopped',check)
    assert not (tmp_path/'stopped/output.mp4').exists()
    assert not (tmp_path/'stopped/output.partial.mp4').exists()

def test_shared_slot_wait_cancellable_and_nested(tmp_path,monkeypatch):
    root=tmp_path/'resource';monkeypatch.setenv('D_HEAVY_ROOT',str(root))
    ready=tmp_path/'ready'
    code="from app.workbench_d.commercial.resources import slot; from pathlib import Path; import time\nwith slot('holder'):\n Path(r'"+str(ready)+"').write_text('ready')\n time.sleep(30)"
    env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'server')}
    child=subprocess.Popen([sys.executable,'-c',code],env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        deadline=time.monotonic()+10
        while not ready.exists():
            assert child.poll() is None
            assert time.monotonic()<deadline
            time.sleep(.02)
        waited=[]
        def stop():
            if waited:raise InterruptedError('stop queued')
        with pytest.raises(InterruptedError):
            with slot('waiting',stop,lambda **kw:waited.append(kw)):pass
        assert waited[0]['stage']=='waiting_local'
    finally:child.kill();child.wait(timeout=10)
    with slot('after-crash') as a:
        with slot('nested') as b:assert a is b and current() is a
    assert json.loads((root/'owner.json').read_text())['status']=='released'

def test_dead_worker_reaps_real_media_tree(tmp_path,monkeypatch):
    import psutil
    root=tmp_path/'resource';monkeypatch.setenv('D_HEAVY_ROOT',str(root))
    code="from app.workbench_d.commercial.render import command,binary\ncommand([binary('ffmpeg'),'-v','error','-re','-f','lavfi','-i','testsrc2=size=64x64:rate=30','-f','null','-'],timeout=60)"
    env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'server')}
    child=subprocess.Popen([sys.executable,'-c',code],env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    media_pid=None
    try:
        deadline=time.monotonic()+10
        while not media_pid:
            try:
                owner=json.loads((root/'owner.json').read_text())
                if owner['children']:media_pid=owner['children'][0]['pid']
            except (FileNotFoundError,ValueError):pass
            assert time.monotonic()<deadline
            time.sleep(.02)
        assert psutil.pid_exists(media_pid)
    finally:child.kill();child.wait(timeout=10)
    with slot('replacement'):
        assert not psutil.pid_exists(media_pid)

def test_copy_video_audio_and_static_draft(document,tmp_path,monkeypatch):
    import wave
    from app.workbench_d.commercial.engine import Engine
    from app.workbench_d.commercial.drafts import Drafts
    audio=tmp_path/'voice.wav'
    with wave.open(str(audio),'wb') as f:
        f.setparams((1,2,48000,0,'NONE','not compressed'));f.writeframes(b'\x00\x00'*48000)
    doc=copy.deepcopy(document);doc['frames']=30;doc['layers']=doc['layers'][:1];doc['layers'][0]['end']=30
    doc['assets'].append(dict(id='voice',kind='audio',path=str(audio),sha256=sha(audio),license='test',source='offline'))
    doc['audio']=[dict(asset='voice',end=30)]
    out=render(upgrade(doc),tmp_path/'copy-audio')
    assert out['render_plan']['route']=='copy-video' and out['video_encodes']==0
    assert len(out['probe']['streams'])==2
    e=Engine(tmp_path/'core')
    p=e.create(dict(commandId='create',name='static draft',document=document))
    draft=Drafts(e).create(dict(commandId='draft',projectId=p['projectId'],revision=0,name='native',allowBaked=True))
    root=Path(draft['path'])
    assert not list(root.rglob('*.mov'))
    assert not list(root.rglob('decode-*'))
    native=json.loads((root/'native-input.json').read_text())
    assert len(native['layers'])==5
    assert [l['kind'] for l in native['layers']].count('video')==2
    assert draft['editorUIVerified'] is False

def test_lease_loss_does_not_overwrite_new_owner(tmp_path,monkeypatch):
    monkeypatch.setenv('D_HEAVY_ROOT',str(tmp_path/'resource'))
    with pytest.raises(InterruptedError):
        with slot('old') as lease:
            value=json.loads(lease.path.read_text());value['token']='replacement'
            lease.path.write_text(json.dumps(value))
            time.sleep(1.15);lease.check()
    assert json.loads(lease.path.read_text())['token']=='replacement'

def test_running_command_cancel_and_memory_guard(tmp_path,monkeypatch):
    import psutil
    from app.workbench_d.commercial.resources import POLICY
    monkeypatch.setenv('D_HEAVY_ROOT',str(tmp_path/'resource'))
    started=time.monotonic()
    def stop():
        if time.monotonic()-started>.25:raise InterruptedError('stop real decoder')
    with pytest.raises(InterruptedError):
        command([binary('ffmpeg'),'-v','error','-re','-f','lavfi','-i',
                 'testsrc2=size=128x128:rate=30','-f','null','-'],stop)
    assert time.monotonic()-started<3
    state=json.loads((tmp_path/'resource/owner.json').read_text())
    assert not state['children'] and state['status']=='released'
    budget=psutil.Process().memory_info().rss+96*1024**2
    monkeypatch.setitem(POLICY,'memory_bytes',budget)
    with pytest.raises((MemoryError,ValueError)):
        command([sys.executable,'-c',f"p=bytearray({budget*2});import time;time.sleep(5)"],timeout=10)
    state=json.loads((tmp_path/'resource/owner.json').read_text())
    assert not state['children'] and state['status']=='released'

def test_validation_and_export_stop_never_publish(document,tmp_path,monkeypatch):
    from app.workbench_d.commercial.engine import Engine
    from app.workbench_d.commercial.drafts import Drafts
    from app.workbench_d.commercial import flow
    from app.workbench_d.commercial.render import Rasterizer
    stopped=False
    def progress(**stage):
        nonlocal stopped
        if stage.get('stage')=='validating':stopped=True
    def check():
        if stopped:raise InterruptedError('stop validation')
    with pytest.raises(InterruptedError):render(upgrade(document),tmp_path/'validation',check,progress)
    assert not list((tmp_path/'validation').glob('output*.mp4'))
    e=Engine(tmp_path/'core');flow.initialize(e.store)
    p=e.create(dict(commandId='source',name='export stop',document=document))
    original=Rasterizer.layer_image
    def image(self,*args):
        value=original(self,*args);flow.stop(e.store);return value
    monkeypatch.setattr(Rasterizer,'layer_image',image)
    with pytest.raises(InterruptedError):
        Drafts(e).create(dict(commandId='export',projectId=p['projectId'],revision=0,name='stopped',allowBaked=True))
    with e.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM managed_drafts').fetchone()[0]==0
    assert not list((e.store.root/'drafts').rglob('draft_content.json'))

@pytest.mark.parametrize('fit,width,height',[('stretch',80,45),('stretch',160,90),('stretch',240,135),('contain',300,210),('cover',160,180),('stretch',640,360)])
def test_video_geometry_quality(document,tmp_path,fit,width,height):
    import math
    from PIL import ImageStat
    doc=copy.deepcopy(document);doc.update(width=640,height=360,frames=3)
    doc['layers']=doc['layers'][:1];doc['layers'][0].update(width=width,height=height,fit=fit,end=3)
    old=legacy_render(upgrade(doc),tmp_path/'old');new=render(upgrade(doc),tmp_path/'new')
    if (width,height)==(80,45):assert new['render_plan']['route']=='legacy-png'
    else:assert new['render_plan']['route']=='ffmpeg'
    values=[];reference_quality=[]
    def psnr(a,b):
        mse=sum(v*v for v in ImageStat.Stat(ImageChops.difference(a,b)).rms)/3
        return 10*math.log10(255**2/mse) if mse else 100
    for n in range(3):
        with Image.open(final_frame(old,n)['path']) as a,Image.open(final_frame(new,n)['path']) as b:
            a=a.convert('RGB').crop((0,0,width,height));b=b.convert('RGB').crop((0,0,width,height))
            values.append(psnr(a,b))
            with Image.open(tmp_path/'old/frames'/f'{n:08d}.png') as reference:
                reference=reference.convert('RGB').crop((0,0,width,height))
                reference_quality.append({'old':psnr(reference,a),'new':psnr(reference,b)})
    (tmp_path/'geometry-quality.json').write_text(json.dumps({'fit':fit,'size':[width,height],'psnr_db':values,
        'pillow_reference_psnr_db':reference_quality,'route':new['render_plan']['route']}))
    # Two lossy encodings are not ground truth for one another. Require both
    # bounded mutual differences and no material fidelity loss to the original.
    assert min(values)>=35,values
    assert all(q['new']>=q['old']-.1 for q in reference_quality),reference_quality

def test_tracked_brand_companion_is_not_frozen_to_one_image(document,tmp_path):
    from app.workbench_d.commercial.engine import Engine
    from app.workbench_d.commercial.drafts import Drafts
    from app.workbench_d.commercial.brand import target_binding
    doc=copy.deepcopy(document);doc['layers'].pop(1);doc['layers'][0]['end']=12
    logo=doc['layers'][1];logo.update(x=0,y=0)
    p=upgrade(doc)
    logo['brand_lock']=dict(mode='planar',target_layer='a',reviewed=True,
                           source_sha256=doc['assets'][1]['sha256'],target_binding=target_binding(p,p.layers[0]),
                           samples=[dict(frame=n,quad=[[10+n*3,10],[50+n*3,10],[50+n*3,40],[10+n*3,40]]) for n in range(12)])
    assert choose(upgrade(doc))['route']=='legacy-png'
    e=Engine(tmp_path/'core');created=e.create(dict(commandId='create',name='tracked',document=doc))
    draft=Drafts(e).create(dict(commandId='draft',projectId=created['projectId'],revision=0,name='tracked',allowBaked=True))
    folder=Path(draft['path'])
    assert (folder/'media/logo.mov').is_file()
    with Image.open(folder/'frames-logo/00000000.png') as a,Image.open(folder/'frames-logo/00000011.png') as b:
        assert ImageChops.difference(a,b).getbbox() is not None

def test_fractional_clock_and_multiple_audio_tracks(document,tmp_path):
    import math,struct,wave
    audio=tmp_path/'voice.wav'
    with wave.open(str(audio),'wb') as f:
        f.setparams((1,2,48000,0,'NONE','not compressed'))
        f.writeframes(b''.join(struct.pack('<h',round(1000*math.sin(i*2*math.pi*440/48000))) for i in range(48000)))
    doc=copy.deepcopy(document);doc['fps']=dict(num=30000,den=1001)
    doc['assets'].append(dict(id='voice',kind='audio',path=str(audio),sha256=sha(audio),license='test',source='offline'))
    doc['audio']=[dict(asset='voice',start=0,end=9,volume=.7,fade_in=2),
                  dict(asset='voice',start=3,end=12,source_start=3,volume=.4,fade_out=2)]
    old=legacy_render(upgrade(doc),tmp_path/'old');new=render(upgrade(doc),tmp_path/'new')
    assert new['probe']['streams'][0]['avg_frame_rate']=='30000/1001'
    def samples(result):
        return command([binary('ffmpeg'),'-v','error','-i',result['path'],'-map','0:a','-c:a','pcm_s16le','-f','hash','-hash','sha256','-'])
    assert samples(old)==samples(new)

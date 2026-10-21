"""S4-R1: compare retained samples through the real immutable draft/export path."""
import json,math,struct,wave
from copy import deepcopy
from pathlib import Path
import pytest
from PIL import Image,ImageDraw
from .test_d_stage4 import studio,call
from app.workbench_d.commercial.drafts import Drafts
from app.workbench_d.commercial.schema import Project,Layer
from app.workbench_d.commercial.render import Rasterizer,animated,sha,command,binary,render


def spec(manifest):return json.loads((Path(manifest['path'])/'d-project.json').read_text(encoding='utf8'))
def native(manifest):return json.loads((Path(manifest['path'])/'draft_content.json').read_text(encoding='utf8'))
def segment(document,name):return next(t['segments'][0] for t in document['tracks'] if t['name']==name)
def frame_time(frame):return round(frame*1000000/30)


def native_value(segment,prop,frame):
    keys=next(k['keyframe_list'] for k in segment['common_keyframes'] if k['property_type']==prop)
    time=frame_time(frame)-segment['target_timerange']['start']
    if time<=keys[0]['time_offset']:return keys[0]['values'][0]
    for a,b in zip(keys,keys[1:]):
        if time<=b['time_offset']:
            fraction=(time-a['time_offset'])/(b['time_offset']-a['time_offset'])
            return a['values'][0]+(b['values'][0]-a['values'][0])*fraction
    return keys[-1]['values'][0]


def make_draft(studio,tmp_path,kind='image',fade=False):
    engine,_,p=studio;doc=deepcopy(p['document']);doc['background']='#00000000';doc['output']='mov-alpha';doc['audio']=[];doc['layers']=doc['layers'][:1]
    if kind=='video':
        frames=tmp_path/'source-frames';frames.mkdir()
        for n in range(32):
            im=Image.new('RGBA',(64,64),(20+n*5,110,170,255));ImageDraw.Draw(im).rectangle((n,8,n+10,26),fill=(240,30,90,180));im.save(frames/f'{n:03d}.png')
        movie=tmp_path/'source.mov';command([binary('ffmpeg'),'-v','error','-y','-framerate','30','-i',frames/'%03d.png','-c:v','png','-pix_fmt','rgba',movie])
        doc['assets'].append(dict(id='movie',kind='video',path=str(movie),sha256=sha(movie),source='local generated moving frames',license='test fixture'))
        doc['layers'][0].update(kind='video',asset='movie')
    layer=doc['layers'][0];layer.update(start=2,end=28,source_start=2,opacity=.8)
    layer['keyframes']={key:[dict(frame=2,value=a,easing='linear'),dict(frame=27,value=b,easing='linear')] for key,a,b in [('x',2,70),('y',4,24),('scale',.6,1.4),('rotation',-10,20)]}
    layer['keyframes']['x'].insert(1,dict(frame=11,value=22,easing='linear'))
    if fade:layer.update(fade_in=20,fade_out=20) # Deliberately overlapping, with cut inside both fades.
    else:layer['keyframes']['opacity']=[dict(frame=2,value=.35,easing='linear'),dict(frame=27,value=.95,easing='linear')]
    p=call(engine,'edit',projectId=p['projectId'],baseRevision=0,document=doc)
    drafts=Drafts(engine);before=call(drafts,'create',projectId=p['projectId'],revision=1,name='S4-R1',allowBaked=False)
    return drafts,before


@pytest.mark.parametrize('kind',['image','video'])
@pytest.mark.parametrize('operation',['split','trim','one-frame'])
@pytest.mark.parametrize('fade',[False,True])
def test_retained_frames_pixels_and_native_motion(studio,tmp_path,kind,operation,fade):
    drafts,before=make_draft(studio,tmp_path,kind,fade)
    action=dict(op='split',id='picture',frame=15) if operation=='split' else dict(op='trim',id='picture',start=14 if operation=='one-frame' else 8,end=15 if operation=='one-frame' else 24)
    after=call(drafts,'edit',draftId=before['draftId'],baseRevision=0,expectedHash=before['nativeHash'],actions=[action])
    old,new=spec(before),spec(after);old_layer=Layer.model_validate(old['layers'][0]);old_native=segment(native(before),'picture');new_native=native(after)
    original=Rasterizer(Project.model_validate(old),tmp_path/'original');original.prepare()
    edited=Rasterizer(Project.model_validate(new),tmp_path/'edited');edited.prepare()
    checked=[];max_native_error=0
    for value in new['layers']:
        layer=Layer.model_validate(value);clip=segment(new_native,layer.id)
        assert clip['target_timerange']==dict(start=frame_time(layer.start),duration=frame_time(layer.end)-frame_time(layer.start))
        if kind=='video':assert clip['source_timerange']['start']==frame_time(old_layer.source_start+layer.start-old_layer.start)
        for points in layer.keyframes.values():
            assert points[0].frame==layer.start and points[-1].frame==layer.end-1
        for n in range(layer.start,layer.end):
            for key in old_layer.keyframes:
                assert animated(layer,key,n)==pytest.approx(animated(old_layer,key,n),abs=1e-12)
            # Exact RGBA bytes, including pixels hidden by alpha. No contact-sheet tolerance.
            assert original.frame(n).tobytes()==edited.frame(n).tobytes(),(kind,operation,fade,n)
            for keys in old_native['common_keyframes']:
                error=abs(native_value(old_native,keys['property_type'],n)-native_value(clip,keys['property_type'],n));max_native_error=max(max_native_error,error)
                # Native timestamps are integer microseconds: allow their <=1 us quantization,
                # not a frame-scale shift. Values and D raster comparisons above are separate.
                assert error<.0001,(n,keys['property_type'],error)
            checked.append(n)
    assert sha(Path(before['path'])/'draft_content.json')==before['nativeHash']
    (tmp_path/'retained-frame-evidence.json').write_text(json.dumps(dict(kind=kind,operation=operation,fade=fade,frames=checked,rgbaExact=True,maxNativeValueError=max_native_error,oldRevisionUnchanged=True,draftId=before['draftId']),indent=2))


@pytest.mark.parametrize('case',['smooth','hold','component','rect','composed-opacity'])
def test_baked_local_age_and_nonlinear_temporal_edits_rejected(studio,tmp_path,case):
    engine,_,p=studio;doc=deepcopy(p['document']);layer=doc['layers'][0]
    if case in ('smooth','hold'):layer['keyframes']={'x':[dict(frame=0,value=0,easing=case),dict(frame=29,value=80)]}
    elif case=='component':layer.update(kind='component',component='ColorWash',props={'strength':.6})
    elif case=='rect':layer.update(kind='rect',color='#ff44aa')
    else:layer.update(fade_in=20,keyframes={'opacity':[dict(frame=0,value=.2),dict(frame=29,value=.8)]})
    p=call(engine,'edit',projectId=p['projectId'],baseRevision=0,document=doc);drafts=Drafts(engine)
    before=call(drafts,'create',projectId=p['projectId'],revision=1,name=case,allowBaked=True);assert before['baked']
    for action in (dict(op='split',id='picture',frame=15),dict(op='trim',id='picture',start=5,end=25),dict(op='move',id='picture',start=0)):
        with pytest.raises(ValueError,match='TEMPORAL_EDIT_UNSUPPORTED.*local age'):
            call(drafts,'edit',draftId=before['draftId'],baseRevision=0,expectedHash=before['nativeHash'],actions=[action])
    with engine.store.connect() as db:assert db.execute('SELECT COUNT(*) FROM draft_revisions WHERE draft=?',(before['draftId'],)).fetchone()[0]==1
    assert not (Path(before['path']).parent/'1').exists()
    assert sha(Path(before['path'])/'draft_content.json')==before['nativeHash']


def test_repeated_cut_and_trim_before_first_after_last_key(studio,tmp_path):
    engine,_,p=studio;doc=deepcopy(p['document']);doc['audio']=[];doc['layers']=doc['layers'][:1]
    doc['layers'][0]['keyframes']={'x':[dict(frame=8,value=11),dict(frame=20,value=55)],'opacity':[dict(frame=8,value=.31),dict(frame=20,value=.83)]}
    p=call(engine,'edit',projectId=p['projectId'],baseRevision=0,document=doc);drafts=Drafts(engine)
    old=call(drafts,'create',projectId=p['projectId'],revision=1,name='Repeated cuts',allowBaked=False)
    current=call(drafts,'edit',draftId=old['draftId'],baseRevision=0,expectedHash=old['nativeHash'],actions=[dict(op='split',id='picture',frame=15)])
    current=call(drafts,'edit',draftId=old['draftId'],baseRevision=1,expectedHash=current['nativeHash'],actions=[dict(op='trim',id='picture',start=3,end=14),dict(op='trim',id='picture_split_15',start=17,end=27)])
    a=Rasterizer(Project.model_validate(spec(old)),tmp_path/'old');a.prepare()
    b=Rasterizer(Project.model_validate(spec(current)),tmp_path/'new');b.prepare()
    for n in [*range(3,14),*range(17,27)]:assert a.frame(n).tobytes()==b.frame(n).tobytes()
    assert sha(Path(old['path'])/'draft_content.json')==old['nativeHash']


@pytest.mark.parametrize('fade',[False,True])
def test_audio_volume_samples_and_fade_boundary(studio,tmp_path,fade):
    engine,_,p=studio;doc=deepcopy(p['document']);doc['output']='mov-alpha'
    source=tmp_path/'tone.wav'
    with wave.open(str(source),'wb') as out:
        out.setparams((1,2,48000,0,'NONE','not compressed'));out.writeframes(b''.join(struct.pack('<h',round(14000*math.sin(2*math.pi*431*n/48000))) for n in range(48000)))
    doc['assets']=[a for a in doc['assets'] if a['id']!='audio']+[dict(id='audio',kind='audio',path=str(source),sha256=sha(source),source='generated sine',license='test fixture')]
    if fade:doc['audio'][0].update(fade_in=20,fade_out=20)
    p=call(engine,'edit',projectId=p['projectId'],baseRevision=0,document=doc);drafts=Drafts(engine)
    before=call(drafts,'create',projectId=p['projectId'],revision=1,name='Audio',allowBaked=False)
    if fade:
        for action in (dict(op='split',target='audio',index=0,frame=15),dict(op='trim',target='audio',index=0,start=5,end=25)):
            with pytest.raises(ValueError,match='TEMPORAL_EDIT_UNSUPPORTED.*audio fade'):
                call(drafts,'edit',draftId=before['draftId'],baseRevision=0,expectedHash=before['nativeHash'],actions=[action])
        assert native(before)['materials']['audio_fades']
        assert drafts.inspect(dict(draftId=before['draftId']))['revision']==0
    else:
        def pcm(document,name):
            result=render(Project.model_validate(document),tmp_path/name);target=tmp_path/(name+'.pcm')
            command([binary('ffmpeg'),'-v','error','-y','-i',result['path'],'-vn','-ac','1','-ar','48000','-f','s16le',target]);return target.read_bytes()
        original=pcm(spec(before),'before-audio')
        split=call(drafts,'edit',draftId=before['draftId'],baseRevision=0,expectedHash=before['nativeHash'],actions=[dict(op='split',target='audio',index=0,frame=15)])
        assert original==pcm(spec(split),'after-split-audio')
        clips=[s for t in native(split)['tracks'] if t['type']=='audio' for s in t['segments']]
        assert [s['volume'] for s in clips]==[.4,.4]
        assert [s['source_timerange']['start'] for s in clips]==[0,500000]
        trimmed=call(drafts,'edit',draftId=split['draftId'],baseRevision=1,expectedHash=split['nativeHash'],actions=[dict(op='trim',target='audio',index=0,start=5,end=14)])
        samples=pcm(spec(trimmed),'after-trim-audio');assert samples[5*1600*2:14*1600*2]==original[5*1600*2:14*1600*2]
    assert sha(Path(before['path'])/'draft_content.json')==before['nativeHash']

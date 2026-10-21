"""Ordinary timeline → one FFmpeg video encode, without full-film PNG sequences."""
import json,os,shutil,time
from fractions import Fraction
from pathlib import Path
from PIL import Image,ImageColor
from .resources import POLICY
from .store import fingerprint

def static_state(raster,layer,cache,check):
    from .render import sha
    style=layer.model_dump(mode='json')
    for name in ('id','start','end','track'):style.pop(name,None)
    implementation={name:sha(Path(__file__).with_name(name)) for name in ('render.py','typography.py','render_ffmpeg.py')}
    key=fingerprint({'style':style,'canvas':[raster.p.width,raster.p.height],
                     'assets':{a.id:a.sha256 for a in raster.p.assets if a.id==layer.asset or a.id in layer.fonts},
                     'implementation':implementation})
    metadata=cache/(key+'.json');target=cache/(key+'.png')
    if metadata.is_file():
        value=json.loads(metadata.read_text())
        if value['bbox'] is None:return None,True
        if not target.is_file() or sha(target)!=value['sha256']:raise ValueError('Static state cache integrity mismatch')
        return {**value,'path':str(target)},True
    check()
    image=raster.layer_image(layer,layer.start)
    box=image.getchannel('A').getbbox()
    value={'bbox':box,'key':key}
    if box:
        image.crop(box).save(target)
        value['sha256']=sha(target)
    metadata.write_text(json.dumps(value),encoding='utf8')
    return ({**value,'path':str(target)} if box else None),False

def geometry(layer,stream):
    """Pillow-equivalent geometry; scaling kernel differences are quality-gated."""
    sw,sh=stream['width'],stream['height'];filters=['format=rgba']
    if layer.crop:
        x0,y0,x1,y1=layer.crop
        if x1>sw or y1>sh:raise ValueError(layer.id+': crop exceeds source')
        sw,sh=x1-x0,y1-y0;filters.append(f'crop={sw}:{sh}:{x0}:{y0}:exact=1')
    w,h=layer.width,layer.height
    if layer.fit=='cover':
        ratio=max(w/sw,h/sh);cw,ch=w/ratio,h/ratio
        x,y=(sw-cw)/2,(sh-ch)/2
        if any(abs(v-round(v))>1e-6 for v in (cw,ch,x,y)):
            raise ValueError('Fractional cover crop was not rejected by route preflight')
        if (round(cw),round(ch))!=(sw,sh):
            filters.append(f'crop={round(cw)}:{round(ch)}:{round(x)}:{round(y)}:exact=1');sw,sh=round(cw),round(ch)
        tw,th=w,h
    elif layer.fit=='contain':
        if sw/sh>w/h:tw,th=w,round(sh/sw*w)
        else:tw,th=round(sw/sh*h),h
    else:tw,th=w,h
    if (tw,th)!=(sw,sh):filters.append(f'scale={tw}:{th}:flags=lanczos')
    if (tw,th)!=(w,h):filters.append(f'pad={w}:{h}:{(w-tw)//2}:{(h-th)//2}:color=black@0')
    return ','.join(filters)

def audio_graph(project,args,filters,next_index,check,media):
    from .render import probe
    labels=[]
    sample=lambda f:round(Fraction(f*project.fps.den*48000,project.fps.num))
    for a in project.audio:
        asset=next(v for v in project.assets if v.id==a.asset)
        info=media.get(a.asset) or probe(asset.path,check)
        if not any(s['codec_type']=='audio' for s in info['streams']):raise ValueError('source has no audio')
        start=sample(a.source_start);count=sample(a.end-a.start)
        if float(info['format'].get('duration',0))*48000+1<start+count:raise ValueError('source audio too short')
        i=next_index;next_index+=1
        args+=['-threads',str(POLICY['decoder_threads']),'-thread_queue_size','4','-i',asset.path]
        f=f'[{i}:a]aresample=48000,atrim=start_sample={start}:end_sample={start+count},asetpts=PTS-STARTPTS,volume={a.volume}'
        if a.fade_in:f+=f',afade=t=in:st=0:d={project.fps.seconds(a.fade_in)}'
        if a.fade_out:f+=f',afade=t=out:st={project.fps.seconds(max(0,a.end-a.start-a.fade_out))}:d={project.fps.seconds(a.fade_out)}'
        f+=f',adelay={sample(a.start)}S:all=1[a{i}]';filters.append(f);labels.append(f'[a{i}]')
    if labels:
        filters.append(''.join(labels)+f'amix=inputs={len(labels)}:normalize=0,apad,atrim=end_sample={sample(project.frames)},asettb=1/48000,asetpts=N/SR/TB[mix]')
    return bool(labels)

def validate(project,path,check):
    from .render import probe
    info=probe(path,check);video=next(s for s in info['streams'] if s['codec_type']=='video')
    if int(video.get('nb_read_frames',0))!=project.frames:raise ValueError('output frame count mismatch')
    if (video['width'],video['height'])!=(project.width,project.height):raise ValueError('output size mismatch')
    if Fraction(video['avg_frame_rate'])!=Fraction(project.fps.num,project.fps.den):raise ValueError('output frame rate mismatch')
    if abs(float(video['duration'])-project.fps.seconds(project.frames))>project.fps.seconds(1)/2:raise ValueError('output duration drift')
    audio=[s for s in info['streams'] if s['codec_type']=='audio']
    if bool(audio)!=bool(project.audio):raise ValueError('output audio mismatch')
    if audio and abs(float(audio[0]['duration'])-project.fps.seconds(project.frames))>max(.025,project.fps.seconds(1)):raise ValueError('output audio duration drift')
    return info

def stream_render(project,folder,plan,check,progress,cache_root=None):
    from .render import Rasterizer,binary,command,sha
    from .brand import preflight
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    cache=Path(cache_root or folder/'states');cache.mkdir(parents=True,exist_ok=True)
    pending=folder/'output.partial.mp4';out=folder/'output.mp4'
    rate=f'{project.fps.num}/{project.fps.den}';phases={};started=time.perf_counter()
    for asset in project.assets:
        check()
        if sha(asset.path)!=asset.sha256:raise ValueError('asset identity changed: '+asset.id)
    args=[binary('ffmpeg'),'-v','error','-nostdin','-y','-filter_threads',str(POLICY['filter_threads']),
          '-filter_complex_threads',str(POLICY['filter_threads']),'-filter_buffered_frames',str(POLICY['filter_buffered_frames'])]
    filters=[];hits=0;states=0;next_index=0
    route=plan['route']
    if route in {'copy-file','copy-video'}:
        source=next(a for a in project.assets if a.id==project.layers[0].asset).path
        args+=['-i',source];video='0:v:0';next_index=1
    else:
        raster=Rasterizer(project,folder,check);raster.prepare(decode=False)
        bg=folder/'background.png'
        Image.new('RGBA',(project.width,project.height),ImageColor.getcolor(project.background,'RGBA')).save(bg)
        args+=['-threads',str(POLICY['decoder_threads']),'-framerate',rate,'-i',bg];next_index=1
        filters.append(f'[0:v]loop=loop=-1:size=1:start=0,setpts=N,trim=end_frame={project.frames},format=rgba[base]')
        previous='base'
        for number,layer in enumerate(sorted(project.layers,key=lambda l:l.track)):
            check();i=next_index
            if layer.kind=='video':
                asset=raster.assets[layer.asset];stream=next(s for s in plan['actual_media'][asset.id]['streams'] if s['codec_type']=='video')
                args+=['-threads',str(POLICY['decoder_threads']),'-thread_queue_size','4','-i',asset.path]
                filters.append(f'[{i}:v]fps={rate},trim=start_frame={layer.source_start}:end_frame={layer.source_start+layer.end-layer.start},'
                               f'setpts=PTS-STARTPTS+{layer.start}*{project.fps.den}/{project.fps.num}/TB,{geometry(layer,stream)}[layer{number}]')
                x,y=round(layer.x),round(layer.y)
            else:
                state,hit=static_state(raster,layer,cache,check);hits+=hit
                if state is None:continue
                states+=1;x,y=state['bbox'][:2]
                args+=['-threads',str(POLICY['decoder_threads']),'-framerate',rate,'-i',state['path']]
                filters.append(f'[{i}:v]loop=loop=-1:size=1:start=0,setpts=N,trim=end_frame={project.frames},format=rgba[layer{number}]')
            next_index+=1
            filters.append(f'[{previous}][layer{number}]overlay=x={x}:y={y}:format=rgb:alpha=straight:repeatlast=0:eof_action=pass:'
                           f"enable='gte(n,{layer.start})*lt(n,{layer.end})'[v{number}]")
            previous=f'v{number}'
        filters.append(f'[{previous}]trim=end_frame={project.frames},setpts=PTS-STARTPTS,format=rgba[video]')
        video='[video]'
    has_audio=audio_graph(project,args,filters,next_index,check,plan['actual_media'])
    phases['input_and_static_prepare']=time.perf_counter()-started
    try:
        started=time.perf_counter()
        if route=='copy-file':shutil.copyfile(source,pending)
        else:
            if filters:
                graph=folder/'filtergraph.txt';graph.write_text(';'.join(filters),encoding='utf8')
                args+=['-filter_complex',';'.join(filters)]
            args+=['-map',video]
            args+=['-map','[mix]','-c:a','aac','-ar','48000'] if has_audio else ['-an']
            args+=['-c:v','copy'] if route=='copy-video' else ['-c:v','libopenh264','-b:v',str(max(1000000,project.width*project.height*8)),'-pix_fmt','yuv420p']
            args+=['-movflags','+faststart','-t',str(project.fps.seconds(project.frames)),pending]
            (folder/'encode-command.json').write_text(json.dumps([str(a) for a in args],indent=2),encoding='utf8')
            command(args,check,timeout=1800)
        phases['decode_composite_encode']=time.perf_counter()-started
        progress(stage='validating',route=route)
        started=time.perf_counter();info=validate(project,pending,check)
        phases['full_decode_validation']=time.perf_counter()-started
        check();os.replace(pending,out)
        return {'result_version':2,'path':str(out),'sha256':sha(out),'frames':project.frames,'probe':info,
                'render_plan':plan,'brand':preflight(project),'phases_seconds':phases,
                'video_encodes':0 if route in {'copy-file','copy-video'} else 1,
                'static_states':states,'static_cache_hits':hits,'full_film_png_sequences':False,
                'frame_evidence':'decode final encoded movie on demand; never substitute pre-encode reference'}
    finally:
        if pending.exists():pending.unlink()

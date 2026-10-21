"""Deterministic, versioned route selection. Unknown semantics keep PNG compatibility."""
import os,re
from functools import lru_cache
from fractions import Fraction
from PIL import ImageColor
from .store import fingerprint
from .resources import POLICY

VERSION=1

def shape(project):
    return {'width':project.width,'height':project.height,'frames':project.frames,
            'fps':project.fps.model_dump(),'output':project.output,'background':project.background,
            'layers':[l.model_dump(mode='json') for l in project.layers],
            'audio':[a.model_dump(mode='json') for a in project.audio],
            'transitions':[t.model_dump(mode='json') for t in project.transitions]}

@lru_cache(maxsize=4)
def capabilities(path,digest):
    from .render import command
    filters=command([path,'-v','error','-filters'])
    help_text=command([path,'-hide_banner','-h','full'])
    names=set()
    for line in filters.splitlines():
        parts=line.split()
        if len(parts)>2 and re.fullmatch(r'[TSC\.]{2,3}',parts[0]):names.add(parts[1])
    required={'fps','trim','setpts','scale','crop','pad','overlay','format','loop','aresample','atrim','amix','apad','adelay','afade','asetpts','asettb','volume'}
    return {'filters':sorted(required & names),'missing':sorted(required-names),
            'bounded_filter_buffers':'-filter_buffered_frames' in help_text,
            'binary_sha256':digest}

def copy_clock(path,frames,rate,check):
    """Prove every presentation timestamp; stream metadata averages do not prove CFR."""
    from .render import binary,command
    if frames>108000:return False
    text=command([binary('ffprobe'),'-v','error','-select_streams','v:0',
                  '-show_entries','packet=pts_time','-of','csv=p=0',path],check)
    try:pts=sorted(Fraction(line.strip().split(',')[0]) for line in text.splitlines() if line.strip())
    except (ValueError,ZeroDivisionError):return False
    return len(pts)==frames and all(abs(float(t-Fraction(i,1)/rate))<.000002 for i,t in enumerate(pts))

def choose(project,resolve=False,check=lambda:None,frozen=None):
    from .render import binary,sha,probe
    mode=(frozen or {}).get('mode',os.environ.get('D_RENDER_MODE','auto'))
    if mode not in {'auto','legacy'}:raise ValueError('D_RENDER_MODE must be auto or legacy')
    signature=fingerprint(shape(project))
    if frozen and (frozen['version']!=VERSION or frozen['shape_hash']!=signature):
        raise ValueError('Frozen render plan no longer matches composition')
    reasons=[]
    if mode=='legacy':reasons.append('operator selected compatibility renderer')
    if project.output!='mp4':reasons.append('alpha MOV remains on compatibility renderer')
    if ImageColor.getcolor(project.background,'RGBA')[3]!=255:reasons.append('transparent background not admitted to MP4 fast path')
    if project.transitions:reasons.append('explicit transitions require compatibility rendering')
    videos=[l for l in project.layers if l.kind=='video']
    if len(videos)>POLICY['max_video_inputs']:reasons.append('video decoder input budget exceeded')
    if len(project.audio)>POLICY['max_audio_inputs']:reasons.append('audio decoder input budget exceeded')
    if len(project.layers)-len(videos)>POLICY['max_static_states']:reasons.append('static state input budget exceeded')
    for l in project.layers:
        if l.kind=='component':reasons.append(l.id+': procedural component')
        if l.keyframes or l.fade_in or l.fade_out:reasons.append(l.id+': temporal layer effects')
        if l.brand_lock:reasons.append(l.id+': protected brand placement retains verified renderer')
        if l.words or l.transcript:reasons.append(l.id+': timed typography')
        if l.kind=='video' and (l.rotation or l.scale!=1 or l.opacity!=1):
            reasons.append(l.id+': transformed or translucent video')
    route='legacy-png' if reasons else 'ffmpeg'
    media={};caps={}
    if resolve and not reasons:
        path=binary('ffmpeg');caps=capabilities(path,sha(path))
        if caps['missing'] or not caps['bounded_filter_buffers']:
            reasons.append('deployed FFmpeg lacks required filters or bounded filter queues')
        for l in videos:
            check()
            a=next(a for a in project.assets if a.id==l.asset)
            if a.id not in media:media[a.id]=probe(a.path,check)
            info=media[a.id];s=next((s for s in info['streams'] if s['codec_type']=='video'),None)
            if not s:raise ValueError(l.id+': source has no video')
            rotation=any(float(x.get('rotation',0))%360 for x in s.get('side_data_list',[]))
            if rotation or float(s.get('tags',{}).get('rotate',0))%360:reasons.append(l.id+': rotation metadata requires compatibility')
            if s.get('sample_aspect_ratio') not in (None,'1:1','0:1'):reasons.append(l.id+': non-square source pixels')
            if s.get('pix_fmt') not in {'yuv420p','yuvj420p','nv12','rgb24','rgba'}:reasons.append(l.id+': unverified source pixel format')
            if s.get('color_transfer') in {'smpte2084','arib-std-b67'} or s.get('color_primaries')=='bt2020':reasons.append(l.id+': HDR/wide-gamut requires compatibility')
            sw,sh=(l.crop[2]-l.crop[0],l.crop[3]-l.crop[1]) if l.crop else (s['width'],s['height'])
            ratio=max(l.width/sw,l.height/sh) if l.fit=='cover' else min(l.width/sw,l.height/sh)
            # Admitted geometry is compared to the original Pillow reference,
            # including both encoded-to-encoded difference and source fidelity.
            if ratio<.5 or (max(l.width/sw,l.height/sh)>2 and l.fit=='stretch') or ratio>2:
                reasons.append(l.id+': video scale outside validated range retains Pillow sampling')
            if l.fit=='cover':
                ratio=max(l.width/sw,l.height/sh);cw,ch=l.width/ratio,l.height/ratio
                if any(abs(v-round(v))>1e-6 for v in (cw,ch,(sw-cw)/2,(sh-ch)/2)):
                    reasons.append(l.id+': fractional cover crop retains Pillow sampling')
            try:
                avg=Fraction(s['avg_frame_rate']);rate=Fraction(s['r_frame_rate'])
                duration=Fraction(s.get('duration',info['format'].get('duration','0')))
                count=int(s.get('nb_read_frames',0))
                if avg!=rate or abs(float(duration*avg)-count)>1.01:reasons.append(l.id+': VFR or uncertain source clock')
            except (KeyError,ZeroDivisionError,ValueError):reasons.append(l.id+': unverified source clock')
            else:
                if float(duration)+.001<project.fps.seconds(l.source_start+l.end-l.start):raise ValueError(l.id+': source video too short')
        if reasons:route='legacy-png'
        elif len(project.layers)==1 and len(videos)==1:
            l=videos[0];a=next(a for a in project.assets if a.id==l.asset)
            s=next(s for s in media[a.id]['streams'] if s['codec_type']=='video')
            if (l.start==l.source_start==0 and l.end==project.frames and not l.crop and l.x==l.y==0
                and (l.width,l.height)==(project.width,project.height)==(s['width'],s['height'])
                and Fraction(s['avg_frame_rate'])==Fraction(project.fps.num,project.fps.den)
                and int(s.get('nb_read_frames',0))==project.frames and s.get('codec_name')=='h264'
                and s.get('pix_fmt')=='yuv420p' and float(s.get('start_time',0))==0
                and copy_clock(a.path,project.frames,Fraction(project.fps.num,project.fps.den),check)):
                route='copy-file' if not project.audio and len(media[a.id]['streams'])==1 and a.path.lower().endswith('.mp4') else 'copy-video'
    plan={'version':VERSION,'mode':mode,'shape_hash':signature,'route':route,'fallback_reasons':sorted(set(reasons)),
          'allowed_local_fallback':'legacy-png','resource_policy':POLICY,
          'encoding':{'video':'libopenh264','bitrate':max(1000000,project.width*project.height*8),'pixel_format':'yuv420p','audio':'aac','sample_rate':48000},
          'actual_media':media,'capabilities':caps,'resolved':resolve}
    plan['plan_hash']=fingerprint(plan)
    return plan

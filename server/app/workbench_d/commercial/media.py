"""Local media operations with explicit alpha and sample clocks."""
import math,json
from pathlib import Path
from PIL import Image,ImageOps,ImageFilter
from .render import command,binary,sha,probe
from .resources import operation

OPERATIONS=['image-transform','image-composite','chroma-key','video-transform','video-matte','extract-frame','convert','audio-edit']

def result(path,kind,inputs,**metadata):
    return dict(path=str(path.resolve()),kind=kind,sha256=sha(path),source_hashes=[a['sha256'] for a in inputs],**metadata)

def key_image(image,color,tolerance,softness):
    # Deterministic color key, not semantic segmentation. Preserve existing alpha.
    from PIL import ImageColor
    key=ImageColor.getrgb(color);pixels=[]
    for r,g,b,a in image.convert('RGBA').getdata():
        distance=math.sqrt(sum((v-k)**2 for v,k in zip((r,g,b),key)))
        alpha=min(1,max(0,(distance-tolerance)/max(1,softness)))
        pixels.append((r,g,b,round(a*alpha)))
    out=image.convert('RGBA');out.putdata(pixels);return out

@operation('media-operation')
def process(task,inputs,folder,check):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    op=task['operation'];o=task['options']
    allowed={'image-transform':{'crop','width','height','rotation','mirror'},'image-composite':{'x','y','opacity'},'chroma-key':{'color','tolerance','softness'},'video-transform':{'crop','width','height','rotation','start','duration'},'video-matte':{'color','similarity','blend'},'extract-frame':{'frame'},'convert':{'format'},'audio-edit':{'start','duration','volume','fade_in','fade_out'}}
    if op not in allowed or set(o)-allowed[op]:raise ValueError('unsupported media operation/options')
    if not inputs:raise ValueError('media input required')
    source=inputs[0]['path'];check()
    if op in ('image-transform','image-composite','chroma-key'):
        with Image.open(source) as im:image=im.convert('RGBA')
        if op=='image-transform':
            if 'crop' in o:
                box=o['crop']
                if len(box)!=4 or not 0<=box[0]<box[2]<=image.width or not 0<=box[1]<box[3]<=image.height:raise ValueError('crop outside source')
                image=image.crop(box)
            if 'width' in o or 'height' in o:
                size=(int(o.get('width',image.width)),int(o.get('height',image.height)))
                if min(size)<1 or max(size)>4096:raise ValueError('image dimensions outside 1..4096')
                image=image.resize(size,Image.Resampling.LANCZOS)
            if o.get('mirror'):image=ImageOps.mirror(image)
            if o.get('rotation'):image=image.rotate(float(o['rotation']),Image.Resampling.BICUBIC,expand=True)
        elif op=='image-composite':
            if len(inputs)!=2:raise ValueError('composite needs background and foreground')
            with Image.open(inputs[1]['path']) as im:overlay=im.convert('RGBA')
            opacity=float(o.get('opacity',1))
            if not 0<=opacity<=1:raise ValueError('invalid opacity')
            overlay.putalpha(overlay.getchannel('A').point(lambda a:round(a*opacity)))
            image.alpha_composite(overlay,(int(o.get('x',0)),int(o.get('y',0))))
        else:image=key_image(image,o.get('color','#00ff00'),float(o.get('tolerance',40)),float(o.get('softness',40)))
        path=folder/'output.png';image.save(path);return result(path,'image',inputs)
    if op=='extract-frame':
        n=o.get('frame',0)
        if type(n)!=int or n<0:raise ValueError('frame must be nonnegative integer')
        path=folder/'frame.png';command([binary('ffmpeg'),'-v','error','-y','-i',source,'-vf',f'select=eq(n\\,{n})','-frames:v','1',path],check)
        if not path.exists():raise ValueError('frame outside source')
        return result(path,'image',inputs,frame=n)
    if op=='audio-edit':
        filters=['aresample=48000']
        start=float(o.get('start',0));duration=o.get('duration')
        if start<0 or duration is not None and float(duration)<=0:raise ValueError('invalid audio cut')
        filters+=['atrim=start_sample='+str(round(start*48000))+((':end_sample='+str(round((start+float(duration))*48000))) if duration else ''),'asetpts=N/SR/TB',f'volume={float(o.get("volume",1))}']
        if o.get('fade_in'):filters.append(f'afade=t=in:st=0:d={float(o["fade_in"])}')
        if o.get('fade_out'):
            if duration is None:raise ValueError('duration required for fade out')
            filters.append(f'afade=t=out:st={max(0,float(duration)-float(o["fade_out"]))}:d={float(o["fade_out"])}')
        path=folder/'audio.wav';command([binary('ffmpeg'),'-v','error','-y','-i',source,'-vn','-af',','.join(filters),'-c:a','pcm_s16le',path],check)
        return result(path,'audio',inputs,sample_rate=48000)
    filters=[];args=[]
    if op=='video-transform':
        if 'start' in o:args+=['-ss',str(float(o['start']))]
        if 'duration' in o:args+=['-t',str(float(o['duration']))]
        if 'crop' in o:
            x,y,w,h=map(int,o['crop'])
            if min(x,y)<0 or min(w,h)<1:raise ValueError('invalid video crop x,y,w,h')
            filters.append(f'crop={w}:{h}:{x}:{y}')
        if 'width' in o or 'height' in o:
            w=int(o.get('width',-2));h=int(o.get('height',-2))
            if any(v!= -2 and not 1<=v<=4096 for v in (w,h)):raise ValueError('invalid dimensions')
            filters.append(f'scale={w}:{h}')
        if 'rotation' in o:filters.append(f'rotate={float(o["rotation"])*math.pi/180}:c=none')
    if op=='video-matte':
        from PIL import ImageColor
        rgb=ImageColor.getrgb(o.get('color','#00ff00'));similarity=float(o.get('similarity',.1));blend=float(o.get('blend',.1))
        if not .01<=similarity<=1 or not 0<=blend<=1:raise ValueError('invalid key settings')
        filters=['format=rgba',f'colorkey=0x{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}:{similarity}:{blend}']
    fmt=o.get('format','mov-alpha')
    if fmt not in ('mov-alpha','mp4','wav'):raise ValueError('supported formats: mov-alpha/mp4/wav')
    path=folder/('output.wav' if fmt=='wav' else 'output.mp4' if fmt=='mp4' else 'output.mov')
    codec=['-vn','-c:a','pcm_s16le'] if fmt=='wav' else ['-c:v','libopenh264','-pix_fmt','yuv420p','-c:a','aac'] if fmt=='mp4' else ['-c:v','png','-pix_fmt','rgba','-c:a','pcm_s16le']
    command([binary('ffmpeg'),'-v','error','-y','-i',source,*args,*(['-vf',','.join(filters)] if filters else []),*codec,path],check)
    return result(path,'audio' if fmt=='wav' else 'video',inputs,probe=probe(path,check))

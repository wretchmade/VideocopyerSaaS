"""Independent frame rasterizer and explicit FFmpeg adapter, authored from D specs."""
from __future__ import annotations
import hashlib, json, os, shutil, subprocess, time
from pathlib import Path
from fractions import Fraction
from bisect import bisect_left
from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


def binary(name):
    value = os.environ.get('D_' + name.upper()) or shutil.which(name)
    if not value: raise ValueError(f'{name} is not configured; set D_{name.upper()}')
    return str(Path(value).resolve())


def command(args, check=lambda: None, timeout=300):
    from .resources import slot,current
    # Version/help discovery neither decodes nor renders and must not wait behind a movie.
    if any(str(a) in {'-version','-filters','-h','-encoders'} for a in args):
        return _command(args,check,timeout)
    with slot('media-command',check) as lease:
        def guarded():check();lease.check()
        return _command(args,guarded,timeout)


def _command(args, check=lambda: None, timeout=300):
    import tempfile
    # Drain output to a file, avoiding deadlock on a full pipe during encoding.
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen([str(a) for a in args], stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),start_new_session=os.name!='nt')
        from .processes import ProcessTree
        tree=ProcessTree(proc)
        started = time.monotonic()
        try:
            while proc.poll() is None:
                check()
                if os.fstat(log.fileno()).st_size>16*1024*1024:
                    raise ValueError('Media command output exceeds bounded log budget')
                if time.monotonic()-started > timeout: raise TimeoutError('media operation timed out')
                time.sleep(.05)
            check()
            if log.tell()>16*1024*1024:raise ValueError('Media command output exceeds bounded log budget')
            log.seek(0); output = log.read().decode('utf8', errors='replace')
            if proc.returncode: raise ValueError(output[-4000:])
            return output
        finally:
            tree.close()


def identity(include_browser=False):
    from PIL import __version__ as pillow_version
    import fontTools
    implementation=hashlib.sha256(b''.join(p.read_bytes() for p in sorted(Path(__file__).parent.iterdir()) if p.suffix in ('.py','.mjs'))).hexdigest()
    result = {'rasterizer':'d-frames-1', 'Pillow':pillow_version,'fontTools':fontTools.__version__,'implementation':implementation}
    from .resources import POLICY
    from .render_plan import VERSION
    result['composition']={'plan_version':VERSION,'mode':os.environ.get('D_RENDER_MODE','auto'),'resources':POLICY}
    result['configuration']={name:sha(os.environ[name]) for name in ('D_PROVIDERS','D_MODEL_ADAPTERS','D_STORAGE') if os.environ.get(name)}
    for name in ('ffmpeg','ffprobe'):
        p = binary(name)
        version=command([p,'-version'])
        if '--enable-gpl' in version or '--enable-nonfree' in version:
            raise ValueError('D core requires an audited LGPL FFmpeg build without --enable-gpl / --enable-nonfree')
        result[name] = dict(path=p, sha256=sha(p), version=version.splitlines()[0],configuration=next((l for l in version.splitlines() if l.startswith('configuration:')),''))
        # Shared FFmpeg builds are defined by their DLLs as well as launcher EXEs.
        result[name]['libraries']={dll.name:sha(dll) for dll in sorted(Path(p).parent.glob('*.dll'))}
    if include_browser:
        node=os.environ.get('D_NODE') or shutil.which('node')
        module=os.environ.get('D_PLAYWRIGHT_MODULE')
        if not node or not module or not Path(module).is_dir():raise ValueError('Set D_NODE and D_PLAYWRIGHT_MODULE for a pinned browser adapter')
        package=json.loads((Path(module)/'package.json').read_text())
        script="const p=require(process.argv[1]);console.log(p.chromium.executablePath())"
        browser=os.environ.get('D_BROWSER') or command([node,'-e',script,module]).strip()
        result['capture']=dict(node=dict(path=str(Path(node).resolve()),sha256=sha(node)),
            playwright=dict(version=package['version'],package_sha256=sha(Path(module)/'package.json')),
            browser=dict(path=browser,sha256=sha(browser),version=command([node,'-e',"const p=require(process.argv[1]);p.chromium.launch({headless:true,executablePath:process.argv[2]}).then(async b=>{console.log(b.version());await b.close()})",module,browser]).strip()),
            adapter_sha256=sha(Path(__file__).with_name('browser.mjs')))
    return result


def probe(path, check=lambda:None):
    return json.loads(command([binary('ffprobe'),'-v','error','-threads','2','-count_frames','-show_streams','-show_format','-of','json',path],check))


def animated(layer, key, frame):
    points = layer.keyframes.get(key)
    if not points: return getattr(layer,key)
    if frame <= points[0].frame: return points[0].value
    index=bisect_left(points,frame,key=lambda p:p.frame)
    if index==len(points):return points[-1].value
    b=points[index]
    if frame==b.frame:return b.value # A key is an exact sample, not another interpolation.
    a=points[index-1];t=(frame-a.frame)/(b.frame-a.frame)
    if a.easing=='hold':t=0
    elif a.easing=='smooth':t=t*t*(3-2*t)
    return a.value+(b.value-a.value)*t


class Rasterizer:
    def __init__(self, project, folder, check=lambda:None):
        self.p, self.folder, self.check = project, Path(folder), check
        self.assets = {a.id:a for a in project.assets}
        self.images, self.fonts, self.videos, self.caption_cache = {}, {}, {}, {}

    def prepare(self,decode=True):
        from fontTools.ttLib import TTFont
        for a in self.p.assets:
            self.check()
            if not Path(a.path).is_file() or sha(a.path) != a.sha256: raise ValueError(f'asset identity changed: {a.id}')
            if a.kind == 'image':
                with Image.open(a.path) as source: self.images[a.id] = source.convert('RGBA')
            if a.kind == 'font':
                with TTFont(a.path) as font: self.fonts[a.id] = set(font.getBestCmap() or {})
        for layer in self.p.layers:
            if layer.brand_lock:
                for sample in layer.brand_lock.samples:
                    if sample.mask_asset and self.images[sample.mask_asset].size != (self.p.width,self.p.height):
                        raise ValueError('BRAND_ANCHOR: visibility mask must match canvas dimensions')
            if layer.kind == 'text' and (not layer.transcript or layer.transcript in self.assets):
                if layer.transcript:
                    from .schema import Word
                    transcript=json.loads(Path(self.assets[layer.transcript].path).read_text(encoding='utf8'))
                    if any(w['missing'] for w in transcript['words']):raise ValueError('unaligned transcript words require correction before caption timing')
                    rate=Fraction(self.p.fps.num,transcript['sampleRate']*self.p.fps.den)
                    layer.words=[Word(text=w['text']+(' ' if w['text'].isascii() else ''),start=layer.start+round(w['startSample']*rate),end=layer.start+round(w['endSample']*rate)) for w in transcript['words']]
                    if any(w.start<layer.start or w.end>layer.end for w in layer.words):raise ValueError('transcript timing outside text layer')
                    if any(a.end>b.start for a,b in zip(layer.words,layer.words[1:])):raise ValueError('transcript words overlap in frame clock')
                self.caption(layer,layer.start) # preflight glyphs/overflow before encoding
            if layer.kind == 'component':
                from .components import draw
                draw(self,layer,layer.start)
            media_id=layer.asset if layer.kind=='video' else layer.props.get('image') if layer.kind=='component' else None
            if media_id in self.assets and self.assets[media_id].kind=='video' and decode:
                source = self.assets[media_id].path
                target = self.folder / ('decode-'+layer.id); target.mkdir(exist_ok=True,parents=True)
                count = layer.end-layer.start
                rate = f'{self.p.fps.num}/{self.p.fps.den}'
                command([binary('ffmpeg'),'-v','error','-nostdin','-y','-i',source,
                    '-vf',f'fps={rate},trim=start_frame={layer.source_start}:end_frame={layer.source_start+count},setpts=PTS-STARTPTS',
                    '-frames:v',str(count),'-start_number','0',target/'%08d.png'], self.check)
                if len(list(target.glob('*.png'))) != count: raise ValueError(f'{layer.id}: source video too short')
                self.videos[layer.id] = target

    def caption(self, layer, frame):
        from .typography import caption
        if not layer.words and not layer.transcript:
            from .store import fingerprint
            key=fingerprint(layer.model_dump(mode='json'))
            if key not in self.caption_cache:self.caption_cache[key]=caption(self,layer,frame)
            return self.caption_cache[key].copy()
        return caption(self,layer,frame)

    def layer_image(self,layer,frame):
        if layer.brand_lock and layer.brand_lock.mode == 'planar':
            from .brand import planar_image
            return planar_image(self,layer,frame)
        canvas=Image.new('RGBA',(self.p.width,self.p.height))
        if layer.kind == 'rect': img=Image.new('RGBA',(layer.width,layer.height),ImageColor.getcolor(layer.color,'RGBA'))
        elif layer.kind == 'text': img=self.caption(layer,frame)
        elif layer.kind == 'image': img=self.images[layer.asset].copy()
        elif layer.kind == 'component':
            from .components import draw
            img=draw(self,layer,frame)
        else:
            with Image.open(self.videos[layer.id]/f'{frame-layer.start:08d}.png') as source: img=source.convert('RGBA')
        if layer.crop:
            if layer.crop[2] > img.width or layer.crop[3] > img.height: raise ValueError(f'{layer.id}: crop exceeds source')
            img=img.crop(layer.crop)
        size=(layer.width,layer.height)
        if layer.fit=='cover': img=ImageOps.fit(img,size,method=Image.Resampling.LANCZOS)
        elif layer.fit=='contain':
            img=ImageOps.contain(img,size,method=Image.Resampling.LANCZOS)
            box=Image.new('RGBA',size); box.alpha_composite(img,((size[0]-img.width)//2,(size[1]-img.height)//2)); img=box
        else: img=img.resize(size,Image.Resampling.LANCZOS)
        scale=animated(layer,'scale',frame)
        if scale != 1: img=img.resize((max(1,round(img.width*scale)),max(1,round(img.height*scale))),Image.Resampling.LANCZOS)
        rotation=animated(layer,'rotation',frame)
        if rotation: img=img.rotate(-rotation,Image.Resampling.BICUBIC,expand=True)
        opacity=animated(layer,'opacity',frame)
        if layer.fade_in: opacity*=min(1,(frame-layer.start)/layer.fade_in)
        if layer.fade_out: opacity*=min(1,(layer.end-1-frame)/layer.fade_out)
        if opacity!=1: img.putalpha(img.getchannel('A').point(lambda v:round(v*opacity)))
        x=round(animated(layer,'x',frame)+(layer.width-img.width)/2)
        y=round(animated(layer,'y',frame)+(layer.height-img.height)/2)
        canvas.alpha_composite(img,(x,y))
        return canvas

    def frame(self, frame):
        from .transitions import transition
        self.check()
        canvas=Image.new('RGBA',(self.p.width,self.p.height),ImageColor.getcolor(self.p.background,'RGBA'))
        ordered=sorted(self.p.layers,key=lambda l:l.track)
        lookup={l.id:l for l in ordered}; consumed=set()
        for layer in ordered:
            if layer.id in consumed or not layer.start<=frame<layer.end:continue
            active=next((t for t in self.p.transitions if t.start<=frame<t.end and layer.id in (t.source,t.target)),None)
            if active:
                a=self.layer_image(lookup[active.source],frame);b=self.layer_image(lookup[active.target],frame)
                fraction=(frame-active.start)/max(1,active.end-active.start-1)
                canvas.alpha_composite(transition(a,b,fraction,active.kind,active.direction))
                consumed.update((active.source,active.target));continue
            if any((t.target==layer.id and frame<t.start) or (t.source==layer.id and frame>=t.end) for t in self.p.transitions):continue
            canvas.alpha_composite(self.layer_image(layer,frame))
        return canvas


def legacy_render(project,folder,check=lambda:None,progress=lambda **kw:None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    raster=Rasterizer(project,folder,check);raster.prepare()
    frames=folder/'frames';frames.mkdir(exist_ok=True)
    # Complete PNGs are atomic checkpoints. Recheck hashes before reuse after a restart.
    manifest_path=folder/'frames.json'
    manifest=json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for n in range(project.frames):
        check(); target=frames/f'{n:08d}.png';key=str(n)
        if not target.is_file() or manifest.get(key)!=sha(target):
            tmp=target.with_suffix('.partial');raster.frame(n).save(tmp,format='PNG');os.replace(tmp,target)
            manifest[key]=sha(target)
        if n % 10 == 0 or n==project.frames-1:
            tmp=manifest_path.with_suffix('.tmp');tmp.write_text(json.dumps(manifest));os.replace(tmp,manifest_path)
            progress(frame=n+1,total=project.frames)
    out=folder/('output.mov' if project.output=='mov-alpha' else 'output.mp4')
    pending=folder/('output.partial'+out.suffix)
    rate=f'{project.fps.num}/{project.fps.den}'
    args=[binary('ffmpeg'),'-v','error','-nostdin','-y','-framerate',rate,'-i',frames/'%08d.png']
    filters=[]; labels=[]
    for i,a in enumerate(project.audio,1):
        asset=next(v for v in project.assets if v.id==a.asset)
        args+=['-i',asset.path]
        sr=48000
        sample=lambda f:round(Fraction(f*project.fps.den*sr,project.fps.num))
        start=sample(a.source_start); count=sample(a.end-a.start)
        source=probe(asset.path,check)
        if not any(s['codec_type']=='audio' for s in source['streams']): raise ValueError('source has no audio')
        # Do not silently pad a missing/short audio source.
        duration=float(source['format'].get('duration',0))
        if duration*sr+1 < start+count: raise ValueError('source audio too short')
        f=f'[{i}:a]aresample={sr},atrim=start_sample={start}:end_sample={start+count},asetpts=PTS-STARTPTS,volume={a.volume}'
        if a.fade_in: f+=f',afade=t=in:st=0:d={project.fps.seconds(a.fade_in)}'
        if a.fade_out: f+=f',afade=t=out:st={project.fps.seconds(max(0,a.end-a.start-a.fade_out))}:d={project.fps.seconds(a.fade_out)}'
        f+=f',adelay={sample(a.start)}S:all=1[a{i}]'; filters.append(f);labels.append(f'[a{i}]')
    if filters:
        filters.append(''.join(labels)+f'amix=inputs={len(labels)}:normalize=0,apad,atrim=end_sample={round(Fraction(project.frames*project.fps.den*48000,project.fps.num))},asettb=1/48000,asetpts=N/SR/TB[mix]')
        args+=['-filter_complex',';'.join(filters),'-map','0:v','-map','[mix]','-c:a','pcm_s16le' if project.output=='mov-alpha' else 'aac','-ar','48000']
    else: args+=['-an']
    if project.output=='mov-alpha': args+=['-c:v','png','-pix_fmt','rgba']
    else: args+=['-c:v','libopenh264','-b:v',str(max(1000000,project.width*project.height*8)),'-pix_fmt','yuv420p','-movflags','+faststart']
    # The finite PNG sequence owns video length. -frames:v would end the whole
    # muxer as soon as video is encoded, before queued audio packets are drained.
    args+=['-t',str(project.fps.seconds(project.frames)),pending]
    (folder/'encode-command.json').write_text(json.dumps([str(a) for a in args],indent=2))
    command(args,check,timeout=1800)
    info=probe(pending,check);video=next(s for s in info['streams'] if s['codec_type']=='video')
    if int(video.get('nb_read_frames',0))!=project.frames: raise ValueError('output frame count mismatch')
    if (video['width'],video['height'])!=(project.width,project.height): raise ValueError('output size mismatch')
    if abs(float(video['duration'])-project.fps.seconds(project.frames)) > project.fps.seconds(1)/2: raise ValueError('output duration drift')
    audio=[s for s in info['streams'] if s['codec_type']=='audio']
    if bool(audio)!=bool(project.audio): raise ValueError('output audio mismatch')
    if audio and abs(float(audio[0]['duration'])-project.fps.seconds(project.frames)) > max(.025,project.fps.seconds(1)): raise ValueError('output audio duration drift')
    check();os.replace(pending,out)
    from .brand import preflight
    evidence=dict(path=str(out),sha256=sha(out),frames=project.frames,probe=info,frame_hashes=manifest,brand=preflight(project))
    (folder/'output-evidence.json').write_text(json.dumps(evidence,indent=2))
    return evidence


def render(project,folder,check=lambda:None,progress=lambda **kw:None,plan=None,cache_root=None):
    from .resources import slot
    from .render_plan import choose
    from .render_ffmpeg import stream_render
    with slot('composition',check,progress) as lease:
        def guarded():check();lease.check()
        started=time.perf_counter()
        selected=choose(project,resolve=True,check=guarded,frozen=plan)
        preflight_seconds=time.perf_counter()-started
        progress(stage='compositing',route=selected['route'])
        if selected['route']=='legacy-png':
            result=legacy_render(project,folder,guarded,progress)
            result.update(result_version=1,render_plan=selected)
        else:result=stream_render(project,folder,selected,guarded,progress,cache_root)
        result.setdefault('phases_seconds',{})['route_preflight_full_source_decode']=preflight_seconds
        result['resources']=lease.summary()
        (Path(folder)/'output-evidence.json').write_text(json.dumps(result,indent=2),encoding='utf8')
        return result

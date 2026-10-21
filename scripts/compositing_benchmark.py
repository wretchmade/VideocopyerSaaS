"""Offline fixtures and per-process render benchmark. No Web/Agent/provider imports."""
import argparse,hashlib,json,os,subprocess,sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def env():
    config=json.loads((ROOT/'config.local.json').read_text(encoding='utf-8-sig'))
    os.environ.update(D_FFMPEG=config['ffmpeg'],D_FFPROBE=config['ffprobe'],
                      D_JIANYING_PYTHON=str(ROOT/'.venv-jianying/Scripts/python.exe'),
                      D_HEAVY_ROOT=str(ROOT/'.local/compositing-benchmark/resources'))
    return config

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def fixtures():
    from PIL import Image,ImageDraw
    cfg=env();folder=ROOT/'.local/compositing-benchmark/fixtures';folder.mkdir(parents=True,exist_ok=True)
    ff=os.environ['D_FFMPEG']
    for width,height in [(1280,720),(1920,1080)]:
        video=folder/f'source-{height}.mp4'
        if not video.exists():
            subprocess.run([ff,'-v','error','-nostdin','-y','-f','lavfi','-i',f'testsrc2=size={width}x{height}:rate=30:duration=60',
                            '-an','-c:v','libopenh264','-b:v',str(max(1000000,width*height*8)),'-pix_fmt','yuv420p','-threads','2',str(video)],check=True)
    audio=folder/'voice.wav'
    if not audio.exists():subprocess.run([ff,'-v','error','-y','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=60','-c:a','pcm_s16le',str(audio)],check=True)
    logo=folder/'logo.png';image=Image.new('RGBA',(160,96));draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((2,2,157,93),12,fill='#125ac899',outline='#ffffffff',width=2)
    draw.line((12,75,145,18),fill='#00ffaa',width=1);draw.ellipse((60,25,100,65),outline='white',width=2);image.save(logo)
    def asset(id,kind,path):return {'id':id,'kind':kind,'path':str(path),'sha256':sha(path),'license':'local fixture / system font local use','source':'offline benchmark'}
    for height,seconds in [(720,12),(1080,60)]:
        width=height*16//9;frames=seconds*30
        document={'width':width,'height':height,'frames':frames,'fps':{'num':30,'den':1},'background':'#111622',
                  'assets':[asset('video','video',folder/f'source-{height}.mp4'),asset('logo','image',logo),asset('font','font',Path(cfg['font'])),asset('voice','audio',audio)],
                  'layers':[{'id':'shot_a','kind':'video','asset':'video','width':width,'height':height,'start':0,'end':frames//2},
                            {'id':'shot_b','kind':'video','asset':'video','width':width,'height':height,'start':frames//2,'end':frames,'source_start':30},
                            {'id':'logo','kind':'image','asset':'logo','x':width-185,'y':25,'width':160,'height':96,'end':frames,'track':2},
                            {'id':'caption','kind':'text','text':'相同画质 · 普通字幕 / Logo 与配音','fonts':['font'],'font_size':36,'stroke':1,'shadow':[2,2],
                             'width':width-80,'height':100,'x':40,'y':height-125,'end':frames,'track':3,'text_align':'center'}],
                  'audio':[{'asset':'voice','start':0,'end':frames,'volume':.15,'fade_in':15,'fade_out':15}]}
        (folder/f'ordinary-{height}.json').write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'fixtures':str(folder),'provider_requests':0}))

def run(args):
    import psutil
    env();sys.path.insert(0,str(Path(args.source).resolve()))
    from app.workbench_d.commercial import render
    from app.workbench_d.commercial.schema import upgrade
    doc=upgrade(json.loads(Path(args.document).read_text(encoding='utf8')))
    out=Path(args.output).resolve()
    if out.exists():raise ValueError('Benchmark output must be a new directory')
    out.mkdir(parents=True)
    phase={};original=render.command
    def command(argv,*a,**kw):
        strings=[str(x) for x in argv]
        kind=('complete_decode_validation' if any('output.partial' in s for s in strings) else 'source_probe') if '-count_frames' in strings else 'encoding' if any('output.partial' in s for s in strings) else 'input_decode_prepare'
        started=time.perf_counter()
        try:return original(argv,*a,**kw)
        finally:phase[kind]=phase.get(kind,0)+time.perf_counter()-started
    render.command=command
    old_frame=render.Rasterizer.frame
    def frame(self,n):
        started=time.perf_counter()
        try:return old_frame(self,n)
        finally:phase['pillow_composition']=phase.get('pillow_composition',0)+time.perf_counter()-started
    render.Rasterizer.frame=frame
    stop=threading.Event();samples={'tree_peak_rss_bytes':0,'temp_peak_bytes':0,'cpu':{}}
    parent=psutil.Process()
    def monitor():
        while not stop.is_set():
            total=0
            for p in [parent,*parent.children(recursive=True)]:
                try:
                    key=(p.pid,p.create_time());cpu=p.cpu_times()
                    samples['cpu'][key]=max(samples['cpu'].get(key,0),cpu.user+cpu.system)
                    total+=p.memory_info().rss
                except (psutil.NoSuchProcess,psutil.AccessDenied):pass
            samples['tree_peak_rss_bytes']=max(samples['tree_peak_rss_bytes'],total)
            disk=0
            for p in out.rglob('*'):
                try:
                    if p.is_file() and not p.name.startswith('output.'):disk+=p.stat().st_size
                except FileNotFoundError:pass
            samples['temp_peak_bytes']=max(samples['temp_peak_bytes'],disk)
            stop.wait(.05)
    start_cpu=parent.cpu_times();thread=threading.Thread(target=monitor,daemon=True);thread.start()
    started=time.perf_counter()
    try:result=render.render(doc,out)
    finally:stop.set();thread.join()
    elapsed=time.perf_counter()-started
    metrics={'source':str(Path(args.source).resolve()),'document':str(Path(args.document).resolve()),'document_hash':sha(args.document),
             'implementation_sha256':hashlib.sha256(b''.join(p.read_bytes() for p in sorted(Path(render.__file__).parent.iterdir()) if p.suffix in ('.py','.mjs'))).hexdigest(),
             'wall_seconds':elapsed,'phases_seconds':phase,'tree_peak_rss_bytes':samples['tree_peak_rss_bytes'],
             'temp_peak_bytes':samples['temp_peak_bytes'],'sampled_tree_cpu_seconds':sum(samples['cpu'].values())-start_cpu.user-start_cpu.system,
             'sampling_seconds':.05,'cpu_note':'Sum of sampled per-process lifetime CPU; very short child processes can be undercounted. RSS sums processes including shared pages.',
             'png_count':len(list(out.rglob('*.png'))),'output_bytes':Path(result['path']).stat().st_size,
             'result':result,'provider_requests':0,'local_machine_not_cloud_capacity':True}
    (out/'benchmark.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in metrics.items() if k!='result'},ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--fixtures',action='store_true');parser.add_argument('--source',default=str(ROOT/'server'));parser.add_argument('--document');parser.add_argument('--output')
    args=parser.parse_args()
    fixtures() if args.fixtures else run(args)

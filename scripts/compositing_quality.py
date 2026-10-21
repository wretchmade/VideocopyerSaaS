"""Compare final movie pixels and key regions. All outputs stay in benchmark/evidence."""
import argparse,json,math,os,sys
from pathlib import Path
from PIL import Image,ImageChops,ImageStat,ImageDraw
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'server'))
from compositing_benchmark import env
env()
from app.workbench_d.commercial.render import command,binary
from app.workbench_d.commercial.render_artifacts import final_frame

def metrics(a,b):
    difference=ImageChops.difference(a.convert('RGB'),b.convert('RGB'))
    stats=ImageStat.Stat(difference);mse=sum(v*v for v in stats.rms)/3
    return {'identical':difference.getbbox() is None,'mae':sum(stats.mean)/3,
            'psnr_db':10*math.log10(255**2/mse) if mse else None}

def compare(old,new,document,name):
    from app.workbench_d.commercial.schema import upgrade
    document=upgrade(document).model_dump(mode='json')
    folder=ROOT/'docs/evidence/compositing'/name;folder.mkdir(parents=True,exist_ok=True)
    frames={0,document['frames']-1,document['frames']//4,document['frames']//2,document['frames']*3//4}
    for l in document['layers']:
        for n in (l['start'],l['end']):
            frames.update(x for x in (n-1,n,n+1) if 0<=x<document['frames'])
    for t in document.get('transitions',[]):
        for n in (t['start'],(t['start']+t['end'])//2,t['end']):
            frames.update(x for x in (n-1,n,n+1) if 0<=x<document['frames'])
    rows=[];thumbs=[]
    for n in sorted(frames):
        x=final_frame(old,n);y=final_frame(new,n)
        with Image.open(x['path']) as a,Image.open(y['path']) as b:
            row={'frame':n,**metrics(a,b),'regions':{}}
            for l in document['layers']:
                if l['kind'] not in ('image','text') or not l['start']<=n<l['end']:continue
                box=(max(0,round(l.get('x',0))),max(0,round(l.get('y',0))),
                     min(a.width,round(l.get('x',0))+l['width']),min(a.height,round(l.get('y',0))+l['height']))
                if box[2]>box[0] and box[3]>box[1]:row['regions'][l['id']]=metrics(a.crop(box),b.crop(box))
            rows.append(row)
            pair=Image.new('RGB',(640,220),'#202020')
            for i,source in enumerate((a,b)):
                thumb=source.convert('RGB');thumb.thumbnail((320,190));pair.paste(thumb,(i*320,25))
            ImageDraw.Draw(pair).text((8,6),f'Frame {n}: original | streaming',fill='white')
            thumbs.append(pair)
    sheet=Image.new('RGB',(640,220*len(thumbs)),'#202020')
    for i,pair in enumerate(thumbs):sheet.paste(pair,(0,220*i))
    sheet.save(folder/'key-frames.jpg',quality=92)
    stats=folder/'ssim.log'
    # Windows drive separators require escaping inside a filter expression.
    escaped=stats.as_posix().replace(':',r'\:')
    text=command([binary('ffmpeg'),'-v','info','-i',old['path'],'-i',new['path'],
                  '-lavfi',f"ssim=stats_file='{escaped}'",'-an','-f','null','-'],timeout=600)
    summary={'same_file_sha256':old['sha256']==new['sha256'],'key_frames':rows,
             'full_movie_ssim':[line for line in text.splitlines() if 'SSIM Y:' in line],
             'old_frames':old['frames'],'new_frames':new['frames'],
             'old_probe':old['probe'],'new_probe':new['probe'],
             'route':new['render_plan']['route'],'reasons':new['render_plan']['fallback_reasons']}
    (folder/'quality.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    print(json.dumps({'name':name,'same_file':summary['same_file_sha256'],'all_key_frames_exact':all(r['identical'] for r in rows),'ssim':summary['full_movie_ssim']}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('old');parser.add_argument('new');parser.add_argument('document');parser.add_argument('name');a=parser.parse_args()
    compare(json.loads(Path(a.old).read_text(encoding='utf8'))['result'],
            json.loads(Path(a.new).read_text(encoding='utf8'))['result'],
            json.loads(Path(a.document).read_text(encoding='utf8')),a.name)

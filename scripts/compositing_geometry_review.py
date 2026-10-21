"""Inspect the geometry comparison's final encoded ROI, including codec variation."""
import json,sys
from pathlib import Path
from PIL import Image,ImageChops,ImageEnhance,ImageDraw
from compositing_benchmark import env,ROOT
env();sys.path.insert(0,str(ROOT/'server'))
from app.workbench_d.commercial.render import binary,command
folder=Path(sys.argv[1]);results=[];strips=[]
for case in sorted((folder/'cases').glob('test_video_geometry*')):
    spec=json.loads((case/'geometry-quality.json').read_text());w,h=spec['size']
    text=command([binary('ffmpeg'),'-v','info','-i',case/'old/output.mp4','-i',case/'new/output.mp4',
                  '-filter_complex',f'[0:v]crop={w}:{h}:0:0[a];[1:v]crop={w}:{h}:0:0[b];[a][b]ssim',
                  '-an','-f','null','-'])
    results.append({**spec,'roi_ssim':[line for line in text.splitlines() if 'SSIM Y:' in line]})
    selected=[]
    for name in ('old','new'):
        rows=[json.loads(p.read_text()) for p in (case/name/'review-frames').glob('*.json')]
        row=next(r for r in rows if r['frame']==1)
        with Image.open(row['path']) as im:selected.append(im.convert('RGB').crop((0,0,w,h)))
    images=[*selected,ImageEnhance.Contrast(ImageChops.difference(*selected)).enhance(8)]
    strip=Image.new('RGB',(960,270),'#202020')
    for i,im in enumerate(images):
        im.thumbnail((320,240));strip.paste(im,(320*i,25))
    ImageDraw.Draw(strip).text((6,7),f"{spec['fit']} {w}x{h} | original | streaming | difference x8",fill='white')
    strips.append(strip)
out=ROOT/'docs/evidence/compositing/geometry';out.mkdir(parents=True,exist_ok=True)
sheet=Image.new('RGB',(960,270*len(strips)))
for i,im in enumerate(strips):sheet.paste(im,(0,270*i))
sheet.save(out/'comparison.png')
(out/'quality.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results))

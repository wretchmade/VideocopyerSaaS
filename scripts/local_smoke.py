"""Real FFmpeg/local-media test; explicitly NOT provider or Jianying UI acceptance."""
import io,json,math,time,wave
from pathlib import Path
import httpx
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1]
c=httpx.Client(base_url='http://127.0.0.1:8765',timeout=180)
c.headers['x-vc-token']=c.get('/api/bootstrap').json()['token']
def post(path,data):
    r=c.post('/api'+path,json=data);r.raise_for_status();return r.json()
p=post('/projects',{'text':'非付费管线验收 · 字幕与多轨','command_id':'local-smoke-project-v1'});pid=p['id']
im=Image.new('RGB',(960,540),'#243348');draw=ImageDraw.Draw(im);draw.rectangle((100,120,860,420),fill='#315f93');draw.ellipse((370,120,590,340),fill='#bc986c')
b=io.BytesIO();im.save(b,format='PNG');r=c.post(f'/api/projects/{pid}/files',files={'file':('local-fixture.png',b.getvalue(),'image/png')});r.raise_for_status();f=r.json()
b=io.BytesIO()
with wave.open(b,'wb') as w:
    w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes(b''.join(int(1600*math.sin(2*math.pi*440*n/24000)).to_bytes(2,'little',signed=True) for n in range(72000)))
r=c.post(f'/api/projects/{pid}/files',files={'file':('test-tone.wav',b.getvalue(),'audio/wav')});r.raise_for_status();a=r.json()
plan={'title':'非付费管线验收 · 字幕与多轨','aspect':'16:9','audio_file_id':a['id'],'shots':[{'id':'shot1','title':'测试画面','description':'本地图形素材，用于渲染验证','duration':3,'file_id':f['id'],'subtitle':'本地制作链路验证'}]}
snapshot=c.get('/api/projects/'+pid).json()
if snapshot['revision']==0:
    r=c.put(f'/api/projects/{pid}/plan',json={'plan':plan,'base_revision':0,'command_id':'local-smoke-plan-v1'});r.raise_for_status()
q=c.get(f'/api/projects/{pid}/quote?revision=1');q.raise_for_status();q=q.json()
t=post(f'/projects/{pid}/produce',{'revision':1,'quote_hash':q['quote_hash'],'command_id':'local-smoke-build-v1'})
current=c.get('/api/projects/'+pid).json()
live=next(x for x in current['tasks'] if x['id']==t['id'])
if live['status'] in ['failed','cancelled']:post(f'/projects/{pid}/tasks/{t["id"]}/resume',{})
for _ in range(120):
    s=c.get('/api/projects/'+pid).json();t=next(x for x in s['tasks'] if x['id']==t['id'])
    if t['status'] in ['succeeded','failed','cancelled']:break
    time.sleep(1)
print('task',t['status'],t.get('error'))
if t['status']!='succeeded':raise SystemExit(1)
d=post(f'/projects/{pid}/deliver',{'task_id':t['id'],'allow_baked':False,'command_id':'local-smoke-export-v1'})
evidence={'project':pid,'task':t['id'],'delivery':d,'verification':'actual local render + native draft structure, NOT model quality or Jianying UI'}
(ROOT/'docs/evidence/local-smoke.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
print('paired delivery',d['id'])

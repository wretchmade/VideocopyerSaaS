"""Read the existing room project without modifying its database or assets."""
import copy,json,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
source=Path('D:/P-project/VCTestplace/senclub-blue-room/d-data/core/state.sqlite')
if Path(str(source)+'-wal').exists():raise RuntimeError('Source has WAL; take a consistent read-only backup first')
with sqlite3.connect(source.as_uri()+'?mode=ro&immutable=1',uri=True) as db:
    db.row_factory=sqlite3.Row
    builds=db.execute("SELECT id,spec,result,revision FROM builds WHERE status='succeeded' ORDER BY rowid DESC").fetchall()
    chosen=builds[0];doc=json.loads(chosen['spec'])
    results={r['id']:json.loads(r['result']) for r in db.execute("SELECT id,result FROM nodes WHERE build=? AND status='succeeded'",(chosen['id'],))}
for t in doc.get('tasks',[]):
    a=results[t['id']]
    doc['assets'].append(dict(id=t['id'],kind=a['kind'],path=a['path'],sha256=a['sha256'],license='existing generated media; original rights retained',source='frozen build '+chosen['id']))
doc['tasks']=[]
folder=ROOT/'.local/compositing-benchmark/fixtures'
folder.mkdir(parents=True,exist_ok=True)
out=folder/'room-original.json';out.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf8')
ordinary=copy.deepcopy(doc)
for transition in ordinary.get('transitions',[]):
    next(l for l in ordinary['layers'] if l['id']==transition['source'])['end']=transition['start']
ordinary['transitions']=[]
(folder/'room-hardcut.json').write_text(json.dumps(ordinary,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({'source':str(source),'build':chosen['id'],'revision':chosen['revision'],'fixture':str(out),
                  'frames':doc['frames'],'layers':[(l['id'],l['kind']) for l in doc['layers']],'provider_requests':0},ensure_ascii=False))

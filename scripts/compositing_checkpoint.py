"""Verified pre-optimization snapshot; read-only source and no provider calls."""
import hashlib,json,shutil,sqlite3,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def main():
    data=ROOT/'.local/data';active=[]
    for p in data.rglob('state.sqlite'):
        with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True) as c:
            active += [r[0] for r in c.execute("SELECT id FROM builds WHERE status IN ('queued','running')")]
    with sqlite3.connect((data/'control.sqlite3').as_uri()+'?mode=ro',uri=True) as c:
        for kind,body in c.execute("SELECT kind,body FROM facts WHERE kind IN ('task','agent_inbox','project')"):
            row=json.loads(body)
            if row.get('status') in ({'queued','running','stopping','reconciling'} if kind=='task' else {'pending','dispatching','dispatched'} if kind=='agent_inbox' else {'running','starting'}):active.append(row['id'])
    if active:raise RuntimeError('Active work must finish or retain its original runtime before changes: '+str(active))
    dest=ROOT/'.local/compositing-backups'/time.strftime('%Y%m%d-%H%M%S');dest.mkdir(parents=True)
    paths=[p for directory in ['server','web','dist','scripts','docs','.local/data'] for p in (ROOT/directory).rglob('*') if p.is_file()]
    paths += [p for p in ROOT.iterdir() if p.is_file()]
    manifest={}
    for p in paths:
        if '__pycache__' in p.parts or p.suffix in {'.pyc','.lock'} or p.name.endswith(('-wal','-shm')):continue
        rel=p.relative_to(ROOT);target=dest/rel;target.parent.mkdir(parents=True,exist_ok=True)
        if p.suffix in {'.sqlite','.sqlite3'}:
            with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True) as a,sqlite3.connect(target) as b:
                a.backup(b);assert b.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        else:shutil.copy2(p,target);assert sha(p)==sha(target)
        manifest[rel.as_posix()]=sha(target)
    (dest/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    result={'backup':str(dest),'files':len(manifest),'active_work':active,
            'commercial_sha256':hashlib.sha256(b''.join(p.read_bytes() for p in sorted((ROOT/'server/app/workbench_d/commercial').iterdir()) if p.suffix in {'.py','.mjs'})).hexdigest(),
            'model':json.loads((ROOT/'config.local.json').read_text(encoding='utf-8-sig'))['planning']['model'],
            'rollback':'Preserve v2 readers for new results; prefer disabling optimized route. Restore original source/database set only while stopped. Never rewrite build identity.'}
    out=ROOT/'docs/evidence/compositing';out.mkdir(parents=True,exist_ok=True)
    (out/'checkpoint.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()

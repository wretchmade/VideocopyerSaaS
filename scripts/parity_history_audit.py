"""Read-only comparison with P0. Never opens an Agent or submits provider work."""
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'.local/parity-backups/20261020-142733'

def connect(path):
    return sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def main():
    manifest=json.loads((BASE/'manifest.json').read_text())
    checked=0;databases=0;rows=0;active=[];unknown=0;deliveries=0
    for relative,expected in manifest.items():
        if not relative.startswith('.local/data/'):continue
        original=BASE/relative;current=ROOT/relative
        if original.suffix in {'.sqlite','.sqlite3'}:
            databases+=1
            with connect(original) as a,connect(current) as b:
                assert b.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
                tables=[r[0] for r in a.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
                for table in tables:
                    assert table.replace('_','').isalnum()
                    old=a.execute(f'SELECT * FROM "{table}"').fetchall()
                    now=set(b.execute(f'SELECT * FROM "{table}"').fetchall())
                    assert all(row in now for row in old),f'Historical rows changed: {relative}:{table}'
                    rows+=len(old)
                if 'builds' in tables:
                    active += [r[0] for r in b.execute("SELECT id FROM builds WHERE status IN ('queued','running')")]
                if 'requests' in tables:
                    unknown+=b.execute("SELECT COUNT(*) FROM requests WHERE state IN ('unknown','submitting')").fetchone()[0]
                if 'facts' in tables:
                    for kind,body in b.execute("SELECT kind,body FROM facts WHERE kind IN ('agent_inbox','task','delivery')"):
                        fact=json.loads(body)
                        if kind=='agent_inbox' and fact['status'] in {'pending','dispatching','dispatched'}:active.append(fact['id'])
                        if kind=='task' and fact['status'] in {'queued','running','reconciling','stopping'}:active.append(fact['id'])
                        if kind=='delivery':
                            assert digest(Path(fact['preview_path']))==fact['preview_sha256']
                            assert digest(Path(fact['zip_path']))==fact['zip_sha256']
                            deliveries+=1
        elif '/agents/' not in relative and current.name not in {'worker.log','providers.json'}:
            assert current.is_file() and digest(current)==expected,relative
            checked+=1
    original=json.loads((BASE/'config.local.json').read_text(encoding='utf-8-sig'))
    current=json.loads((ROOT/'config.local.json').read_text(encoding='utf-8-sig'))
    assert current==original,'Existing configuration changed'
    evidence={'historical_files_verified':checked,'databases_integrity_verified':databases,'historical_rows_unchanged':rows,
              'deliveries_hash_verified':deliveries,'active_work':active,'unknown_remote_receipts_retained':unknown,
              'configuration_unchanged':True,'planning_model':current['planning']['model'],'read_only':True}
    (ROOT/'docs/evidence/parity/history-audit.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(evidence,ensure_ascii=False))

if __name__=='__main__':main()

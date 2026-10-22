"""Read-only live checks of the restored app and immutable historical deliveries."""
import hashlib,json,time
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
config=json.loads((ROOT/'config.local.json').read_text(encoding='utf-8-sig'))
base=f"http://127.0.0.1:{config.get('port',8765)}"
verified=[];active=[]
with httpx.Client(base_url=base,timeout=30,trust_env=False) as client:
    response=client.get('/api/bootstrap');response.raise_for_status();boot=response.json()
    assert boot['agent_runtime']==config.get('agent_runtime','codex') and boot['model']==config['planning']['model']
    if boot['agent_runtime']=='codex':assert boot['codex_version']=='0.163.0'
    projects=client.get('/api/projects').json()
    for p in projects:
        snapshot=client.get('/api/projects/'+p['id']).json()
        active.extend(t['id'] for t in snapshot['tasks'] if t['status'] in ('queued','running','reconciling','stopping'))
        for delivery in snapshot['deliveries']:
            for suffix,key in [('preview','preview_sha256'),('zip','zip_sha256')]:
                digest=hashlib.sha256()
                with client.stream('GET',f"/api/projects/{p['id']}/deliveries/{delivery['id']}/{suffix}") as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes():digest.update(chunk)
                assert digest.hexdigest()==delivery[key]
            verified.append(delivery['id'])
data=Path(config.get('data_dir','.local/data'))
if not data.is_absolute():data=ROOT/data
providers=json.loads((data/'providers.json').read_text(encoding='utf8'))
expires=[model['quote']['expires'] for provider in providers.values() for model in provider.get('models',{}).values() if model.get('quote')]
evidence={'url':base,'ready':True,'model_unchanged':True,'historical_deliveries_http_hash_verified':len(verified),
          'active_work':active,'provider_quote_expired':bool(expires and min(expires)<time.time()),
          'provider_quote_auto_renewed':False,'provider_generation_requests':0,'read_only':True}
(ROOT/'docs/evidence/compositing/service.json').write_text(json.dumps(evidence,indent=2),encoding='utf8')
print(json.dumps(evidence))

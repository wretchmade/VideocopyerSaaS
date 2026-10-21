"""Content-addressed local store and operator-supplied COS presigned upload boundary."""
import json,os,shutil
from pathlib import Path
from .render import sha
from .store import fingerprint

def configurations():
    path=os.environ.get('D_STORAGE')
    return json.loads(Path(path).read_text(encoding='utf8')) if path else {}

def status():return [dict(id=k,kind=v['kind'],credentialReference=v.get('credential_env'),configured=True) for k,v in configurations().items()]

def publish(asset,name,check):
    config=configurations().get(name)
    if not config:raise ValueError('storage not configured')
    check()
    if sha(asset['path'])!=asset['sha256']:raise ValueError('storage source hash mismatch')
    key=asset['sha256']+Path(asset['path']).suffix
    if config['kind']=='local':
        target=Path(config['root'])/key;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(asset['path'],target)
        return dict(path=str(target),sha256=sha(target),url=config.get('public_base','').rstrip('/')+'/'+key if config.get('public_base') else None)
    if config['kind']!='cos-presigned':raise ValueError('unsupported storage contract')
    from .providers import json_request,request
    secret=os.environ.get(config.get('credential_env',''))
    if not secret:raise ValueError('storage signer credential reference unavailable')
    signed=json_request(config['signer_url'],'POST',dict(key=key,sha256=asset['sha256'],bytes=Path(asset['path']).stat().st_size),{'Content-Type':'application/json','Authorization':'Bearer '+secret})
    request(signed['put_url'],'PUT',Path(asset['path']).read_bytes(),signed.get('headers',{}));check()
    return dict(key=key,sha256=asset['sha256'],url=signed['get_url'])

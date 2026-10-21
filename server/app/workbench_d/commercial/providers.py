"""D remote transport. Provider-specific wire inputs remain explicit, never guessed."""
import base64,json,mimetypes,os,time,re
from pathlib import Path
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.parse import urlparse,quote
from urllib.error import HTTPError
from .store import canonical,fingerprint
from .render import sha,probe
from .ledger import Ledger
from .media import result

# Exact-baseline model identities from package metadata / public contract tables.
SEED=['seedance-2','seedance-2-fast','seedance-2-mini','seedance-2.5']
IMAGE=['gpt-image-2','nano-banana-2','nano-banana-pro']
CATALOG={
 'beatapi':SEED+['minimax-h3','grok-imagine-video-1.5-preview']+IMAGE,
 'hiapi':SEED+['seedream-5-lite','minimax-h3','grok-imagine-video','grok-imagine-video-1.5-preview']+IMAGE,
 'pollo':['minimax-h3','grok-imagine-video-1.5-preview']+IMAGE,
 'tokendance':SEED+['seedream-5-lite','minimax-h3'],
 'monid':SEED+['minimax-h3','wan-2.7-image','wan-2.7-image-pro'],
 'hypihub':SEED+['seedream-5-lite','minimax-h3','grok-imagine-video','grok-imagine-video-1.5-preview','pixverse-v6','pixverse-c1','eleven_ttv_v3','voice-design-1','voice-clone','mimo-v2.5-tts-voicedesign','mimo-v2.5-tts-voiceclone','whisperx-alignment','remove-background','portrait-matting']+IMAGE,
 'ark':['seedance','seedream'],
}

def configurations():
    path=os.environ.get('D_PROVIDERS')
    return json.loads(Path(path).read_text(encoding='utf8')) if path else {}

def get(value,path,default=None):
    for segment in path.split('.') if path else []:
        try:value=value[int(segment)] if isinstance(value,list) else value[segment]
        except (KeyError,IndexError,TypeError,ValueError):return default
    return value

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('redirect refused; configure the final endpoint')

def request(url,method='GET',body=None,headers=None,limit=64*1024*1024):
    parsed=urlparse(url)
    if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1','::1')):raise ValueError('HTTPS or loopback required')
    data=body if isinstance(body,bytes) else canonical(body).encode() if body is not None else None
    try:
        with build_opener(NoRedirect).open(Request(url,data=data,method=method,headers=headers or {}),timeout=30) as response:
            data=response.read(limit+1)
            if len(data)>limit:raise ValueError('response exceeds configured limit')
            return data
    except HTTPError as exc:
        # Never retain credentials, signed URLs, or provider-echoed payloads.
        code = ''
        try:
            error = json.loads(exc.read(65536)).get('error', {})
            candidate = error.get('code', '') if isinstance(error, dict) else ''
            # Only a short enum-like code is retained, never the echoed message.
            if isinstance(candidate, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.]{0,99}', candidate): code = candidate
        except (ValueError, OSError):
            pass
        raise ValueError(f'provider HTTP {exc.code}; code={code or "unavailable"}; request-id={re.sub(r"[^a-zA-Z0-9_-]","",exc.headers.get("x-request-id",""))[:100]}') from None

def json_request(url,method,body,headers):return json.loads(request(url,method,body,headers))

def config_for(task):
    config=configurations().get(task['provider'])
    if not config:raise ValueError('PROVIDER_NOT_CONFIGURED')
    model=config.get('models',{}).get(task['model'])
    if not model:raise ValueError('explicit model mapping required; no substitutions')
    if config.get('service'):
        from .provider_contracts import contract
        model={**contract(config['service'],task['model'],task['output_kind']),**model}
    from .provider_contracts import validate_contract
    validate_contract(task,model)
    if not config.get('account') or not config.get('currency') or not model.get('documentation'):raise ValueError('account, currency and contract source required')
    if not model.get('submit') or not model.get('output_path'):raise ValueError('complete submission and artifact wire contract required')
    if any(not isinstance(model[k],str) or not model[k].startswith('/') for k in ('submit','poll','cancel') if model.get(k)):raise ValueError('provider paths must be relative absolute paths')
    parsed=urlparse(config['base_url'])
    if parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('provider base URL cannot contain credentials, query or fragment')
    if set(task['options'])-set(model.get('fields',[])):raise ValueError('unsupported provider fields')
    if model.get('output_kind')!=task['output_kind']:raise ValueError('provider output kind mismatch')
    return config,model

def catalog():
    configs=configurations()
    return dict(baseline=CATALOG,configured=[dict(id=k,account=v.get('account'),currency=v.get('currency'),models=list(v.get('models',{})),credentialReady=bool(os.environ.get(v.get('credential_env',''))),verification='contract adapter; external model quality unverified') for k,v in configs.items()])

def quote_task(task):
    config,model=config_for(task)
    # An operator-pinned quote is labelled, never represented as a live price.
    quote_data=model.get('quote')
    if quote_data and (type(quote_data.get('upperMicros'))!=int or quote_data['upperMicros']<0):raise ValueError('quote upperMicros must be a nonnegative integer')
    return dict(provider=task['provider'],model=task['model'],account=config['account'],currency=config['currency'],quote=quote_data,source='operator-pinned quote; not a live price',maximumReservedMicros=task['max_cost_micros'],ready=bool(quote_data and quote_data.get('expires',0)>time.time()))

def execute(store,build,task,inputs,folder,check):
    config,model=config_for(task)
    secret=os.environ.get(config.get('credential_env',''))
    if not secret:raise ValueError('credential environment reference unavailable')
    headers={'Content-Type':'application/json',config.get('auth_header','Authorization'):config.get('auth_prefix','Bearer ')+secret}
    ledger=Ledger(store)
    payload={'modelConfig':model,'endpoint':config['base_url'],'task':task,'inputs':[dict(sha256=a['sha256'],kind=a['kind']) for a in inputs]}
    row=ledger.lookup(build,task,payload)
    # Pricing admits a NEW charge. It must never gate GET/download recovery of
    # an existing frozen request, including an independently reconciled identity.
    if row is None or row['state']=='prepared':
        q=quote_task(task)
        if not q['ready']:raise ValueError('fresh pinned price quote required')
        if task['max_cost_micros']<model['quote']['upperMicros']:raise ValueError('maximum reservation below quoted upper estimate')
        row=ledger.reserve(build,task,config['account'],payload,config['currency'])
    rid=row['id']
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    if row['state'] in ('submitting','unknown') and not row['remote']:raise ValueError('SUBMISSION_UNKNOWN: reconcile provider identity; automatic resubmission prohibited')
    if row['state'] in ('failed','cancelled','released'):raise ValueError('remote request is terminal; a new revision and budget are required for another paid request')
    response=json.loads(row['response']) if row.get('response') else None;remote=row['remote']
    if row['state']!='prepared' and model.get('poll') and not remote:raise ValueError('confirmed remote identity required for recovery')
    base=config['base_url'].rstrip('/')
    if row['state']=='prepared':
        check()
        if not ledger.claim_dispatch(rid):raise ValueError('remote dispatch already claimed')
        try:
            # State was committed before references or generation leave the machine.
            urls=[]
            for a in inputs:
                check();raw=Path(a['path']).read_bytes()
                if len(raw)>model.get('max_reference_bytes',15*1024*1024):raise ValueError('reference exceeds model size limit')
                mode=model.get('reference_modes',{}).get(a['kind'],model.get('references','none'));mime=mimetypes.guess_type(a['path'])[0] or 'application/octet-stream'
                if mode=='inline':urls.append('data:'+mime+';base64,'+base64.b64encode(raw).decode())
                elif mode=='upload':
                    upload=config.get('upload')
                    if not upload:raise ValueError('upload contract missing')
                    h={**headers,'Content-Type':mime}
                    upload_response=json.loads(request(base+upload['path'],'POST',raw,h))
                    url=get(upload_response,upload['url_path'])
                    if not url:raise ValueError('upload returned no URL')
                    urls.append(url)
                elif mode=='storage':
                    from .storage import publish
                    urls.append(publish(a,config['storage'],check)['url'])
                else:raise ValueError('model does not accept references')
            from .provider_contracts import payload as make_payload
            body=make_payload(task,model,inputs,urls)
            response=json_request(base+model['submit'],'POST',body,{**headers,'Idempotency-Key':rid})
            remote=get(response,model.get('id_path','id'))
            if not remote and model.get('poll'):raise ValueError('submission response missing remote identity')
            ledger.update(rid,'accepted',str(remote) if remote else None,response)
        except Exception:
            ledger.update(rid,'unknown',error='submission or upload outcome ambiguous; inspect provider before retry')
            raise
    deadline=time.monotonic()+model.get('timeout_seconds',1800)
    try:
        while model.get('poll'):
            check()
            if time.monotonic()>deadline:raise TimeoutError('remote task still pending; resume polling without a new submission')
            response=json_request(base+model['poll'].replace('{id}',quote(str(remote),safe='')),'GET',None,headers)
            state=get(response,model.get('status_path','status'))
            if state in model.get('success',['succeeded']):break
            if state in model.get('failure',['failed','cancelled']):
                ledger.update(rid,'failed',response=response,error='provider task failed')
                raise ValueError('provider task failed; consult remote task identity')
            ledger.update(rid,'running',response=response)
            for _ in range(max(1,int(model.get('poll_seconds',5)*10))):check();time.sleep(.1)
        urls=get(response,model['output_path'])
        if not isinstance(urls,list):urls=[urls]
        urls=[get(u,model.get('output_item_path','')) for u in urls]
        if not urls or any(not isinstance(u,str) for u in urls):raise ValueError('provider returned no usable artifacts')
        artifacts=[]
        for i,url in enumerate(urls):
            check();kind=task['output_kind'];ext={'image':'.png','video':'.mp4','audio':'.wav','transcript':'.json'}[kind]
            path=folder/(str(i)+ext)
            # Artifact URLs never receive provider credentials.
            path.write_bytes(request(url,limit=512*1024*1024))
            if kind=='image':
                from PIL import Image
                with Image.open(path) as im:im.load();im.convert('RGBA').save(path,format='PNG')
            elif kind in ('audio','video'):
                metadata=probe(path,check)
                if not any(s['codec_type']==kind for s in metadata['streams']):raise ValueError('provider artifact stream kind mismatch')
            else:json.loads(path.read_text(encoding='utf8'))
            artifacts.append(result(path,kind,inputs))
        ledger.update(rid,'succeeded',response=response)
        return {**artifacts[0],'artifacts':artifacts,'requestId':rid,'remoteId':remote}
    except InterruptedError:
        ledger.update(rid,'cancel_requested',remote=str(remote) if remote else None)
        if model.get('cancel') and remote:
            json_request(base+model['cancel'].replace('{id}',quote(str(remote),safe='')),model.get('cancel_method','DELETE'),None,headers)
            # An acknowledged cancellation request does not prove cancellation or a refund.
        raise

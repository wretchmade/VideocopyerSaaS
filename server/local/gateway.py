"""Server-side Responses boundary: credentials, tool allowlist and global spend admission."""
import json, math, re, time
import httpx
from fastapi import Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from . import db
from .config import CONFIG
from .credentials import planning_key
from .bridge import GATEWAY_TOKENS
from .tool_registry import gateway_contract,restore_tool_calls

def provider_error_code(raw, key):
    """Only retain short enum codes; providers may echo credentials in errors."""
    try:
        code=json.loads(raw)['error']['code']
    except (ValueError, KeyError, TypeError):
        return 'provider_error'
    if not isinstance(code,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.]{0,99}',code):
        return 'provider_error'
    if key and key in code:
        return 'provider_error'
    return code

async def responses(pid,request:Request):
    token=request.headers.get('authorization','').removeprefix('Bearer ')
    if GATEWAY_TOKENS.get(token)!=pid: raise HTTPException(403,'Private agent boundary')
    raw=await request.body()
    if len(raw)>8*1024*1024:raise HTTPException(413,'上下文超过本地规划上限')
    body=json.loads(raw);cfg=CONFIG['planning'];key=planning_key()
    if not key:raise HTTPException(409,'规划 API 尚未配置')
    # Ark accepts function tools, not OpenAI tool namespaces or internal Codex tools.
    functions,aliases=gateway_contract(body.get('tools',[]))
    payload={k:v for k,v in body.items() if k in {'input','instructions','stream','store','temperature','top_p'}}
    payload.update(model=cfg['model'],stream=True,store=False,tools=functions,max_output_tokens=int(cfg.get('max_output_tokens',4096)))
    # Remove Codex-only tool namespace metadata; keep complete conversation items.
    for item in payload.get('input',[]):
        if isinstance(item,dict):
            namespace=item.pop('namespace',None)
            if item.get('type')=='function_call':
                for wire,original in aliases.items():
                    if original=={'name':item.get('name'),'namespace':namespace}:item['name']=wire;break
            if item.get('type')=='message' and item.get('role')=='developer':item['role']='system'
    rate_in=cfg.get('input_cny_per_million');rate_out=cfg.get('output_cny_per_million')
    if not rate_in or not rate_out:raise HTTPException(409,'请先配置规划模型的费用上界')
    # Byte count is deliberately conservative for textual input; reject image blobs
    # above the cap rather than calling them free. Actual provider bill remains pending.
    upper=math.ceil(len(json.dumps(payload,ensure_ascii=False).encode())*rate_in+payload['max_output_tokens']*rate_out)
    rid=db.uid()
    with db.transaction() as c:
        db.reserve(c,rid,pid,upper,'planning',{'model':cfg['model'],'bytes':len(raw)})
        row=db.get(c,'usage',rid);row['state']='submitting';db.put(c,'usage',rid,row,pid,True)
        db.emit(c,pid,'usage/reserved',{'id':rid,'reserved_micros':upper})
    client=httpx.AsyncClient(timeout=httpx.Timeout(180,connect=20),follow_redirects=False,trust_env=False)
    try:
        req=client.build_request('POST',cfg['base_url'].rstrip('/')+'/responses',headers={'Authorization':'Bearer '+key},json=payload)
        response=await client.send(req,stream=True)
    except Exception:
        await client.aclose()
        with db.transaction() as c:
            row=db.get(c,'usage',rid);row['state']='reconciling';db.put(c,'usage',rid,row,pid,True)
        raise HTTPException(502,'规划请求连接中断，费用待核对；未自动重试')
    if response.status_code!=200:
        error=await response.aread();await client.aclose()
        code=provider_error_code(error,key)
        with db.transaction() as c:
            row=db.get(c,'usage',rid);row.update(state='released' if response.status_code<500 else 'reconciling',error=code);db.put(c,'usage',rid,row,pid,True)
        return JSONResponse({'error':{'message':'Ark 规划请求失败：'+str(code),'code':code}},status_code=response.status_code)
    async def stream():
        completed=False
        try:
            async for line in response.aiter_lines():
                if line.startswith('data: '):
                    try:
                        event=json.loads(line[6:])
                        event=restore_tool_calls(event,aliases)
                        line='data: '+json.dumps(event,ensure_ascii=False)
                        if event.get('type')=='response.completed':
                            usage=event.get('response',{}).get('usage',{});completed=True
                            with db.transaction() as c:
                                row=db.get(c,'usage',rid);row.update(state='succeeded',tokens=usage,provider_response=event.get('response',{}).get('id'),bill_status='待供应商对账');db.put(c,'usage',rid,row,pid,True)
                                db.emit(c,pid,'usage/completed',row)
                    except ValueError:pass
                yield (line+'\n').encode()
        finally:
            await response.aclose();await client.aclose()
            if not completed:
                with db.transaction() as c:
                    row=db.get(c,'usage',rid);row['state']='reconciling';db.put(c,'usage',rid,row,pid,True)
    return StreamingResponse(stream(),media_type='text/event-stream')

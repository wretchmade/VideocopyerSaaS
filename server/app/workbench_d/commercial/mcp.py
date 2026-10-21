"""Concurrent JSON-RPC stdio server using only the D core dependency closure."""
import json, sys
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from .api import tools,dispatch


def serve(input_stream=sys.stdin,output_stream=sys.stdout):
    lock=Lock()
    def emit(value):
        with lock:print(json.dumps(value,ensure_ascii=False),file=output_stream,flush=True)
    def call(request):
        try:result={'content':[{'type':'text','text':json.dumps(dispatch(request['params']['name'],request['params'].get('arguments',{})),ensure_ascii=False)}]}
        except Exception as exc:result={'isError':True,'content':[{'type':'text','text':str(exc)}]}
        emit(dict(jsonrpc='2.0',id=request['id'],result=result))
    with ThreadPoolExecutor(max_workers=8) as executor:
        for line in input_stream:
            request={}
            try:
                request=json.loads(line)
                if 'id' not in request:continue
                method=request.get('method')
                if method=='tools/call':executor.submit(call,request);continue
                if method=='initialize':result={'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'workbench-d-core','version':'2.0.0-beta.1'}}
                elif method=='ping':result={}
                elif method=='tools/list':result={'tools':tools()}
                else:
                    emit(dict(jsonrpc='2.0',id=request['id'],error={'code':-32601,'message':'Method not found'}));continue
                emit(dict(jsonrpc='2.0',id=request['id'],result=result))
            except Exception as exc:emit(dict(jsonrpc='2.0',id=request.get('id'),error={'code':-32600,'message':str(exc)}))


if __name__=='__main__':serve()

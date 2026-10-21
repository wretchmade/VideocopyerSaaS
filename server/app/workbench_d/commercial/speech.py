"""Independent speech model process boundary; weights are never bundled/downloaded."""
import json,os,re
from pathlib import Path
from .render import sha,command,binary,probe
from .media import result

OPERATIONS=['tts','asr','forced-align','voice-convert','background-remove','video-segment']

def adapters():
    path=os.environ.get('D_MODEL_ADAPTERS')
    return json.loads(Path(path).read_text(encoding='utf8')) if path else {}

def readiness():
    return [{ 'id':name,'operations':v.get('operations',[]),'ready':ready(v),'quality':'not verified without real model run','license':v.get('license'),'weights':[{k:w.get(k) for k in ('name','sha256','license')} for w in v.get('weights',[])]} for name,v in adapters().items()]

def ready(config):
    return bool(config.get('license') and config.get('weights') and Path(config.get('python','')).is_file() and Path(config.get('script','')).is_file() and sha(config['script'])==config.get('script_sha256') and all(w.get('license') and Path(w.get('path','')).is_file() and sha(w['path'])==w.get('sha256') for w in config.get('weights',[])))

def normalize_transcript(raw,source_hash,corrected=None,sample_rate=16000):
    words=raw.get('words',[])
    if not words:raise ValueError('model returned no transcript words')
    if corrected is not None:
        authored=re.findall(r'[\u3400-\u9fff]|[^\s\u3400-\u9fff]+',corrected)
        if [w['text'] for w in words]!=authored:raise ValueError('aligner must return every corrected token, with null boundaries for unaligned tokens')
    normalized=[];previous=0
    for index,w in enumerate(words):
        start=w.get('start');end=w.get('end');missing=start is None or end is None
        if not missing:
            start=round(float(start)*sample_rate);end=round(float(end)*sample_rate)
            if not previous<=start<end:raise ValueError('nonmonotonic word boundaries')
            previous=end
        from .store import fingerprint
        normalized.append(dict(wordId=fingerprint([source_hash,index,w['text']])[:24],text=w['text'],startSample=None if missing else start,endSample=None if missing else end,missing=missing))
    return dict(format='d-transcript-1',sourceHash=source_hash,sampleRate=sample_rate,words=normalized,alignment=raw.get('alignment','acoustic-model'),language=raw.get('language'))

from .resources import operation

@operation('local-model')
def execute(task,inputs,folder,check):
    config=adapters().get(task['provider'])
    if not config or not ready(config):raise ValueError('MODEL_NOT_READY: explicit adapter, pinned weights and license records required')
    if task['operation'] not in config['operations']:raise ValueError('operation absent from adapter contract')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    request={'operation':task['operation'],'options':task['options'],'model':task['model'],'inputs':inputs,'weights':config['weights'],'settings':config.get('settings',{})}
    if task['operation'] in ('asr','forced-align'):
        if len(inputs)!=1:raise ValueError('speech recognition/alignment needs one source')
        evidence=folder/'evidence.wav';command([binary('ffmpeg'),'-v','error','-y','-i',inputs[0]['path'],'-vn','-ar','16000','-ac','1','-c:a','pcm_s16le',evidence],check)
        request['evidence']={'path':str(evidence.resolve()),'sha256':sha(evidence),'sampleRate':16000}
    request_path=folder/'request.json';response_path=folder/'response.json'
    request_path.write_text(json.dumps(request,ensure_ascii=False),encoding='utf8')
    command([config['python'],config['script'],'--request',request_path.resolve(),'--response',response_path.resolve()],check,timeout=3600)
    value=json.loads(response_path.read_text(encoding='utf8'))
    if task['operation'] in ('asr','forced-align'):
        transcript=normalize_transcript(value,inputs[0]['sha256'],task['options'].get('text') if task['operation']=='forced-align' else None)
        transcript['evidenceHash']=request['evidence']['sha256'];transcript['adapterScriptHash']=config['script_sha256']
        path=folder/'transcript.json';path.write_text(json.dumps(transcript,ensure_ascii=False),encoding='utf8')
        return result(path,'transcript',inputs)
    path=Path(value['path']).resolve()
    if not path.is_relative_to(folder.resolve()) or not path.is_file():raise ValueError('adapter output must be inside task directory')
    expected={'tts':'audio','voice-convert':'audio','background-remove':'image','video-segment':'video'}[task['operation']]
    if expected!='image':
        metadata=probe(path,check)
        if not any(s['codec_type']==expected for s in metadata['streams']):raise ValueError('model output stream kind mismatch')
    else:
        from PIL import Image
        with Image.open(path) as image:
            image.load()
            if 'A' not in image.getbands():raise ValueError('background removal must return alpha')
    return result(path,expected,inputs,adapter_hash=config['script_sha256'],quality='model quality requires independent acceptance')

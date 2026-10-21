"""Independent wire-contract declarations. No credentials or prices shipped."""
from copy import deepcopy

def contract(service,name,kind):
    common=dict(output_kind=kind,fields=['duration','resolution','aspect_ratio','size','n','seed','generate_audio'],references='storage',max_reference_bytes=15*1024*1024,model_field='model',wire_model=name,verification='public contract / mock only; live availability and quality unverified')
    if service=='beatapi':
        return dict(common,submit='/v1/images/tasks' if kind=='image' else '/v1/videos/tasks',poll='/v1/tasks/{id}',id_path='data.id',status_path='data.status',output_path='data.output.media',output_item_path='url',references='upload',reference_style='beat',wire_model='grok-imagine-video-1.5' if name=='grok-imagine-video-1.5-preview' else name,documentation='https://docs.beatapi.io/quick-guide')
    if service=='ark' or service=='tokendance':
        if service=='tokendance' and name=='minimax-h3':
            return dict(common,submit='/minimax/v2/video_generation',poll='/minimax/v2/query/video_generation/{id}',id_path='task_id',status_path='status',output_path='content.url',content_field='content',documentation='https://tokendance.space',requires_verified_override=True)
        prefix='/api/v3' if service=='ark' else '/ark/v3'
        image=kind=='image'
        return dict(common,submit=prefix+('/images/generations' if image else '/contents/generations/tasks' if service=='ark' else '/generations/tasks'),poll=None if image else prefix+('/contents/generations/tasks/{id}' if service=='ark' else '/generations/tasks/{id}'),id_path='id',status_path='status',output_path='data' if image else 'content.video_url',output_item_path='url' if image else '',references='inline',reference_modes={'video':'storage'},reference_field='image' if image else None,content_field=None if image else 'content',fields=['duration','resolution','ratio','size','seed','generate_audio','watermark','response_format'],documentation='https://docs.volcengine.com/docs/ark/image-generation-api' if image else 'https://docs.volcengine.com/docs/ark/create-video-generation-task-api')
    if service=='hiapi':
        return dict(common,submit='/v1/tasks',poll='/v1/tasks/{id}',id_path='data.task_id',status_path='data.status',output_path='data.output',output_item_path='url',wrapper='input',model_in_envelope=True,references='inline',reference_field='images',documentation='https://www.hiapi.ai/docs/models.json',requires_verified_override=True)
    if service=='pollo':
        route={'minimax-h3':'minimax/minimax-h3/video','grok-imagine-video-1.5-preview':'xai/grok-imagine-video-1-5/video','gpt-image-2':'openai/gpt-image-2/image','nano-banana-2':'google/nano-banana-2/image','nano-banana-pro':'google/nano-banana-pro/image'}[name]
        return dict(common,submit='/v1/generation/'+route,poll='/v1/generation/{id}/status',id_path='taskId',status_path='generations.0.status',success=['succeed'],failure=['failed'],output_path='generations',output_item_path='url',wrapper='input',model_field=None,reference_style='pollo',fields=['duration','resolution','aspectRatio','seed'],documentation='https://docs.pollo.ai')
    if service=='monid':
        wire=name.replace('seedance-2','seedance-2.0') if name in ('seedance-2','seedance-2-fast','seedance-2-mini') else name
        return dict(common,submit='/v1/run',poll='/v1/runs/{id}',id_path='runId',status_path='status',success=['COMPLETED'],failure=['FAILED','BLOCKED','STOPPED','TIMED_OUT'],output_path='output',wrapper='input',envelope={'provider':'alibaba' if kind=='image' else 'minimax' if name=='minimax-h3' else 'bytedance','endpoint':'/v1/'+('image/' if kind=='image' else 'video/')+wire},content_field=None if kind=='image' else 'content',reference_field='images' if kind=='image' else None,documentation='https://monid.ai',requires_verified_override=True)
    if service=='hypihub':
        if kind not in ('image','video') or name in ('remove-background','portrait-matting'):
            return dict(common,documentation='https://hypihub.ai',requires_verified_override=True)
        return dict(common,submit='/v1/images/generations' if kind=='image' else '/v1/videos',poll='/v1/tasks/{id}',id_path='id',status_path='status',output_path='data',output_item_path='url',reference_style='hub',documentation='https://hypihub.ai',requires_verified_override=True)
    raise ValueError('unknown service')

def validate_contract(task,model):
    if model.get('requires_verified_override') and not model.get('verified_contract_sha256'):raise ValueError('authenticated/current wire contract must be supplied and pinned for this service')
    roles=task.get('input_roles') or ['reference_'+a for a in []]
    if task.get('inputs') and len(roles)!=len(task['inputs']):raise ValueError('explicit role for each generation reference required')
    if 'last_frame' in roles and 'first_frame' not in roles:raise ValueError('last frame requires first frame')
    name=task.get('model','');o=task['options']
    if name=='seedance-2-mini' and o.get('generate_audio'):raise ValueError('mini does not support generated audio')

def payload(task,model,inputs,urls):
    validate_contract(task,model)
    body={**model.get('defaults',{}),**task['options']};prompt_field=model.get('prompt_field','prompt');model_field=model.get('model_field','model')
    if task.get('prompt') is not None or task.get('brand_reference'):
        from .brand import generation_prompt
        body[prompt_field]=generation_prompt(task)
    if model_field:body[model_field]=model.get('wire_model',task['model'])
    roles=task.get('input_roles') or model.get('reference_roles',[])
    style=model.get('reference_style')
    if urls:
        if model.get('reference_field'):body[model['reference_field']]=urls
        elif model.get('content_field'):
            body[model['content_field']]=[{'type':'text','text':body.pop(prompt_field,'')}]+[{'type':a['kind']+'_url',a['kind']+'_url':{'url':u},'role':role} for a,u,role in zip(inputs,urls,roles)]
        elif style=='beat':
            frames={role:url for role,url in zip(roles,urls) if role in ('first_frame','last_frame')}
            if frames:body['images']=[frames[r] for r in ('first_frame','last_frame') if r in frames]
            for role in ('reference_image','reference_video','reference_audio'):
                selected=[u for r,u in zip(roles,urls) if r==role]
                if selected:body[role+'s']=selected
        elif style=='pollo':
            refs=[]
            for role,u in zip(roles,urls):
                if role=='first_frame':body['image']=u
                elif role=='last_frame':body['imageTail']=u
                else:refs.append({'type':role.removeprefix('reference_'),'url':u})
            if refs:body['refs']=refs
        elif style=='hub':
            for role,u in zip(roles,urls):
                if role in ('first_frame','last_frame'):body[role]=u
                else:body.setdefault(role+'s',[]).append({'url':u} if task['output_kind']=='image' else u)
        else:raise ValueError('reference mapping missing')
    elif model.get('content_field'):body[model['content_field']]=[{'type':'text','text':body.pop(prompt_field,'')}]
    if model.get('wrapper'):
        envelope=deepcopy(model.get('envelope',{}))
        if model.get('model_in_envelope') and model_field:envelope[model_field]=body.pop(model_field)
        body={model['wrapper']:body,**envelope}
    return body

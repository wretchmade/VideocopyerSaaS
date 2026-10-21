"""Real project-scoped local tool lifecycle; no model or media provider calls."""
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
import pytest
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault("VC_DATA",tempfile.mkdtemp(prefix="vc-tools-"))
sys.path.insert(0,str(ROOT/"server"))
from local import db,projects,production,commands
from app.workbench_d.commercial.engine import Engine
from app.workbench_d.commercial.worker import run
from app.workbench_d.commercial.render import sha


def test_scoped_native_tool_lifecycles(monkeypatch):
    monkeypatch.setitem(production.CONFIG,"media_profile","")
    production.setup_media()
    monkeypatch.setattr(Engine,"launch",lambda *a:None)
    # Serialization/relocation is tested in a new fixture directory, not the actual editor.
    monkeypatch.setattr("app.workbench_d.commercial.drafts.guard_directory",lambda p:Path(p).resolve())
    pid=projects.create(db.uid(),"tool lifecycle fixture")["id"]
    seen=[]
    def call(tool_name,**args):
        if tool_name not in {'d_capabilities','d_storage_status','d_list_projects','d_inspect_project','d_check_project','d_plan_build','d_build_status','d_inspect_build','d_preview_frame','d_get_feedback','d_canvas_status','d_list_workflows','d_preflight_reuse','d_retention_check','d_jianying_list','d_jianying_inspect'}:
            args.setdefault('commandId',db.uid())
        result=commands.dispatch(pid,tool_name,args);seen.append(tool_name);return result
    out=io.BytesIO();Image.new('RGB',(64,64),'#126c52').save(out,format='PNG')
    file=projects.add_file(pid,'local.png',out.getvalue())
    font=Path(production.CONFIG['font'])
    doc={'width':64,'height':64,'frames':3,'assets':[
        {'id':'image','kind':'image','path':'file:'+file['id'],'sha256':file['sha256'],'license':'fixture generated','source':'local fixture'},
        {'id':'font','kind':'font','path':'resource:font','sha256':sha(font),'license':'local system font','source':'configured font'}],
        'layers':[{'id':'picture','kind':'image','asset':'image','end':3,'width':64,'height':64},
                  {'id':'title','kind':'text','text':'Test','fonts':['font'],'font_size':12,'end':3,'width':64,'height':20,'track':1}]}
    assert call('d_capabilities')['brandProtection']['bindingTool']=='d_bind_brand_lock'
    call('d_storage_status')
    p=call('d_create_project',name='native',document=doc)
    assert call('d_list_projects')[0]['projectId']==p['projectId']
    assert call('d_inspect_project',projectId=p['projectId'])['authorRevision']==0
    doc=p['document'];doc['background']='#102030'
    p=call('d_edit_project',projectId=p['projectId'],baseRevision=0,document=doc)
    assert call('d_check_project',projectId=p['projectId'])['executable']
    assert call('d_plan_build',projectId=p['projectId'])['documentHash']==p['sha256']
    q=call('d_submit_build',projectId=p['projectId'],revision=1)['quote']
    task=commands.confirm(pid,q['id'],db.uid());commands.tick_native(task)
    with db.transaction() as c:task=db.get(c,'task',task['id'],pid)
    e=commands.engine(pid);run(task['build_id'],e.store);commands.tick_native(task)
    assert call('d_build_status',buildId=task['build_id'])['status']=='succeeded'
    assert call('d_inspect_build',buildId=task['build_id'])['remoteRequests']==[]
    preview=call('d_preview_frame',projectId=p['projectId'],revision=1,frame=0)
    assert preview['url'].startswith('/api/projects/'+pid+'/files/')
    review=call('d_prepare_studio',buildId=task['build_id'])
    comment=call('d_add_feedback',reviewId=review['reviewId'],frame=0,body='Adjust title')
    call('d_resolve_feedback',feedbackId=comment['feedbackId'],baseVersion=0)
    call('d_reopen_feedback',feedbackId=comment['feedbackId'],baseVersion=1)
    call('d_sync_feedback',reviewId=review['reviewId'],documentHash=p['sha256'],comments=[{'externalId':'offline','frame':1,'body':'Review exact frame'}])
    assert len(call('d_get_feedback',reviewId=review['reviewId'])['comments'])==2
    view={'viewport':{'x':0,'y':0,'zoom':1},'groups':[{'id':'g','title':'Composition','x':0,'y':0,'members':['picture','title']}]}
    call('d_save_view',projectId=p['projectId'],revision=1,baseVersion=0,view=view)
    assert call('d_canvas_status',projectId=p['projectId'],revision=1)['version']==1
    archive=call('d_archive_workflow',projectId=p['projectId'],revision=1,name='reusable',parameterDeclarations=[{'path':'layers.1.text'}])
    assert len(call('d_list_workflows',query='reusable'))==1
    assert call('d_rebuild_index')['indexed']==1
    assert call('d_preflight_reuse',workflowId=archive['workflowId'],parameters={'layers.1.text':'Next'})['compatible']
    fresh=call('d_instantiate_workflow',workflowId=archive['workflowId'],name='copy',parameters={'layers.1.text':'Next'})
    assert fresh['projectId']!=p['projectId']
    assert not call('d_retention_check',sha256=file['sha256'])['deletable']
    delivered=call('d_deliver_mp4',buildId=task['build_id'])
    from local.media_access import inspect_media
    uploaded_video=projects.add_file(pid,'review.mp4',Path(delivered['path']).read_bytes())
    assert inspect_media(pid,{'file_id':uploaded_video['id'],'frame':0})['_contentItems'][0]['imageUrl'].startswith('data:image/jpeg;base64,')
    with pytest.raises(ValueError,match='超出'):inspect_media(pid,{'file_id':uploaded_video['id'],'frame':99})
    choice=call('d_choose_export',deliveryId=delivered['deliveryId'],format='jianying',allowBaked=False)
    draft=call('d_export_draft',choiceId=choice['choiceId'],name='paired')
    assert draft['source']['buildId']==task['build_id'] and draft['archive_url'] and draft['web_delivery_id']
    with db.transaction() as c:
        paired=db.get(c,'delivery',draft['web_delivery_id'],pid)
        assert paired['build_id']==task['build_id']
    local=call('d_jianying_create',projectId=fresh['projectId'],revision=0,name='independent',allowBaked=False)
    assert len(call('d_jianying_list'))==2
    assert call('d_jianying_inspect',draftId=local['draftId'])['manualChanges']==[]
    edited=call('d_jianying_edit',draftId=local['draftId'],baseRevision=0,expectedHash=local['nativeHash'],actions=[{'op':'subtitle','id':'title','text':'Edited'}])
    dest=production.DATA/'projects'/pid/'installed-fixture'
    installed=call('d_jianying_publish',draftId=edited['draftId'],revision=1,expectedHash=edited['nativeHash'],directory=str(dest))
    imported=call('d_jianying_import',directory=str(dest),expectedHash=installed['nativeHash'],name='imported')
    assert imported['draftId']!=edited['draftId']
    with db.transaction() as c:zip_file=db.get(c,'file',draft['archive_file_id'],pid)
    with zipfile.ZipFile(zip_file['path']) as package:
        assert not any('/frames-' in n or '/raster/' in n for n in package.namelist())
    protected=call('d_bind_brand_lock',projectId=fresh['projectId'],baseRevision=0,layerId='picture',placement={'mode':'screen','reviewed':True})
    assert protected['authorRevision']==1
    brand_quote=commands.prepare(pid)
    branded=commands.confirm(pid,brand_quote['id'],db.uid());commands.tick_native(branded)
    with db.transaction() as c:branded=db.get(c,'task',branded['id'],pid)
    run(branded['build_id'],e.store);commands.tick_native(branded)
    # Exact-result review declaration is retained separately from real human/UI validation.
    row=e.store.build(branded['build_id'])
    reviewed=call('d_review_brand_build',buildId=branded['build_id'],sha256=row['result']['sha256'],approved=True,note='Fixture declaration; not human visual acceptance')
    assert reviewed['approved']
    (ROOT/'docs/evidence/parity/tool-lifecycles.json').write_text(json.dumps({'passed':sorted(set(seen)),'real_local_render':True,'editor_ui_verified':False,'provider_requests':0},indent=2),encoding='utf8')

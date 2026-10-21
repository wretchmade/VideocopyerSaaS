import json,os,wave
from pathlib import Path
import pytest
from PIL import Image
from app.workbench_d.commercial.engine import Engine
from app.workbench_d.commercial.worker import run
from app.workbench_d.commercial.production_state import ProductionState
from app.workbench_d.commercial.drafts import Drafts
from app.workbench_d.commercial.render import sha
from app.workbench_d.commercial.store import fingerprint

def call(obj,method,**args):return getattr(obj,method)({'commandId':os.urandom(8).hex(),**args})

@pytest.fixture
def studio(tmp_path,monkeypatch):
    monkeypatch.setattr(Engine,'launch',lambda *a:None)
    engine=Engine(tmp_path/'data');state=ProductionState(engine)
    pic=tmp_path/'image.png';Image.new('RGBA',(64,64),'#55bbaa').save(pic)
    audio=tmp_path/'audio.wav'
    with wave.open(str(audio),'wb') as out:out.setparams((1,2,48000,0,'NONE','not compressed'));out.writeframes(b'\x00\x00'*48000)
    def asset(path,kind,id):return dict(id=id,kind=kind,path=str(path),sha256=sha(path),license='test generated' if kind!='font' else 'OFL-1.1',source='test' if kind!='font' else 'Noto Sans SC')
    assets=[asset(pic,'image','image'),asset(audio,'audio','audio'),asset(Path(os.environ['D_TEST_FONT']),'font','font')]
    doc=dict(width=128,height=128,frames=30,assets=assets,layers=[dict(id='picture',kind='image',asset='image',end=30,width=64,height=64,x=32,y=32),dict(id='title',kind='text',text='Editable',fonts=['font'],font_size=16,end=30,width=128,height=24,track=1)],audio=[dict(asset='audio',end=30,volume=.4)])
    p=call(engine,'create',name='stage4',document=doc)
    return engine,state,p

def test_review_exact_revision_feedback_conflict_and_sync(studio):
    engine,state,p=studio;b=call(engine,'submit',projectId=p['projectId'],revision=0);run(b['buildId'],engine.store)
    r=call(state,'prepare_studio',buildId=b['buildId']);assert r['revision']==0
    c=call(state,'add_feedback',reviewId=r['reviewId'],frame=12,body='Adjust subtitle')
    state.feedback_state(dict(commandId='resolve',feedbackId=c['feedbackId'],baseVersion=0),'resolved')
    with pytest.raises(ValueError,match='CONFLICT'):state.feedback_state(dict(commandId='stale',feedbackId=c['feedbackId'],baseVersion=0),'open')
    state.feedback_state(dict(commandId='reopen',feedbackId=c['feedbackId'],baseVersion=1),'open')
    call(engine,'edit',projectId=p['projectId'],baseRevision=0,document={**p['document'],'background':'#224466'})
    assert state.get_feedback({'reviewId':r['reviewId']})['review']['documentHash']==p['sha256']
    args=dict(reviewId=r['reviewId'],documentHash=r['documentHash'],comments=[dict(externalId='offline-1',frame=2,body='Offline review')])
    assert len(call(state,'sync_feedback',**args)['imported'])==1
    assert call(state,'sync_feedback',**args)['imported']==[]
    with pytest.raises(ValueError,match='outside'):call(state,'add_feedback',reviewId=r['reviewId'],frame=30,body='invalid')

def test_workflow_owns_assets_rebuild_preflight_replacement_no_budget(studio):
    engine,state,p=studio;archive=call(state,'archive_workflow',projectId=p['projectId'],revision=0,name='Reusable',parameterDeclarations=[dict(path='layers.1.text')])
    args=dict(workflowId=archive['workflowId']);assert state.preflight_reuse(args)['compatible']
    with engine.store.connect() as db:db.execute('DELETE FROM workflow_index')
    assert call(state,'rebuild_index')['indexed']==1
    manifest=json.loads(Path(archive['path']).read_text(encoding='utf8'));asset=manifest['document']['assets'][0];owned=Path(archive['path']).parent/asset['path'];owned.write_bytes(b'changed')
    assert not state.preflight_reuse(args)['compatible']
    original=p['document']['assets'][0];args['replacements']={'image':original}
    fresh=call(state,'instantiate_workflow',**args,name='Independent',parameters={'layers.1.text':'Replacement'})
    assert fresh['projectId']!=p['projectId'] and fresh['authorRevision']==0 and fresh['document']['layers'][1]['text']=='Replacement'
    assert not state.preflight_reuse(args)['budgetInherited']
    assert not state.retention_check({'sha256':original['sha256']})['deletable']
    with pytest.raises(ValueError,match='not declared'):state.preflight_reuse({**args,'parameters':{'tasks.0.budget':'secret'}})

def test_canvas_cas_visible_receipt_bound_to_hash_and_layout(studio):
    engine,state,p=studio;args=dict(projectId=p['projectId'],revision=0)
    assert state.canvas_status(args)['visibleReceipts']==[]
    view=dict(viewport=dict(x=40,y=-10,zoom=.8),groups=[dict(id='main',title='Main',members=['picture','title'])])
    saved=call(state,'save_view',**args,baseVersion=0,view=view)
    with pytest.raises(ValueError,match='CONFLICT'):call(state,'save_view',**args,baseVersion=0,view=view)
    with pytest.raises(ValueError,match='hash'):call(state,'record_view',**args,documentHash='wrong',viewVersion=1,session='browser',visibility='visible')
    call(state,'record_view',**args,documentHash=p['sha256'],viewVersion=saved['version'],session='browser',visibility='visible')
    assert len(ProductionState(Engine(engine.store.root.parent)).canvas_status(args)['visibleReceipts'])==1

def test_draft_multitrack_edit_relocate_import_immutable_and_manual_change(studio,tmp_path):
    engine,state,p=studio;drafts=Drafts(engine)
    d=call(drafts,'create',projectId=p['projectId'],revision=0,name='Isolated',allowBaked=False)
    native=json.loads((Path(d['path'])/'draft_content.json').read_text(encoding='utf8'));assert [t['type'] for t in native['tracks']]==['video','video','text','audio']
    assert not d['editorUIVerified'] and d['baked']==[]
    oldhash=d['nativeHash']
    edited=call(drafts,'edit',draftId=d['draftId'],baseRevision=0,expectedHash=oldhash,actions=[dict(op='split',id='picture',frame=15),dict(op='subtitle',id='title',text='Revised'),dict(op='volume',target='audio',index=0,value=.2)])
    assert edited['revision']==1 and sha(Path(d['path'])/'draft_content.json')==oldhash
    with pytest.raises(ValueError,match='CONFLICT'):call(drafts,'edit',draftId=d['draftId'],baseRevision=0,expectedHash=oldhash,actions=[])
    installed=call(drafts,'publish',draftId=d['draftId'],revision=1,expectedHash=edited['nativeHash'],directory=str(tmp_path/'isolated-installed'))
    content=(Path(installed['path'])/'draft_content.json').read_text(encoding='utf8');assert str(Path(edited['path'])).replace('\\','\\\\') not in content
    font_path=json.loads(json.loads(content)['materials']['texts'][0]['content'])['styles'][0]['font']['path']
    assert Path(font_path).is_relative_to(Path(installed['path'])) and Path(font_path).is_file()
    imported=call(drafts,'import_draft',directory=installed['path'],expectedHash=installed['nativeHash'],name='Imported')
    assert imported['draftId']!=d['draftId']
    with pytest.raises(ValueError,match='EXISTS'):call(drafts,'publish',draftId=d['draftId'],revision=1,expectedHash=edited['nativeHash'],directory=installed['path'])
    (Path(edited['path'])/'draft_content.json').write_text('{}')
    with pytest.raises(ValueError,match='MANUAL_CHANGE'):call(drafts,'edit',draftId=d['draftId'],baseRevision=1,expectedHash=edited['nativeHash'],actions=[])

def test_draft_explicit_bake_encrypted_and_lock_rejection(studio,tmp_path):
    engine,state,p=studio;drafts=Drafts(engine);doc=p['document'];doc['layers'].append(dict(id='effect',kind='rect',end=30,width=20,height=20,color='#ffcc44',track=3))
    p=call(engine,'edit',projectId=p['projectId'],baseRevision=0,document=doc)
    with pytest.raises(ValueError,match='DEGRADATION'):call(drafts,'create',projectId=p['projectId'],revision=1,name='No bake',allowBaked=False)
    d=call(drafts,'create',projectId=p['projectId'],revision=1,name='Bake allowed',allowBaked=True)
    assert d['baked'][0]['layers']==['effect']
    native=json.loads((Path(d['path'])/'draft_content.json').read_text(encoding='utf8'));assert len(native['tracks'])==5
    locked=tmp_path/'locked';locked.mkdir();(locked/'draft.lock').touch()
    with pytest.raises(ValueError,match='LOCKED'):call(drafts,'import_draft',directory=str(locked),expectedHash='0'*64,name='Locked')
    encrypted=tmp_path/'encrypted';encrypted.mkdir();(encrypted/'draft_content.json').write_bytes(b'\xff\x01encrypted')
    with pytest.raises(ValueError,match='ENCRYPTED'):call(drafts,'import_draft',directory=str(encrypted),expectedHash=sha(encrypted/'draft_content.json'),name='Encrypted')


def test_draft_native_video_crop_motion_and_audio_semantics(studio,tmp_path):
    from app.workbench_d.commercial.render import command,binary
    engine,state,p=studio;movie=tmp_path/'video.mov'
    command([binary('ffmpeg'),'-v','error','-y','-f','lavfi','-i','color=c=blue:s=64x64:r=30:d=1','-c:v','png',movie])
    doc=p['document'];doc['assets'].append(dict(id='movie',kind='video',path=str(movie),sha256=sha(movie),license='generated',source='test lavfi'))
    doc['layers'].append(dict(id='motion',kind='video',asset='movie',start=2,end=20,source_start=3,width=32,height=32,crop=[8,8,56,56],track=3,keyframes={'x':[dict(frame=2,value=0),dict(frame=19,value=40)]}))
    p=call(engine,'edit',projectId=p['projectId'],baseRevision=0,document=doc)
    d=call(Drafts(engine),'create',projectId=p['projectId'],revision=1,name='Native motion',allowBaked=False)
    native=json.loads((Path(d['path'])/'draft_content.json').read_text(encoding='utf8'));segment=native['tracks'][-2]['segments'][0]
    assert segment['source_timerange']['start']==100000 and segment['target_timerange']['duration']==600000
    assert segment['common_keyframes'] and segment['volume']==0
    material=next(m for m in native['materials']['videos'] if m['id']==segment['material_id']);assert material['crop']['upper_left_x']==.125
    assert d['baked']==[]


def test_delivery_choice_bound_and_workflow_binding_resets_budget(studio):
    engine,state,p=studio;b=call(engine,'submit',projectId=p['projectId'],revision=0);run(b['buildId'],engine.store)
    delivered=call(engine,'deliver',buildId=b['buildId']);drafts=Drafts(engine)
    choice=call(drafts,'choose_export',deliveryId=delivered['deliveryId'],format='jianying',allowBaked=False)
    draft=call(drafts,'export_draft',choiceId=choice['choiceId'],name='Bound');assert draft['source']['buildId']==b['buildId'] and draft['source']['revision']==0
    Path(delivered['path']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='missing or changed'):call(drafts,'export_draft',choiceId=choice['choiceId'],name='Tampered')
    doc=p['document'];doc['tasks']=[dict(id='generation',kind='generation',provider='old-provider',model='model',output_kind='image',max_cost_micros=100,budget='old-grant')]
    p=call(engine,'edit',projectId=p['projectId'],baseRevision=0,document=doc)
    w=call(state,'archive_workflow',projectId=p['projectId'],revision=1,name='Bindings')
    args=dict(workflowId=w['workflowId']);assert not state.preflight_reuse(args)['compatible']
    p2=call(state,'instantiate_workflow',**args,name='Rebound',bindings=[dict(taskId='generation',provider='new-provider')])
    task=p2['document']['tasks'][0];assert task['provider']=='new-provider' and task['budget'] is None and task['max_cost_micros']==0

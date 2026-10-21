"""No provider network: exact contracts, admission, stop races and revision reuse."""
import copy
import json
import os
import sys
import tempfile
import time
from pathlib import Path
import pytest
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault("VC_DATA",tempfile.mkdtemp(prefix="vc-parity-"))
sys.path.insert(0,str(ROOT/"server"))
from local import db,projects,commands,production
from local.tool_registry import catalog,gateway_tools
from app.workbench_d.commercial import flow
from app.workbench_d.commercial.engine import Engine
from app.workbench_d.commercial.ledger import Ledger
from app.workbench_d.commercial.render import sha
from app.workbench_d.commercial.store import canonical


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setattr(commands,"runtime",lambda doc:{"test":"pinned"})
    monkeypatch.setattr("app.workbench_d.commercial.engine.identity",lambda *a:{"test":"pinned"})
    monkeypatch.setattr(Engine,"launch",lambda *a:None)
    monkeypatch.setattr(Engine,"check",lambda *a:{"valid":True,"executable":True,"limitations":[]})
    pid=projects.create(db.uid(),"parity")["id"]
    doc={"width":64,"height":64,"frames":3,"tasks":[
        {"id":x,"kind":"media","operation":"resize","inputs":[],"output_kind":"image","options":{"tag":x}} for x in "ABC"],
         "layers":[{"id":"layer_"+x,"kind":"image","asset":x,"start":i,"end":i+1,"width":64,"height":64} for i,x in enumerate("ABC")]}
    p=commands.dispatch(pid,"d_create_project",{"commandId":db.uid(),"name":"native","document":doc})
    return pid,p,commands.engine(pid)


def finish(pid,task,e,nodes="ABC",status="succeeded"):
    with e.store.transaction() as c:
        for node in nodes:
            path=e.store.root/(task["id"]+"-"+node+".png")
            Image.new("RGB",(64,64),(len(node)*20,30,50)).save(path)
            value={"path":str(path),"sha256":sha(path),"kind":"image","artifacts":[]}
            c.execute("UPDATE nodes SET status='succeeded',result=? WHERE build=? AND id=?",(canonical(value),task["build_id"],node))
        c.execute("UPDATE builds SET status=? WHERE id=?",(status,task["build_id"]))
    commands.tick_native(task)


def launch(pid,q):
    t=commands.confirm(pid,q["id"],db.uid())
    commands.tick_native(t)
    with db.transaction() as c:return db.get(c,"task",t["id"],pid)


def test_catalog_contracts():
    original=json.loads((ROOT/"docs/evidence/parity/installed-tools.json").read_text(encoding="utf8"))
    core={x["name"]:x for x in catalog() if x["name"].startswith("d_")}
    assert len(original)==41 and len(core)==43
    assert set(core)-{x["name"] for x in original}=={"d_bind_brand_lock","d_review_brand_build"}
    for old in original:
        current=core[old["name"]]
        assert current["description"]==old["description"]
        assert current["inputSchema"]["required"]==old["inputSchema"]["required"]
        assert set(current["inputSchema"]["properties"])==set(old["inputSchema"]["properties"])
    assert len(gateway_tools([{"type":"namespace","name":"mcp__project_d","tools":[{"name":x} for x in core]}]))==43
    assert len(gateway_tools([{"name":"mcp__project_d__"+x} for x in core]))==43
    assert gateway_tools([{"name":"shell"},{"name":"mcp__foreign__d_create_project"}])==[]


def test_heavy_wait_does_not_block_global_stop(native):
    from concurrent.futures import ThreadPoolExecutor
    from app.workbench_d.commercial.resources import slot
    pid,p,e=native
    q=commands.prepare(pid);task=commands.confirm(pid,q['id'],db.uid())
    with slot('other-project-render'):
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(commands.tick_native,task)
            deadline=time.monotonic()+5
            while True:
                with db.transaction() as c:current=db.get(c,'task',task['id'],pid)
                if isinstance(current.get('stage'),dict) and current['stage'].get('stage')=='waiting_local':break
                assert time.monotonic()<deadline
                time.sleep(.02)
            started=time.monotonic()
            commands.stop(pid)
            assert time.monotonic()-started<2
            pending.result(timeout=3)
    with db.transaction() as c:current=db.get(c,'task',task['id'],pid)
    assert current['status']=='cancelled' and not current.get('build_id')


def test_scoped_tools_and_path_traversal(native):
    pid,p,e=native
    other=projects.create(db.uid(),"other")["id"]
    with pytest.raises(ValueError):commands.dispatch(other,"d_inspect_project",{"projectId":p["projectId"]})
    for name,args in [("d_jianying_inspect",{"draftId":"../outside"}),
                      ("d_preflight_reuse",{"workflowId":"../outside"}),
                      ("d_create_project",{"commandId":"bad","document":{"assets":[{"path":str(ROOT/"config.local.json")}]},"name":"bad"})]:
        with pytest.raises(ValueError):commands.dispatch(pid,name,args)
    assert len(commands.dispatch(other,"d_list_projects",{}))==0


def test_no_model_authority_and_expiring_quote(native):
    pid,p,e=native
    result=commands.dispatch(pid,"d_authorize_budget",{"commandId":db.uid(),"projectId":p["projectId"],"revision":0,
                              "account":"invented","currency":"CNY","limitMicros":999999999,"concurrency":100})
    assert result["status"]=="waiting_user"
    assert Ledger(e.store).budgets(p["projectId"],0)==[]
    q=result["quote"]
    with db.transaction() as c:
        saved=db.get(c,"quote",q["id"]);saved["expires"]=0;db.put(c,"quote",q["id"],saved,pid,True)
    with pytest.raises(ValueError,match="过期"):commands.confirm(pid,q["id"],db.uid())


def test_stop_edit_B_reuse_A_C(native):
    pid,p,e=native
    q=commands.prepare(pid);t=launch(pid,q)
    finish(pid,t,e,nodes="AC",status="running")
    stopped=commands.stop(pid)
    assert stopped["new_work_blocked"]
    doc=copy.deepcopy(p["document"]);doc["tasks"][1]["options"]["tag"]="new B"
    edited=commands.dispatch(pid,"d_edit_project",{"commandId":db.uid(),"projectId":p["projectId"],"baseRevision":0,"document":doc})
    q2=commands.prepare(pid)
    assert q2["reused_nodes"]==["A","C"] and q2["new_nodes"]==["B"]
    assert q2["epoch"]==1 and edited["authorRevision"]==1
    new=launch(pid,q2)
    b=e.store.build(new["build_id"])
    assert {n["id"] for n in b["nodes"] if n["status"]=="succeeded"}=={"A","C"}
    assert e.store.project(p["projectId"],0)["document"]["tasks"][1]["options"]["tag"]=="B"


def test_completed_replan_B_C_force_unchanged_and_subtitles(native):
    pid,p,e=native
    t=launch(pid,commands.prepare(pid));finish(pid,t,e)
    doc=copy.deepcopy(p["document"])
    for task in doc["tasks"][1:]:task["options"]["tag"]="new "+task["id"]
    p=commands.dispatch(pid,"d_edit_project",{"commandId":db.uid(),"projectId":p["projectId"],"baseRevision":0,"document":doc})
    q=commands.prepare(pid)
    assert q["reused_nodes"]==["A"] and q["new_nodes"]==["B","C"]
    t2=launch(pid,q);finish(pid,t2,e)
    force=commands.prepare(pid,["B"])
    assert force["new_nodes"]==["B"] and force["reused_nodes"]==["A","C"]
    t3=launch(pid,force);finish(pid,t3,e)
    # Text/layout-only revision keeps task inputs exactly identical.
    changed=copy.deepcopy(p["document"]);changed["layers"][0]["x"]=1
    commands.dispatch(pid,"d_edit_project",{"commandId":db.uid(),"projectId":p["projectId"],"baseRevision":1,"document":changed})
    local=commands.prepare(pid)
    assert local["new_nodes"]==[] and local["paid_tasks"]==0
    assert local["graph"][-1]["id"]=="$render"
    assert e.store.build(t["build_id"])["revision"]==0


def test_duplicate_confirm_and_stale_quote(native):
    pid,p,e=native
    q=commands.prepare(pid)
    a=commands.confirm(pid,q["id"],"confirm-"+pid)
    assert commands.confirm(pid,q["id"],"confirm-"+pid)["id"]==a["id"]
    assert commands.confirm(pid,q["id"],db.uid())["id"]==a["id"]
    commands.stop(pid)
    commands.tick_native(a)
    with db.transaction() as c:assert db.get(c,"task",a["id"])["build_id"] is None
    assert flow.state(e.store)["stopped"]


def test_stop_fences_provider_claim_and_preserves_unknown(native):
    pid,p,e=native
    t=launch(pid,commands.prepare(pid));l=Ledger(e.store)
    l.authorize({"commandId":db.uid(),"projectId":p["projectId"],"revision":0,"account":"fake","currency":"CNY","limitMicros":10,"concurrency":3})
    build={"id":t["build_id"],"project":p["projectId"],"revision":0}
    before=l.reserve(build,{"id":"before","max_cost_micros":1},"fake",{},"CNY")
    after=l.reserve(build,{"id":"after","max_cost_micros":1},"fake",{},"CNY")
    assert l.claim_dispatch(before["id"])
    commands.stop(pid)
    assert not l.claim_dispatch(after["id"])
    rows={r["id"]:r for r in l.inspect(t["build_id"])}
    assert rows[before["id"]]["state"]=="submitting"
    assert rows[after["id"]]["state"]=="prepared"
    assert flow.state(Engine(e.store.root.parent).store)["stopped"]
    with pytest.raises(ValueError):e.submit({"commandId":db.uid(),"projectId":p["projectId"],"revision":0})


def test_stop_is_idempotent_and_project_local(native,monkeypatch):
    pid,p,e=native
    other=projects.create(db.uid(),"other")["id"]
    other_engine=commands.engine(other);flow.initialize(other_engine.store)
    first=commands.stop(pid);second=commands.stop(pid)
    assert first["epoch"]==second["epoch"]==1
    assert not flow.state(other_engine.store)["stopped"]


def test_force_propagates_dependencies_and_incomplete_is_not_free(native):
    pid,p,e=native
    t=launch(pid,commands.prepare(pid));finish(pid,t,e,nodes="A",status="running")
    commands.stop(pid)
    q=commands.prepare(pid)
    assert q["reused_nodes"]==["A"] and q["new_nodes"]==["B","C"]
    doc=copy.deepcopy(p["document"]);doc["tasks"][2]["depends_on"]=["B"]
    commands.dispatch(pid,"d_edit_project",{"commandId":db.uid(),"projectId":p["projectId"],"baseRevision":0,"document":doc})
    q=commands.prepare(pid,["B"])
    assert q["invalidated"]==["B","C"]


def test_terminal_inbox_deduplicates_and_restart_does_not_replay(native):
    pid,p,e=native
    t=launch(pid,commands.prepare(pid));finish(pid,t,e)
    commands.tick_native(t)
    with db.transaction() as c:
        rows=[r for r in db.all(c,"agent_inbox",pid) if r["id"]=="terminal:"+t["id"]]
        assert len(rows)==1
        row=rows[0];row["status"]="dispatching";db.put(c,"agent_inbox",row["id"],row,pid,True)
    from local.coordinator import recover
    recover()
    with db.transaction() as c:assert db.get(c,"agent_inbox",row["id"])["status"]=="needs_attention"


def test_cancel_tool_is_global_and_cannot_cancel_other_project(native):
    pid,p,e=native
    first=launch(pid,commands.prepare(pid))
    other=projects.create(db.uid(),"other")["id"]
    with pytest.raises(ValueError):commands.dispatch(other,"d_cancel_build",{"commandId":db.uid(),"buildId":first["build_id"]})
    result=commands.dispatch(pid,"d_cancel_build",{"commandId":db.uid(),"buildId":first["build_id"]})
    assert result["stopped"] and first["build_id"] in result["builds"]


def test_stop_does_not_wait_for_long_core_export_transaction(native):
    import threading
    pid,p,e=native
    launch(pid,commands.prepare(pid))
    ready=threading.Event();release=threading.Event()
    def export():
        with e.store.transaction() as c:
            c.execute("UPDATE projects SET name=name")
            ready.set();release.wait(5)
    thread=threading.Thread(target=export);thread.start();assert ready.wait(2)
    try:
        started=time.monotonic();result=commands.stop(pid)
        assert result["stopped"] and time.monotonic()-started<1
    finally:
        release.set();thread.join()


def test_provider_configuration_restart_does_not_rewrite_identity(tmp_path,monkeypatch):
    monkeypatch.setattr(production,"DATA",tmp_path)
    monkeypatch.setitem(production.CONFIG,"media_profile","selected")
    endpoint={"modelId":"unchanged-model","baseUrl":"https://example.invalid/api/v3"}
    monkeypatch.setattr(production,"media_endpoint",lambda:endpoint)
    monkeypatch.setattr(production,"media_key",lambda:"test-fake")
    monkeypatch.setenv("D_PROVIDERS","")
    monkeypatch.setenv("VC_MEDIA_KEY","")
    production.setup_media()
    path=tmp_path/"providers.json";before=path.read_bytes()
    production.setup_media()
    assert path.read_bytes()==before
    endpoint["modelId"]="different"
    with pytest.raises(ValueError,match="冻结"):production.setup_media()
    assert path.read_bytes()==before


def test_stale_revision_and_configuration_rejected(native,monkeypatch):
    pid,p,e=native
    q=commands.prepare(pid)
    monkeypatch.setattr(commands,"runtime",lambda doc:{"test":"changed"})
    with pytest.raises(ValueError,match="配置"):commands.confirm(pid,q["id"],db.uid())
    monkeypatch.setattr(commands,"runtime",lambda doc:{"test":"pinned"})
    commands.dispatch(pid,"d_edit_project",{"commandId":db.uid(),"projectId":p["projectId"],"baseRevision":0,"document":p["document"]})
    with pytest.raises(ValueError,match="修订|替代"):commands.confirm(pid,q["id"],db.uid())


def test_gateway_preserves_mcp_namespace_in_both_protocols():
    from local.tool_registry import gateway_contract,restore_tool_calls
    wire,aliases=gateway_contract([{"type":"namespace","name":"mcp__project_d","tools":[{"name":"d_create_project"}]}])
    assert wire[0]["name"]=="mcp__project_d__d_create_project"
    returned=restore_tool_calls({"item":{"type":"function_call","name":wire[0]["name"],"arguments":"{}"}},aliases)
    assert returned["item"]["namespace"]=="mcp__project_d"
    assert returned["item"]["name"]=="d_create_project"


def test_browser_only_visibility_and_user_path_grants(native):
    from local.main import app,CSRF
    from fastapi.testclient import TestClient
    pid,p,e=native
    args={"commandId":db.uid(),"projectId":p["projectId"],"revision":0,"documentHash":p["sha256"],"viewVersion":0,"session":"fixture-browser","visibility":"visible"}
    with pytest.raises(ValueError,match="VISIBLE"):commands.dispatch(pid,"d_record_view",args)
    client=TestClient(app,base_url="http://127.0.0.1:8765")
    result=client.post(f"/api/projects/{pid}/native/visible",headers={"x-vc-token":CSRF},json={"command_id":db.uid(),"revision":0,"document_hash":p["sha256"],"session":"fixture-browser"})
    assert result.status_code==200
    status=commands.dispatch(pid,"d_canvas_status",{"projectId":p["projectId"],"revision":0})
    assert len(status["visibleReceipts"])==1


def test_retry_returns_new_user_quote_and_preserves_ambiguous_request(native):
    pid,p,e=native
    t=launch(pid,commands.prepare(pid));commands.stop(pid)
    result=commands.dispatch(pid,'d_retry_build',{'commandId':db.uid(),'buildId':t['build_id']})
    assert result['status']=='waiting_user' and result['quote']['new_nodes']==['A','B','C']
    assert flow.state(e.store)['stopped']
    assert e.store.build(t['build_id'])['status']=='queued'


def test_explicit_old_task_adoption_preserves_source(native):
    pid,p,e=native
    t=launch(pid,commands.prepare(pid));finish(pid,t,e)
    with db.transaction() as c:
        web=db.get(c,'project',pid);web.pop('native_project');web.pop('execution_mode')
        db.put(c,'project',pid,web,pid,True)
    adopted=commands.dispatch(pid,'adopt_legacy_revision',{'task_id':t['id']})
    assert adopted['projectId']!=p['projectId'] and adopted['sha256']==p['sha256']
    assert e.store.project(p['projectId'])['authorRevision']==0
    assert commands.adopt_legacy(pid,t['id'])['projectId']==adopted['projectId']
    other=projects.create(db.uid(),'other')['id']
    with pytest.raises(ValueError):commands.adopt_legacy(other,t['id'])


def test_legacy_workspace_grant_is_exact_and_source_stays_readonly(tmp_path,monkeypatch):
    import sqlite3
    source=tmp_path/'legacy.sqlite'
    composition={'width':64,'height':64,'duration':1,'layers':[{'id':'bg','kind':'rect','start':0,'end':1,'width':64,'height':64}]}
    with sqlite3.connect(source) as c:
        c.executescript('CREATE TABLE template_workspaces(id,title,revision,active_run_id,document,project_id); CREATE TABLE assets(project_id);')
        c.execute('INSERT INTO template_workspaces VALUES(?,?,?,?,?,?)',('legacy','fixture',1,None,json.dumps({'specs':{'composition':composition}}),'old-project'))
    monkeypatch.setenv('D_LEGACY_DATABASE',str(source));monkeypatch.setenv('D_LEGACY_ASSETS',str(tmp_path))
    before=source.read_bytes();pid=projects.create(db.uid(),'legacy fixture')['id']
    args={'commandId':db.uid(),'workspace_id':'legacy','expected_revision':1}
    with pytest.raises(ValueError,match='WORKSPACE_IMPORT'):commands.dispatch(pid,'d_transfer_workspace',args)
    with db.transaction() as c:commands.grant_workspace(c,pid,'legacy',1,db.uid())
    result=commands.dispatch(pid,'d_transfer_workspace',args)
    assert result['source']['revision']==1 and result['document']['layers'][0]['id']=='bg'
    assert commands.dispatch(pid,'d_transfer_workspace',args)['projectId']==result['projectId']
    assert source.read_bytes()==before
    other=projects.create(db.uid(),'isolated')['id']
    with pytest.raises(ValueError,match='WORKSPACE_IMPORT'):commands.dispatch(other,'d_transfer_workspace',args)


def test_late_old_output_does_not_replace_new_attempt(native):
    pid,p,e=native
    old=launch(pid,commands.prepare(pid));commands.stop(pid)
    fresh=launch(pid,commands.prepare(pid,['B']));finish(pid,fresh,e)
    finish(pid,old,e)
    q=commands.prepare(pid)
    with db.transaction() as c:frozen=db.get(c,'quote',q['id'],pid)
    assert all(fresh['id'] in value['path'] for value in frozen['reuse'].values())


def test_agent_restart_reconciles_correlated_completed_turn_without_replay(native,monkeypatch):
    import asyncio
    from local import coordinator,bridge
    pid,p,e=native
    with db.transaction() as c:
        item=commands.enqueue(c,pid,'recovery-fixture-'+pid,'test',0)
        item.update(status='dispatched',thread_id='original-thread',client_id='stable-user-id')
        db.put(c,'agent_inbox',item['id'],item,pid,True)
    calls=[]
    class Runner:
        async def start(self):calls.append('start-no-model')
        async def rpc(self,method,args):
            calls.append(method)
            return {'thread':{'turns':[{'id':'persisted-turn','status':'completed','items':[
                {'id':'u','type':'userMessage','clientId':'stable-user-id'},
                {'id':'a','type':'agentMessage','text':'Recovered completion'}]}]}}
    monkeypatch.setattr(bridge,'runner',lambda pid:Runner())
    coordinator.recover()
    asyncio.run(coordinator.reconcile(item))
    asyncio.run(coordinator.reconcile(item))
    with db.transaction() as c:
        assert db.get(c,'agent_inbox',item['id'],pid)['status']=='done'
        assert sum(m['text']=='Recovered completion' for m in db.all(c,'message',pid))==1
    assert 'turn/start' not in calls


def test_reconcile_tool_attaches_receipt_without_dispatch(native):
    pid,p,e=native;t=launch(pid,commands.prepare(pid));ledger=Ledger(e.store)
    ledger.authorize({'commandId':db.uid(),'projectId':p['projectId'],'revision':0,'account':'fake','currency':'CNY','limitMicros':2,'concurrency':1})
    row=ledger.reserve({'id':t['build_id'],'project':p['projectId'],'revision':0},{'id':'B','max_cost_micros':1},'fake',{},'CNY')
    assert ledger.claim_dispatch(row['id'])
    args={'commandId':db.uid(),'requestId':row['id'],'remoteId':'provider-confirmed'}
    result=commands.dispatch(pid,'d_reconcile_request',args)
    assert result['state']=='accepted' and commands.dispatch(pid,'d_reconcile_request',args)==result
    assert not ledger.claim_dispatch(row['id'])
    assert len(ledger.inspect(t['build_id']))==1


def test_cross_process_stop_dispatch_race(native,tmp_path):
    import subprocess
    pid,p,e=native;t=launch(pid,commands.prepare(pid));ledger=Ledger(e.store)
    ledger.authorize({'commandId':db.uid(),'projectId':p['projectId'],'revision':0,'account':'fake','currency':'CNY','limitMicros':2,'concurrency':2})
    build={'id':t['build_id'],'project':p['projectId'],'revision':0}
    row=ledger.reserve(build,{'id':'race','max_cost_micros':1},'fake',{},'CNY')
    later=ledger.reserve(build,{'id':'after','max_cost_micros':1},'fake',{},'CNY')
    script=tmp_path/'race.py'
    script.write_text('''
import sys,time,json
from pathlib import Path
from app.workbench_d.commercial.engine import Engine
from app.workbench_d.commercial.ledger import Ledger
from app.workbench_d.commercial import flow
e=Engine(sys.argv[1]);gate=Path(sys.argv[3])
while not gate.exists():time.sleep(.005)
result=flow.stop(e.store) if sys.argv[2]=='stop' else Ledger(e.store).claim_dispatch(sys.argv[4])
print(json.dumps(result))
''',encoding='utf8')
    env={**os.environ,'PYTHONPATH':str(ROOT/'server')}
    gate=tmp_path/'go'
    processes=[subprocess.Popen([sys.executable,str(script),str(e.store.root.parent),action,str(gate),row['id']],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for action in ['stop','claim']]
    gate.write_text('go')
    results=[]
    for process in processes:
        out,err=process.communicate(timeout=15)
        assert process.returncode==0,err.decode()
        results.append(json.loads(out))
    assert results[0]['stopped']
    assert not ledger.claim_dispatch(later['id'])
    states={r['id']:r['state'] for r in ledger.inspect(t['build_id'])}
    assert states[row['id']]==('submitting' if results[1] else 'prepared')
    assert states[later['id']]=='prepared'


def test_queued_build_stops_without_ever_launching(native):
    pid,p,e=native;t=launch(pid,commands.prepare(pid))
    commands.stop(pid);commands.tick_native(t)
    assert e.store.build(t['build_id'])['status']=='cancelled'
    with db.transaction() as c:assert db.get(c,'task',t['id'],pid)['status']=='cancelled'
    with pytest.raises(ValueError,match='原生'):production.quote(pid,0)

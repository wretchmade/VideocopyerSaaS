"""Project command/authorization boundary shared by chat, UI, MCP and worker."""
import copy
import json
import re
import time
import zipfile
from pathlib import Path
from . import db
from .config import DATA, ROOT, CONFIG, contained
from app.workbench_d.commercial import api as core_api, flow
from app.workbench_d.commercial.engine import Engine
from app.workbench_d.commercial.render import identity, sha
from .tool_registry import catalog, canonical_name,validate_arguments

SAFE_ID = re.compile(r"^[A-Za-z0-9_:-]{1,128}$")
IDENTITIES = {"projectId", "buildId", "reviewId", "feedbackId", "workflowId", "draftId", "choiceId", "deliveryId", "requestId"}
SKILL = ROOT / "server/resources/workbench-d"


def engine(pid):
    with db.transaction() as c:
        db.get(c, "project", pid)
    from .production import engine as scoped_engine
    return scoped_engine(pid)


def bind(c, pid, result):
    p = db.get(c, "project", pid)
    p.update(native_project=result["projectId"], native_revision=result["authorRevision"], execution_mode="native")
    db.put(c, "project", pid, p, pid, True)
    for quote in db.all(c,"quote",pid):
        if quote['status']=='pending' and (quote.get('core_project')!=result['projectId'] or quote['revision']!=result['authorRevision']):
            quote['status']='superseded';db.put(c,'quote',quote['id'],quote,pid,True)
    db.emit(c, pid, "native/revision", {"projectId": result["projectId"], "revision": result["authorRevision"], "documentHash": result["sha256"]})


def resolve_paths(c, pid, value):
    """Never make a client path an authority. Core-owned snapshots and uploads only."""
    if isinstance(value, list):
        return [resolve_paths(c, pid, x) for x in value]
    if not isinstance(value, dict):
        return value
    out = {}
    root = (DATA / "projects" / pid).resolve()
    for key, item in value.items():
        if key in IDENTITIES and (not isinstance(item, str) or not SAFE_ID.fullmatch(item)):
            raise ValueError("Invalid project-scoped identity: " + key)
        if (key=="directory" or key=="path" and ("sha256" in value or value.get("kind") in {"font","image","video","audio","transcript"})) and isinstance(item, str):
            if item=="resource:font":
                item=CONFIG.get("font","C:/Windows/Fonts/msyh.ttc")
            if item.startswith("file:"):
                item = db.get(c, "file", item[5:], pid)["path"]
            path = Path(item).resolve()
            grants = db.all(c, "path_grant", pid)
            if not path.is_relative_to(root) and not any(path == Path(g["path"]).resolve() or g['purpose']=='import_draft' and path.is_relative_to(Path(g["path"]).resolve()) for g in grants):
                # Explicit configured local font is part of the pinned runtime.
                font = Path(CONFIG.get("font", "C:/Windows/Fonts/msyh.ttc")).resolve()
                if key != "path" or path != font or value.get("kind") != "font":
                    raise ValueError("路径需属于此项目上传区或显式批准的本地目录")
            out[key] = str(path)
        else:
            out[key] = resolve_paths(c, pid, item)
    return out


def stop(pid, command=None):
    e = engine(pid)
    with db.transaction() as c:
        def action():
            result = flow.stop(e.store)
            for task in db.all(c, "task", pid):
                if task["status"] in {"queued", "running", "reconciling"}:
                    task.update(stop_requested=True, status="cancelled" if not task.get("build_id") else "stopping")
                    db.put(c, "task", task["id"], task, pid, True)
            db.emit(c, pid, "flow/stopped", result)
            return {**result, "new_work_blocked": True, "remote": "已越过提交边界的远端请求保留原账本，待核对"}
        return db.once(c, command, {"op": "global-stop", "project": pid}, action) if command else action()


def grant_local(c,pid,path,purpose,command):
    if purpose not in {'import_draft','export_draft'}:raise ValueError('未知本地目录用途')
    path=Path(path).expanduser().resolve()
    if path==Path(path.anchor):raise ValueError('请选择具体工程目录')
    if purpose=='export_draft' and path.exists():raise ValueError('安装目标必须是尚不存在的新目录')
    if purpose=='import_draft' and not path.is_dir():raise ValueError('导入目录不存在')
    db.get(c,'project',pid)
    return db.once(c,command,{'op':'local-access','project':pid,'path':str(path),'purpose':purpose},
                   lambda:db.put(c,'path_grant',db.uid(),{'project':pid,'path':str(path),'purpose':purpose},pid))

def grant_workspace(c,pid,workspace_id,expected_revision,command):
    import os
    from app.workbench_d.commercial.bridge import read_workspace
    db.get(c,'project',pid)
    def authorize():
        source=read_workspace(workspace_id,expected_revision)
        grant={'project':pid,'workspace_id':workspace_id,'expected_revision':expected_revision,
               'database':source['source']['database'],'assets':str(Path(os.environ['D_LEGACY_ASSETS']).resolve()),
               'document_hash':source['source']['document_sha256']}
        return db.put(c,'workspace_grant',db.uid(),grant,pid)
    return db.once(c,command,{'op':'workspace-access','project':pid,'workspace':workspace_id,'revision':expected_revision},authorize)

def adopt_legacy(pid,task_id):
    e=engine(pid)
    with db.transaction() as c:
        task=db.get(c,'task',task_id,pid);p=db.get(c,'project',pid)
        if not task.get('build_id'):raise ValueError('所选旧任务尚无可追溯的 D 构建')
        if p.get('native_project'):
            if p.get('adopted_task')==task_id:return e.store.project(p['native_project'])
            raise ValueError('此项目已有原生工程，请编辑当前修订；旧任务仍可检查和下载')
        built=e.store.build(task['build_id'])
        source=e.store.project(built['project'],built['revision'])
        adopted=e.create({'commandId':'adopt-'+db.digest({'project':pid,'task':task_id})[:40],
                         'name':source['name']+' · Web 编辑','document':source['document']})
        p.update(adopted_task=task_id);db.put(c,'project',pid,p,pid,True)
        bind(c,pid,adopted)
        return {**adopted,'source':{'taskId':task_id,'buildId':task['build_id'],'documentHash':source['sha256']}}


def runtime(document):
    return identity(any(t["kind"] == "capture" for t in document["tasks"]))


def task_keys(document, runtime_id):
    """Content identity includes ordered inputs/roles and all upstream task identities."""
    assets = {a["id"]: {"sha256": a["sha256"], "kind": a["kind"]} for a in document["assets"]}
    pending = {t["id"]: t for t in document["tasks"]}
    keys = {}
    while pending:
        ready = [t for t in pending.values() if set(t["depends_on"]) <= keys.keys()]
        if not ready:
            raise ValueError("Invalid dependency graph")
        for task in ready:
            spec = {k: v for k, v in task.items() if k not in {"budget", "max_cost_micros"}}
            keys[task["id"]] = db.digest({"task": spec, "inputs": [assets.get(i) or keys[i] for i in task["inputs"]],
                                         "dependencies": [keys[d] for d in task["depends_on"]], "runtime": runtime_id})
            del pending[task["id"]]
    return keys


def reusable(c, pid, document, keys, forced):
    invalid = set(forced)
    changed = True
    while changed:
        before = len(invalid)
        for task in document["tasks"]:
            if set(task["depends_on"]) & invalid:
                invalid.add(task["id"])
        changed = before != len(invalid)
    reuse = {}
    for row in sorted(c if isinstance(c,list) else db.all(c, "node_output", pid), key=lambda r: r.get("attempt_created", 0), reverse=True):
        node = row["node"]
        if node in reuse or node in invalid or row["key"] != keys.get(node):
            continue
        value = row["result"]
        path = Path(value["path"])
        if path.is_file() and sha(path) == value["sha256"] and all(Path(a["path"]).is_file() and sha(Path(a["path"])) == a["sha256"] for a in value.get("artifacts", [])):
            if value['kind'] in {'video','audio'} and not enough_media(document,node,value):
                invalid.add(node)
                continue
            reuse[node] = value
    changed=True
    while changed:
        before=len(invalid)
        for task in document['tasks']:
            if set(task['depends_on'])&invalid:invalid.add(task['id'])
        changed=len(invalid)!=before
    for key in invalid:reuse.pop(key,None)
    return reuse, invalid


def required_seconds(document,reference):
    frames=[l.get('source_start',0)+l['end']-l['start'] for l in document['layers'] if l.get('asset')==reference]
    frames += [a.get('source_start',0)+a['end']-a['start'] for a in document['audio'] if a['asset']==reference]
    return max(frames,default=0)*document['fps']['den']/document['fps']['num']


def enough_media(document,reference,value):
    from app.workbench_d.commercial.render import probe
    required=required_seconds(document,reference)
    if not required:return True
    media=probe(value['path'])
    return float(media.get('format',{}).get('duration',0))+.001>=required


def projection(doc,reuse,invalid):
    graph=[{'id':a['id'],'kind':a['kind'],'depends_on':[],'state':'reuse'} for a in doc['assets']]
    graph += [{"id":t["id"],"kind":t["kind"],"depends_on":list(dict.fromkeys(t["depends_on"]+t["inputs"])),
               "state":"reuse" if t["id"] in reuse else "redo" if t["id"] in invalid else "planned"} for t in doc['tasks']]
    graph += [{"id":"layer:"+l['id'],"kind":l['kind'],"depends_on":[ref for ref in [l.get('asset'),l.get('transcript'),*l.get('fonts',[])] if ref],
               "start":l['start'],"end":l['end'],"state":"planned"} for l in doc['layers']]
    graph += [{"id":"audio:"+str(i),"kind":"audio","depends_on":[a['asset']],"start":a['start'],"end":a['end'],"state":"planned"} for i,a in enumerate(doc['audio'])]
    graph += [{"id":"transition:"+str(i),"kind":t['kind'],"depends_on":["layer:"+t['source'],"layer:"+t['target']],"state":"planned"} for i,t in enumerate(doc['transitions'])]
    graph.append({"id":"$render","kind":"render","depends_on":[n['id'] for n in graph],"state":"planned"})
    return graph


def public_quote(q):
    private = {"document", "runtime", "reuse", "keys", "accounts"}
    return {k: v for k, v in q.items() if k not in private}


def prepare(pid, regenerate_nodes=None):
    e = engine(pid)
    flow.initialize(e.store)
    with db.transaction() as c:
        current_project = db.get(c, "project", pid)
        if current_project.get("template_instance") and current_project.get("execution_mode") != "native":
            from app.creative_templates.contracts import fail
            fail("TEMPLATE_VALIDATION_REQUIRED", "/plan", "模板实例需先编译为原生 D 工程")
    if current_project.get("execution_mode") != "native":
        from .production import quote
        return quote(pid, current_project["revision"])
    with db.transaction() as c:
        p = db.get(c, "project", pid)
        source = e.store.project(p["native_project"])
        from . import templates
        template_binding = templates.gate(c, pid, source)
        outputs=db.all(c,'node_output',pid)
    # Resource waiting, full media probes and font layout never own the Web write lock.
    fence = flow.state(e.store)
    doc = source["document"]
    checked = e.check({"projectId": source["projectId"], "revision": source["authorRevision"]})
    if not checked["executable"]:raise ValueError("; ".join(checked["limitations"]))
    rt = runtime(doc);keys = task_keys(doc, rt)
    for asset in doc['assets']:
        if asset['kind'] in {'video','audio'} and not enough_media(doc,asset['id'],asset):
            raise ValueError('已有素材 '+asset['id']+' 时长不足，请调整裁切/时间槽或补充素材后重新报价')
    for task in doc['tasks']:
        duration=task['options'].get('duration')
        if task['kind']=='generation' and isinstance(duration,(int,float)) and duration+.001<required_seconds(doc,task['id']):
            raise ValueError('生成任务 '+task['id']+' 的声明时长不足以覆盖时间线，请先调整生成时长或时间槽')
    previous=e.store.project(source['projectId'],source['authorRevision']-1)['document'] if source['authorRevision']>0 else None
    prior_keys=task_keys(previous,rt) if previous else {}
    edited={key for key in keys if key in prior_keys and keys[key]!=prior_keys[key]}
    force = sorted(set(regenerate_nodes or []))
    if set(force) - keys.keys():raise ValueError("重新生成范围包含不存在的任务节点")
    reuse, invalid = reusable(outputs, pid, doc, keys, force)
    invalid |= edited-set(reuse)
    pending = [t for t in doc["tasks"] if t["id"] not in reuse]
    from app.workbench_d.commercial.providers import quote_task
    from app.workbench_d.commercial.render_plan import choose
    from app.workbench_d.commercial.schema import upgrade
    render_plan=choose(upgrade(doc))
    prices = [quote_task(t) for t in pending if t["kind"] == "generation"]
    if any(not x["ready"] or x["currency"] != "CNY" or x["maximumReservedMicros"] < x["quote"]["upperMicros"] for x in prices):
        raise ValueError("需要有效的 CNY 报价和足够的单任务费用上限")
    expires = min([time.time() + 900] + [x["quote"]["expires"] for x in prices])
    graph = projection(doc,reuse,invalid)
    with db.transaction() as c:
        p=db.get(c,'project',pid)
        if p['native_project']!=source['projectId'] or e.store.project(source['projectId'])['sha256']!=source['sha256']:
            raise ValueError('工程在报价校验期间已更新，请重新报价')
        if flow.state(e.store)['epoch']!=fence['epoch']:raise ValueError('停止状态已变化，请重新报价')
        if templates.gate(c,pid,source) != template_binding:
            raise ValueError('模板实例在报价期间已变化')
        costs = db.all(c, "usage", pid)
        q = {"id": db.uid(), "project": pid, "mode": "native", "core_project": source["projectId"],
             "revision": source["authorRevision"], "document_hash": source["sha256"], "document": doc,
             "runtime": rt, "render_plan":render_plan,"keys": keys, "reuse": reuse, "regenerate_nodes": force, "invalidated": sorted(invalid),
             "changed_nodes":sorted(edited),"timeline_policy":"保留工程明确写出的帧区间；顺延必须编辑受影响图层，整片重新合成",
             "epoch": fence["epoch"], "expires": expires, "status": "pending", "graph": graph,
             "new_nodes": [t["id"] for t in pending], "reused_nodes": sorted(reuse), "accounts": prices,
             "maximum_micros": sum(t["max_cost_micros"] for t in pending if t["kind"] == "generation"),
             "paid_tasks": len(prices), "currency": "CNY", "duration": doc["frames"] * doc["fps"]["den"] / doc["fps"]["num"],
             "frames": doc["frames"], "baked": [], "bill_status": "本轮增量预留；既有请求费用未自动抵扣，外部账单待核对",
             "planning_reserved_micros": sum(r["reserved_micros"] for r in costs if r["category"] == "planning" and r["state"] != "released"),
             "prior_media_reserved_micros": sum(r["reserved_micros"] for r in costs if r["category"] == "media" and r["state"] != "released")}
        if template_binding:q["template_binding"] = template_binding
        q["quote_hash"] = db.digest({k: v for k, v in q.items() if k not in {"id", "expires", "status"}})
        for prior in db.all(c, "quote", pid):
            if prior["status"] == "pending":
                if not force and prior["quote_hash"] == q["quote_hash"] and prior["expires"] > time.time():
                    return public_quote(prior)
                prior["status"] = "superseded"
                db.put(c, "quote", prior["id"], prior, pid, True)
        db.put(c, "quote", q["id"], q, pid)
        db.emit(c, pid, "quote/prepared", public_quote(q))
        return public_quote(q)


def confirm(pid, qid, command, source="ui"):
    """Only HTTP user input calls this; never a model-visible tool."""
    e = engine(pid)
    with db.transaction() as c:
        def action():
            q = db.get(c, "quote", qid, pid)
            if q["status"] == "authorized":
                return db.get(c, "task", q["task_id"], pid)
            current = e.store.project(q["core_project"])
            if q["status"] != "pending" or q["expires"] <= time.time():
                raise ValueError("报价已过期或被替代，请重新规划和报价")
            if current["authorRevision"] != q["revision"] or current["sha256"] != q["document_hash"]:
                raise ValueError("工程修订已变化，请重新报价")
            from . import templates
            if templates.gate(c,pid,current,q.get("template_binding")) != q.get("template_binding"):
                raise ValueError("报价缺少当前模板绑定，请重新报价")
            fence = flow.state(e.store)
            if not fence or fence["epoch"] != q["epoch"]:
                raise ValueError("停止状态已变化，请重新报价确认")
            if runtime(q["document"]) != q["runtime"]:
                raise ValueError("配置或实现已变化，请重新报价")
            for asset in q["document"]["assets"]:
                if sha(Path(asset["path"])) != asset["sha256"]:
                    raise ValueError("输入素材已变化")
            for value in q["reuse"].values():
                if sha(Path(value["path"])) != value["sha256"]:
                    raise ValueError("复用素材已变化")
            tid = db.uid()
            if q["maximum_micros"]:
                db.reserve(c, tid, pid, q["maximum_micros"], "media", {"quote": qid, "hash": q["quote_hash"]})
            task = {"id": tid, "project": pid, "revision": q["revision"], "native": True,
                    "core_project": q["core_project"], "core_revision": q["revision"], "quote_id": qid,
                    "document": q["document"], "document_hash": q["document_hash"], "epoch": q["epoch"],
                    "execution": {"epoch": q["epoch"], "runtime": q["runtime"], "reuse": q["reuse"],
                                  "attempt": qid,"render_plan":q.get('render_plan')}, "node_keys": q["keys"], "accounts": q["accounts"],
                    "status": "queued", "stage": "等待执行", "nodes": [], "build_id": None,
                    "created": time.time(), "authorization": {"source": source, "command": command, "quote_hash": q["quote_hash"]}}
            if q.get("template_binding"):task["template_binding"] = q["template_binding"]
            db.put(c, "task", tid, task, pid)
            q.update(status="authorized", task_id=tid)
            db.put(c, "quote", qid, q, pid, True)
            db.emit(c, pid, "task/queued", {"id": tid, "revision": q["revision"]})
            enqueue(c, pid, "authorization:" + qid, "用户已确认报价。执行已排队，完成后检查结果并继续审片与交付。", q["epoch"])
            return task
        return db.once(c, command, {"op": "confirm", "project": pid, "quote": qid}, action)


def enqueue(c, pid, key, text, epoch):
    try:
        return db.get(c, "agent_inbox", key, pid)
    except ValueError:
        return db.put(c, "agent_inbox", key, {"id": key, "project": pid, "text": text, "epoch": epoch, "status": "pending"}, pid)


def user_intent(c,pid,text):
    if re.search(r'(?:^|[，。！？\s])(?:请)?(?:全部先停|全局停止|先停下来|停止制作|暂停制作|停止当前流程|全部停止|先停)(?:[，。！？\s]|$)',text):
        return {'op':'stop'}
    match=re.fullmatch(r'确认报价\s+([a-f0-9]{32})',text)
    if match or text in {'确认制作','确认并开始','确认当前报价'}:
        pending=[q for q in db.all(c,'quote',pid) if q['status']=='pending']
        qid=match[1] if match else pending[0]['id'] if len(pending)==1 else None
        if not qid:raise ValueError('请指定唯一待确认报价 ID')
        db.get(c,'quote',qid,pid)
        return {'op':'confirm','quote':qid}
    return None


def apply_user_intent(item):
    if not item.get('intent') or item.get('intent_processed'):return
    pid=item['project'];intent=item['intent'];command='user-intent-'+db.digest(item['id'])[:40]
    if intent['op']=='stop':stop(pid,command)
    elif intent['op']=='confirm':
        with db.transaction() as c:q=db.get(c,'quote',intent['quote'],pid)
        if q['mode']=='native':confirm(pid,q['id'],command,'user-message')
        else:
            from .production import submit
            submit(pid,q['revision'],command,q['quote_hash'])
    with db.transaction() as c:
        current=db.get(c,'agent_inbox',item['id'],pid)
        current['intent_processed']=True;db.put(c,'agent_inbox',item['id'],current,pid,True)


def expose_file(c,pid,value,generated_by=None):
    """Attach a core result to the existing project file service without copying bytes."""
    if not isinstance(value,dict) or not value.get('path') or not value.get('sha256'):return value
    path=Path(value['path']).resolve()
    if not path.is_relative_to((DATA/'projects'/pid).resolve()) or not path.is_file():return value
    kinds={'.png':'image','.jpg':'image','.jpeg':'image','.webp':'image','.mp4':'video','.mov':'video','.wav':'audio','.mp3':'audio','.json':'text','.html':'text','.zip':'archive'}
    kind=kinds.get(path.suffix.lower())
    if not kind or sha(path)!=value['sha256']:raise ValueError('工具产物完整性校验失败')
    fid=db.digest({'project':pid,'path':str(path),'hash':value['sha256']})[:32]
    try:db.get(c,'file',fid,pid)
    except ValueError:
        db.put(c,'file',fid,{'id':fid,'project':pid,'name':path.name,'kind':kind,'path':str(path),
                           'sha256':value['sha256'],'size':path.stat().st_size,'generated_by':generated_by},pid)
        db.emit(c,pid,'file/added',{'id':fid,'name':path.name})
    return {**value,'file_id':fid,'url':f'/api/projects/{pid}/files/{fid}'}


def draft_package(pid,draft):
    from app.workbench_d.commercial.resources import slot,scoped_check
    with slot('draft-package',scoped_check(engine(pid).store)) as lease:
        return _draft_package(pid,draft,lease.check)


def _draft_package(pid,draft,check):
    source=contained(draft['path'],DATA/'projects'/pid)
    target=source.parent/(str(draft['revision'])+'-'+draft['nativeHash'][:16]+'.zip')
    if not target.exists():
        temp=target.with_suffix('.'+db.uid()+'.partial')
        members={name:contained(source/name,source) for name in draft['files'] if not name.startswith(('frames-','raster/'))}
        for name,path in members.items():
            if sha(path)!=draft['files'][name]:raise ValueError('草稿源文件发生变化，不能重新包装为原交付')
        if (source/'d-manifest.json').is_file():members['d-manifest.json']=source/'d-manifest.json'
        manifest={'files':{name:sha(path) for name,path in members.items()},'project':pid,'source':draft['source'],'editor_ui_verified':False}
        from .artifact_io import zip_member
        import os
        try:
            with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
                for name,path in members.items():zip_member(z,path,'draft/'+name,check)
                z.writestr('manifest.json',db.dump(manifest))
                z.write(ROOT/'scripts/install_draft.py','install_draft.py')
                z.writestr('README.txt','关闭剪映，使用 install_draft.py 安装到新目录。未替代目标剪映实机验收。')
            check()
            # The core's exact revision determines immutable package contents.
            try:os.link(temp,target)
            except FileExistsError:pass
        finally:
            if temp.exists():temp.unlink()
    return {'path':str(target),'sha256':sha(target)}

def register_pair(c,pid,draft,archive,e):
    build_id=draft.get('source',{}).get('buildId')
    task=next((t for t in db.all(c,'task',pid) if t.get('build_id')==build_id),None)
    if not task:return None
    built=e.store.build(build_id)
    if built['status']!='succeeded':raise ValueError('配套交付需要成功构建')
    did=db.digest({'project':pid,'build':build_id,'draft':draft['draftId'],'revision':draft['revision'],'archive':archive['sha256']})[:32]
    try:return db.get(c,'delivery',did,pid)
    except ValueError:pass
    row={'id':did,'project':pid,'revision':task['revision'],'task_id':task['id'],'build_id':build_id,
         'preview_path':built['result']['path'],'preview_sha256':built['result']['sha256'],
         'zip_path':archive['path'],'zip_sha256':archive['sha256'],'installer_sha256':sha(ROOT/'scripts/install_draft.py'),
         'limitations':draft['limitations'],'baked':draft['baked'],'editor_ui_verified':False}
    if task.get('template_binding'):row['template_binding']=task['template_binding']
    db.put(c,'delivery',did,row,pid);db.emit(c,pid,'delivery/created',{'id':did,'revision':row['revision']})
    return row


def dispatch(pid, name, args):
    name = canonical_name(name)
    validate_arguments(name,args)
    definition = next((t for t in catalog() if t["name"] == name), None)
    if not definition:
        raise ValueError("未知业务工具")
    if name == "stop_production":
        return stop(pid)
    if name == "request_production":
        return prepare(pid, args.get("regenerate_nodes"))
    if name == "adopt_legacy_revision":
        return adopt_legacy(pid,args['task_id'])
    if name in {"get_template_instance", "propose_template_adaptation", "compile_template_plan"}:
        from . import templates
        if name == "get_template_instance":return templates.instance(pid,args.get("instance"))
        if name == "propose_template_adaptation":return templates.propose(pid,args["instance"],args["adaptation"],args["command_id"])
        return templates.compile_plan(pid,args["plan_id"])
    if name == "read_skill":
        path = contained(SKILL / args["path"], SKILL)
        if path.suffix not in {".md", ".json"}:
            raise ValueError("未知 Skill 资源")
        return {"path": args["path"], "text": path.read_text(encoding="utf-8-sig")}
    e = engine(pid)
    if name == "d_cancel_build":
        if not SAFE_ID.fullmatch(args.get("buildId","")):raise ValueError("Invalid build identity")
        e.store.build(args["buildId"])
        return stop(pid,args.get("commandId"))
    with db.transaction() as c:
        args = resolve_paths(c, pid, copy.deepcopy(args))
        if name == "d_record_view":
            raise ValueError("VISIBLE_RECEIPT_REQUIRED: only an actual browser visibility receipt may record this operation")
        if name == "d_transfer_workspace":
            import os
            from app.workbench_d.commercial.bridge import read_workspace
            grants = db.all(c, "workspace_grant", pid)
            allowed=[g for g in grants if g["workspace_id"] == args["workspace_id"] and g['expected_revision']==args['expected_revision']
                     and g['database']==str(Path(os.environ.get('D_LEGACY_DATABASE','')).resolve())
                     and g['assets']==str(Path(os.environ.get('D_LEGACY_ASSETS','')).resolve())]
            if not allowed:
                raise ValueError("WORKSPACE_IMPORT_REQUIRED: select and authorize a legacy workspace first")
            with e.store.connect() as core:
                receipt=core.execute('SELECT id FROM receipts WHERE id=?',(args['commandId'],)).fetchone()
            if not receipt:
                source=read_workspace(args['workspace_id'],args['expected_revision'])
                if not any(g['document_hash']==source['source']['document_sha256'] for g in allowed):
                    raise ValueError('工作区内容已变化，请重新确认导入')
        if name in {"d_authorize_budget", "d_submit_build", "d_retry_build"}:
            if name == "d_retry_build":
                built=e.store.build(args['buildId'])
                args={**args,'projectId':built['project'],'revision':built['revision']}
            project = e.store.project(args["projectId"], args["revision"])
            p = db.get(c, "project", pid)
            if p.get("native_project") != project["projectId"] or e.store.project(project["projectId"])["authorRevision"] != args["revision"]:
                raise ValueError("只能对当前项目的精确最新修订报价")
            for task in reversed(db.all(c, "task", pid)) if name!='d_retry_build' else []:
                if task.get("native") and task["core_project"] == args["projectId"] and task["revision"] == args["revision"] and task["status"] not in {"cancelled", "stopping", "failed"}:
                    return {"status": task["status"], "taskId": task["id"], "buildId": task.get("build_id"), "authorization": "existing user receipt"}
            # Do not nest control transactions.
        if name=="d_jianying_import":
            imported=Path(args['directory'])/'d-project.json'
            if imported.is_file():
                resolve_paths(c,pid,json.loads(imported.read_text(encoding='utf8')))
    if name in {"d_authorize_budget","d_submit_build","d_retry_build"}:
        return {"status": "waiting_user", "quote": prepare(pid), "instruction": "展示画布和增量报价，等待用户确认。模型调用不能授权费用。"}
    # Long D exports/previews never own the global Web control database transaction.
    if name in {"d_build_status", "d_inspect_build"}:
        result = e.store.build(args["buildId"])
        if name == "d_inspect_build":
            from app.workbench_d.commercial.ledger import Ledger
            result["remoteRequests"] = [{k: v for k, v in r.items() if k not in {"response", "payload"}} for r in Ledger(e.store).inspect(args["buildId"])]
    else:
        result = core_api.dispatch(name, args, engine=e)
    packaged=draft_package(pid,result) if name in {'d_export_draft','d_jianying_create','d_jianying_edit','d_jianying_import'} else None
    with db.transaction() as c:
        if name in {"d_create_project", "d_edit_project", "d_bind_brand_lock", "d_instantiate_workflow", "d_transfer_workspace"}:
            result_project = result.get("projectId")
            if result_project:
                bind(c, pid, e.store.project(result_project))
        result=expose_file(c,pid,result)
        if packaged:
            artifact=expose_file(c,pid,packaged)
            result={**result,'archive_url':artifact['url'],'archive_file_id':artifact['file_id']}
            if name=='d_export_draft':
                paired=register_pair(c,pid,result,packaged,e)
                if paired:result={**result,'web_delivery_id':paired['id'],'preview_url':f"/api/projects/{pid}/deliveries/{paired['id']}/preview"}
        db.emit(c, pid, "tool/completed", {"name": name, "result": result})
        if name=='d_save_view':db.emit(c,pid,'native/canvas',{'projectId':args['projectId'],'revision':args['revision']})
    return result


def tick_native(task):
    """One dispatcher submits; resource waits never own the Web control lock."""
    from app.workbench_d.commercial.ledger import Ledger
    e = engine(task["project"])
    pid, tid = task["project"], task["id"]
    with db.transaction() as c:latest=db.get(c,'task',tid,pid)
    if latest["status"] not in {"queued", "running", "reconciling", "stopping"}:
        return
    fence = flow.state(e.store)
    if not latest.get("build_id") and not latest.get("stop_requested") and fence["epoch"] == latest["epoch"]:
        from app.workbench_d.commercial.resources import slot
        def check():
            if flow.state(e.store)["epoch"] != latest["epoch"]:
                raise InterruptedError("Project stopped while waiting for local resources")
        def progress(**stage):
            with db.transaction() as c:
                current = db.get(c,"task",tid,pid)
                current["stage"] = stage
                db.put(c,"task",tid,current,pid,True)
        built = None
        try:
            with slot("build-preflight",check,progress):
                with db.transaction() as c:
                    from . import templates
                    source=e.store.project(latest["core_project"])
                    if templates.gate(c,pid,source,latest.get("template_binding"),authorized=True) != latest.get("template_binding"):
                        raise ValueError("任务缺少模板授权绑定")
                    if runtime(latest["document"]) != latest["execution"]["runtime"]:
                        raise ValueError("配置或实现已变化，不能提交已排队工程")
                    for asset in latest["document"]["assets"]:
                        if sha(Path(asset["path"])) != asset["sha256"]:
                            raise ValueError("输入素材已变化")
                    check()
                flow.resume(e.store,latest["epoch"])
                for price in latest["accounts"]:
                    group=(price["account"],price["currency"])
                    cap=sum(p["maximumReservedMicros"] for p in latest["accounts"] if (p["account"],p["currency"])==group)
                    Ledger(e.store).authorize({"commandId":"budget-"+tid+"-"+db.digest(group)[:12],
                        "projectId":latest["core_project"],"revision":latest["core_revision"],
                        "account":group[0],"currency":group[1],"limitMicros":cap,"concurrency":1})
                built=e.submit({"commandId":"native-build-"+tid,"projectId":latest["core_project"],
                                "revision":latest["core_revision"]},execution=latest["execution"])
        except InterruptedError:
            if flow.state(e.store)["epoch"] == latest["epoch"]:
                raise
        finally:
            if built:
                with db.transaction() as c:
                    current=db.get(c,"task",tid,pid)
                    current.update(build_id=built["buildId"],status="stopping" if current.get("stop_requested") else "running")
                    db.put(c,"task",tid,current,pid,True)
        with db.transaction() as c:latest=db.get(c,'task',tid,pid)
    if latest.get('stop_requested') and latest.get('build_id'):
        # Cancellation may wait for a core writer; never hold the Web control lock.
        e.cancel({'commandId':'global-stop-'+tid,'buildId':latest['build_id']})
    with db.transaction() as c:
        task = db.get(c, "task", tid, pid)
        if task["status"] not in {"queued", "running", "reconciling", "stopping"}:
            return
        fence = flow.state(e.store)
        if not task.get("build_id"):
            if task.get("stop_requested") or fence["epoch"] != task["epoch"]:
                task.update(status="cancelled", stop_requested=True)
        if task.get("build_id"):
            b = e.store.build(task["build_id"])
            if not task.get("stop_requested") and fence["epoch"] == task["epoch"] and not fence["stopped"]:
                e.launch(task["build_id"])
            rows = Ledger(e.store).inspect(task["build_id"])
            unresolved = any(r["state"] in {"unknown", "submitting"} for r in rows)
            task.update(status="stopping" if task.get("stop_requested") and b["status"] in {"queued", "running"} else
                        "reconciling" if unresolved and not task.get("stop_requested") else b["status"],
                        stage=b.get("progress"), nodes=b["nodes"], error=b.get("error"), remote_unresolved=unresolved)
            if b["status"] == "succeeded":
                task["result"] = b["result"]
                if task['accounts']:
                    usage=db.get(c,'usage',tid,pid)
                    usage.update(state='succeeded',bill_status='待供应商对账')
                    db.put(c,'usage',tid,usage,pid,True)
            for node in b["nodes"]:
                if node["status"] != "succeeded" or not node.get("result") or node["id"] not in task["node_keys"]:
                    continue
                output_id = tid + ":" + node["id"]
                try:
                    db.get(c, "node_output", output_id, pid)
                except ValueError:
                    expose_file(c,pid,node['result'],tid)
                    db.put(c, "node_output", output_id, {"project": pid, "node": node["id"],
                           "key": task["node_keys"][node["id"]], "result": node["result"], "build_id": task["build_id"], "attempt_created":task["created"]}, pid)
        old = db.get(c, "task", tid, pid)
        db.put(c, "task", tid, task, pid, True)
        if db.digest(old) != db.digest(task):
            db.emit(c, pid, "task/updated", {"id": tid, "status": task["status"], "error": task.get("error")})
        if task["status"] in {"succeeded", "failed", "cancelled"}:
            enqueue(c, pid, "terminal:" + tid, "制作任务 " + tid + " 状态为 " + task["status"] + "。请检查实际结果、说明失败或继续审片和交付。", task["epoch"])

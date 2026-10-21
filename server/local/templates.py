"""Owner-scoped template service shared by browser and Agent. Uses control DB transactions."""
import hashlib
import re
import time
from pathlib import Path
from . import db, projects
from .config import DATA, CONFIG, OWNER, contained
from app.creative_templates.contracts import digest, loads, fail, issue, TemplateError, HASH_VERSION, COMPILER_VERSION, implementation_hash
from app.creative_templates.admission import validate
from app.creative_templates.expansion import expand, options
from app.creative_templates.compiler import adapt, compile_document
from app.workbench_d.commercial.render import sha


def enabled():
    if CONFIG.get("templates_enabled", True) is False:
        fail("FEATURE_DISABLED", "", "模板功能已关闭；已有授权仍按原记录处理")


def routes():
    # Deliberately requires an operator-pinned contract; template authors cannot choose credentials/prices.
    return CONFIG.get("template_routes", {})


def resolve(c, rid):
    r = db.get(c, "template_resource", rid)
    r["integrity"] = Path(r["path"]).is_file() and sha(Path(r["path"])) == r["sha256"]
    return r


def verify_image(path):
    from PIL import Image
    try:
        with Image.open(path) as image:
            image.verify()
    except (OSError, ValueError, SyntaxError):
        fail("RESOURCE_DECODE_FAILED", "/file", "图片字节无法解码")


def verify_media(path, kind):
    from app.workbench_d.commercial.render import probe
    try:
        media = probe(path)
        duration = float(media["format"]["duration"])
    except Exception:
        fail("RESOURCE_DECODE_FAILED", "/file", "媒体探测失败或缺少实际时长")
    if duration <= 0 or not any(s["codec_type"] == kind for s in media.get("streams", [])):
        fail("INPUT_TYPE_MISMATCH", "/file", "真实媒体类型或时长不符")
    return round(duration * 1000)


def register_resource(name, data, kind, scope="research"):
    enabled()
    if kind not in {"image", "video", "audio", "analysis", "evidence", "font"} or scope not in {"research", "public"}:
        fail("SCHEMA_INVALID", "", "未知资源类型或范围")
    if not data or len(data) > 100 * 1024 * 1024:
        fail("CAPACITY_EXCEEDED", "", "资源大小需为 1 字节至 100 MB")
    suffix = Path(name).suffix.lower()
    extensions = {"image": {".png", ".jpg", ".jpeg", ".webp"}, "video": {".mp4", ".mov"},
                  "audio": {".wav", ".mp3", ".m4a"}, "analysis": {".json"}, "evidence": {".json", ".txt"}, "font": {".ttf", ".otf"}}
    if suffix not in extensions[kind]:
        fail("SCHEMA_INVALID", "/name", "不支持的资源扩展名")
    h = hashlib.sha256(data).hexdigest()
    rid = digest([OWNER, h, kind, scope])
    path = DATA / "template-resources" / (rid + suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and sha(path) != h:
        fail("ASSET_HASH_MISMATCH", "", "受控资源内容变化")
    if not path.exists():
        with path.open("xb") as f:
            f.write(data)
    row = {"id": rid, "sha256": h, "kind": kind, "scope": scope, "path": str(path), "name": Path(name).name, "size": len(data)}
    if kind == "image":
        verify_image(path)
    elif kind in {"video", "audio"}:
        row["duration_ms"] = verify_media(path, kind)
    elif kind == "analysis":
        value = loads(data)
        if not isinstance(value, dict) or set(value) != {"source_sha256", "observations"} or not isinstance(value["observations"], list):
            fail("SCHEMA_INVALID", "", "分析 JSON 必须包含 source_sha256 与 observations")
        row.update(value)
    elif kind == "font":
        from fontTools.ttLib import TTFont
        with TTFont(path):
            pass
    with db.transaction() as c:
        try:
            return public_resource(db.get(c, "template_resource", rid))
        except ValueError:
            db.put(c, "template_resource", rid, row)
    return public_resource(row)


def public_resource(r):
    return {k: v for k, v in r.items() if k not in {"path", "integrity"}}


def check(envelope):
    enabled()
    with db.transaction() as c:
        problems, blockers = validate(envelope, lambda rid: resolve(c, rid), routes())
    return {"accepted": not problems, "issues": problems, "publication_blockers": blockers}


def admit(envelope, producer=OWNER):
    enabled()
    # producer is from the authenticated local operator boundary, never from envelope.
    from app.creative_templates.contracts import schema_issues
    structural = schema_issues(envelope)
    if structural:
        # Malformed identifiers cannot own a receipt. Well-formed invalid candidates can.
        if not isinstance(envelope, dict) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}", str(envelope.get("command_id", ""))):
            raise TemplateError(structural)
    key = digest([producer, envelope["command_id"]])
    request_hash = digest(envelope)
    with db.transaction() as c:
        try:
            prior = db.get(c, "template_admission", key)
        except ValueError:
            prior = None
        if prior:
            if prior["request_hash"] != request_hash:
                fail("IDEMPOTENCY_CONFLICT", "/command_id", "同一导入命令的内容发生变化")
            return prior["receipt"]
        problems, blockers = validate(envelope, lambda rid: resolve(c, rid), routes())
        receipt = {"admission_id": key, "accepted": False, "issues": problems, "publication_blockers": blockers}
        if not problems:
            tid = digest([producer, envelope["producer_item_id"]])[:32]
            try:
                head = db.get(c, "template_head", tid)
            except ValueError:
                head = {"id": tid, "revision": 0, "producer": producer}
            if head["revision"] != envelope["expected_revision"]:
                receipt["issues"].append(issue("REVISION_CONFLICT", "/expected_revision", "模板版本已更新"))
            else:
                rev = head["revision"] + 1
                content = envelope["candidate"]
                row = {"template_id": tid, "revision": rev, "content_hash": digest(content), "hash_version": HASH_VERSION,
                       "candidate": content, "created": time.time(), "producer": producer}
                db.put(c, "template_revision", f"{tid}:{rev}", row)
                db.put(c, "template_state", f"{tid}:{rev}", {"state": "draft", "tier": "assisted", "limitations": []})
                db.put(c, "template_head", tid, {**head, "revision": rev}, update=head["revision"] != 0)
                receipt.update(accepted=True, template_id=tid, revision=rev, content_hash=row["content_hash"])
        db.put(c, "template_admission", key, {"request_hash": request_hash, "receipt": receipt, "producer": producer})
        return receipt


def revision(c, tid, rev):
    row = db.get(c, "template_revision", f"{tid}:{rev}")
    return {**row, **db.get(c, "template_state", f"{tid}:{rev}")}


def get_revision(tid, rev):
    with db.transaction() as c:
        return revision(c, tid, rev)


def catalog(author=False):
    with db.transaction() as c:
        rows = [revision(c, r["template_id"], r["revision"]) for r in db.all(c, "template_revision")]
    return [r for r in rows if author or r["state"] == "published"]


def preview(tid, rev, value):
    return expand(get_revision(tid, rev)["candidate"], value)


def mount(c, value, allow_draft=True):
    if not isinstance(value, dict) or set(value) - {"template_id", "revision", "content_hash", "bindings", "parameters", "component_selections", "output"}:
        fail("SCHEMA_INVALID", "/template_mount", "未知挂载字段")
    if not {"template_id", "revision", "content_hash"} <= value.keys():
        fail("SCHEMA_INVALID", "/template_mount", "缺少精确模板引用")
    row = revision(c, value["template_id"], value["revision"])
    if row["content_hash"] != value["content_hash"]:
        fail("REVISION_CONFLICT", "/template_mount/content_hash", "模板内容哈希不一致")
    if row["state"] == "retired" or not allow_draft and row["state"] != "published":
        fail("TEMPLATE_UNAVAILABLE", "/template_mount", "模板已退役或未发布")
    opts = options(row["candidate"], {k: value[k] for k in ("bindings", "parameters", "component_selections", "output") if k in value})
    expand(row["candidate"], opts)
    return row, opts


def get_composer(cid):
    with db.transaction() as c:
        try:
            row = db.get(c, "template_composer", cid)
        except ValueError:
            row = {"id": cid, "revision": 0, "project": None, "template_mount": None, "text": ""}
        return {**row, "files": [{k: v for k, v in f.items() if k != "path"} for f in db.all(c, "template_staged", cid)]}


def save_composer(cid, body):
    enabled()
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,96}", cid):
        fail("SCHEMA_INVALID", "/composer_id", "草稿 ID 无效")
    with db.transaction() as c:
        try:
            old = db.get(c, "template_composer", cid)
        except ValueError:
            old = {"revision": 0}
        if old["revision"] != body.get("expected_revision"):
            fail("REVISION_CONFLICT", "/expected_revision", "输入草稿已在另一个窗口改变")
        if body.get("project"):
            db.get(c, "project", body["project"])
        value = body.get("template_mount")
        if value:
            mount(c, value)
        text = body.get("text", "")
        if not isinstance(text, str) or len(text) > 20000:
            fail("SCHEMA_INVALID", "/text", "草稿文本过长")
        row = {"id": cid, "revision": old["revision"] + 1, "project": body.get("project"),
               "template_mount": value, "text": text, "updated": time.time()}
        db.put(c, "template_composer", cid, row, update=old["revision"] != 0)
        return row


def stage_file(cid, name, data):
    # Reuses the normal upload verifier in a transaction-free temporary project folder,
    # then persists a distinct staged record; no phantom project/message is created.
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,96}", cid):
        fail("SCHEMA_INVALID", "/composer_id", "草稿 ID 无效")
    suffix = Path(name).suffix.lower()
    kinds = {".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".mp4": "video", ".mov": "video", ".wav": "audio", ".mp3": "audio"}
    if suffix not in kinds or not data or len(data) > 100 * 1024 * 1024:
        fail("SCHEMA_INVALID", "/file", "请上传有效图片、视频或音频（最多 100 MB）")
    h = hashlib.sha256(data).hexdigest()
    fid = digest([cid, h, Path(name).name])[:32]
    path = DATA / "template-staging" / cid / (fid + suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("xb") as f:
            f.write(data)
    if sha(path) != h:
        fail("ASSET_HASH_MISMATCH", "/file", "暂存文件发生变化")
    if kinds[suffix] == "image":
        verify_image(path)
    else:
        verify_media(path, kinds[suffix])
    row = {"id": fid, "project": cid, "name": Path(name).name, "kind": kinds[suffix], "sha256": h, "path": str(path), "size": len(data), "created": time.time()}
    with db.transaction() as c:
        try:
            db.get(c, "template_staged", fid, cid)
        except ValueError:
            db.put(c, "template_staged", fid, row, cid)
    return {k: v for k, v in row.items() if k != "path"}


def validate_bindings(c, candidate, opts, pid, cid=None):
    files = {}
    selected_components = {x["id"]: x for x in candidate["components"]}
    required = set()
    for chosen in opts["component_selections"].values():
        required.update(selected_components[chosen]["required_slot_ids"])
    for slot in candidate["input_slots"]:
        refs = opts["bindings"].get(slot["id"], [])
        if not max(slot["min_items"], int(slot["id"] in required)) <= len(refs) <= slot["max_items"]:
            fail("SLOT_COUNT_INVALID", "/bindings/" + slot["id"], "素材数量不符合该槽要求")
        for fid in refs:
            try:
                f = db.get(c, "file", fid, pid) if pid else None
            except ValueError:
                f = None
            if f is None and cid:
                try:
                    f = db.get(c, "template_staged", fid, cid)
                except ValueError:
                    fail("ASSET_NOT_FOUND", "/bindings/" + slot["id"], "上传未完成或素材不属于当前草稿/项目")
            if f is None:
                fail("ASSET_NOT_FOUND", "/bindings/" + slot["id"], "素材不属于当前项目")
            if f["kind"] != slot["media_kind"]:
                fail("INPUT_TYPE_MISMATCH", "/bindings/" + slot["id"], "素材类型不匹配")
            if not Path(f["path"]).is_file() or sha(Path(f["path"])) != f["sha256"]:
                fail("ASSET_HASH_MISMATCH", "/bindings/" + slot["id"], "素材字节已变化")
            files[fid] = f
    return files


def send(body, pid=None):
    enabled()
    command = body.get("command_id")
    with db.transaction() as c:
        def action():
            from . import commands
            from .models import Plan
            cid = body.get("composer_id")
            draft = db.get(c, "template_composer", cid) if cid else None
            if draft and draft["revision"] != body.get("expected_composer_revision"):
                fail("REVISION_CONFLICT", "/expected_composer_revision", "输入草稿已更新")
            if draft and draft.get("project") not in {None, pid}:
                fail("RESOURCE_SCOPE_INVALID", "/composer_id", "草稿属于另一个项目")
            p = db.get(c, "project", pid) if pid else None
            value = body.get("template_mount") if "template_mount" in body else draft.get("template_mount") if draft else None
            previous = None
            if p and p.get("template_instance"):
                previous = db.get(c, "template_instance", p["template_instance"], pid)
                if not value:
                    value = {**previous["template"], **previous["options"]}
            # Explicit stop/quote-confirm messages operate on the existing exact instance.
            # Creating a new instance here would invalidate the quote being confirmed.
            raw_text = body.get("text", "").strip()
            control_intent = commands.user_intent(c, pid, raw_text) if p else None
            if previous and control_intent:
                if value and value != {**previous["template"], **previous["options"]}:
                    fail("REVISION_CONFLICT", "/template_mount", "确认或停止消息不能同时更改模板挂载")
                m = projects.message(c, pid, "user", raw_text, template_instance=previous["id"], template=previous["template"])
                inbox_id = "user:" + digest([pid, command])[:40]
                item = commands.enqueue(c, pid, inbox_id, raw_text, 0)
                item.update(user=True, file_ids=[], template_instance=previous["id"], message_id=m["id"], intent=control_intent)
                db.put(c, "agent_inbox", inbox_id, item, pid, True)
                if draft:
                    draft.update(revision=draft["revision"] + 1, text="", sent_instance=previous["id"])
                    db.put(c, "template_composer", cid, draft, update=True)
                return {"accepted": True, "project": pid, "run_id": inbox_id, "message_id": m["id"], "template_instance": previous["id"]}
            row, opts = mount(c, value)
            files = validate_bindings(c, row["candidate"], opts, pid, cid)
            text = body.get("text", "").strip() or f"使用模板《{row['candidate']['catalog']['title']}》v{row['revision']}，{opts['output']['duration_seconds']} 秒。"
            if len(text) > 20000:
                fail("SCHEMA_INVALID", "/text", "消息过长")
            target = pid or db.uid()
            if not p:
                folder = DATA / "projects" / target
                folder.mkdir(parents=True, exist_ok=True)
                p = {"id": target, "project": target, "title": text[:45], "revision": 0, "thread_id": None, "status": "idle", "created": time.time()}
                db.put(c, "project", target, p, target)
                db.put(c, "plan", target + ":0", {"project": target, "revision": 0, "plan": Plan(title=p["title"]).model_dump(), "hash": db.digest({})}, target)
                db.emit(c, target, "project/created", {"id": target})
            for fid, f in files.items():
                try:
                    existing = db.get(c, "file", fid)
                    if existing["project"] != target:
                        fail("RESOURCE_SCOPE_INVALID", "/bindings", "素材已被另一个项目使用")
                except ValueError as exc:
                    if isinstance(exc, TemplateError):
                        raise
                    db.put(c, "file", fid, {**f, "project": target}, target)
            same = previous and previous["template"] == {k: row[k] for k in ("template_id", "revision", "content_hash")}
            iid = previous["instance_id"] if same else db.uid()
            rev = previous["instance_revision"] + 1 if same else 1
            key = f"{iid}:{rev}"
            inst = {"id": key, "instance_id": iid, "instance_revision": rev, "project": target,
                    "template": {k: row[k] for k in ("template_id", "revision", "content_hash")},
                    "options": opts, "request": text, "trial": row["state"] != "published",
                    "binding_hashes": {fid: f["sha256"] for fid, f in files.items()}}
            db.put(c, "template_instance", key, inst, target)
            p.update(template_instance=key, status="starting")
            db.put(c, "project", target, p, target, True)
            m = projects.message(c, target, "user", text, template_instance=key, template=inst["template"])
            inbox_id = "user:" + digest([target, command])[:40]
            inbox = commands.enqueue(c, target, inbox_id, text, 0)
            inbox.update(user=True, file_ids=list(files), template_instance=key, message_id=m["id"],
                         intent=commands.user_intent(c, target, text))
            db.put(c, "agent_inbox", inbox_id, inbox, target, True)
            for q in db.all(c, "quote", target):
                if q["status"] == "pending":
                    q["status"] = "superseded"
                    db.put(c, "quote", q["id"], q, target, True)
            if draft:
                draft.update(project=target, revision=draft["revision"] + 1, text="", sent_instance=key)
                db.put(c, "template_composer", cid, draft, update=True)
            return {"accepted": True, "project": target, "run_id": inbox_id, "message_id": m["id"], "template_instance": key}
        return db.once(c, command, {"op": "template-send", "project": pid, "body": body}, action)


def instance(pid, key=None):
    with db.transaction() as c:
        p = db.get(c, "project", pid)
        key = key or p.get("template_instance")
        if not key:
            fail("REFERENCE_MISSING", "/instance", "项目没有模板实例")
        inst = db.get(c, "template_instance", key, pid)
        template = revision(c, inst["template"]["template_id"], inst["template"]["revision"])
        return {**inst, "template_revision": template, "expanded": expand(template["candidate"], inst["options"])}


def propose(pid, key, proposal, command):
    enabled()
    inst = instance(pid, key)
    candidate = inst["template_revision"]["candidate"]
    with db.transaction() as c:
        def action():
            p = db.get(c, "project", pid)
            if p.get("template_instance") != key:
                fail("REVISION_CONFLICT", "/instance", "实例已更新，需读取本条消息的精确实例")
            previous = [r for r in db.all(c, "template_plan", pid) if r["instance_id"] == inst["instance_id"]]
            rejected = [r for r in db.all(c, "template_adaptation_attempt", pid) if r["instance"] == key and r["status"] == "rejected"]
            if len(rejected) > candidate["adaptation_policy"]["max_plan_repairs"]:
                return {"_template_rejected": [issue("PLAN_REPAIR_LIMIT", "/adaptation", "已达到本实例的适配修正上限；需人工检查后创建新实例")]}
            try:
                plan = adapt(candidate, inst, proposal, previous[-1]["expanded"]["playback"] if previous else None)
            except TemplateError as exc:
                # Persist a rejected command and its attempt count before raising outside
                # the transaction. Retrying the same command never consumes another repair.
                db.put(c, "template_adaptation_attempt", db.uid(),
                       {"project": pid, "instance": key, "command_id": command, "status": "rejected", "issues": exc.issues}, pid)
                return {"_template_rejected": exc.issues}
            plan.update(id=db.uid(), project=pid, instance=key, instance_id=inst["instance_id"], template=inst["template"], status="accepted")
            plan["plan_hash"] = digest(plan)
            db.put(c, "template_plan", plan["id"], plan, pid)
            return plan
        result = db.once(c, command, {"op": "template-propose", "project": pid, "instance": key, "proposal": proposal}, action)
    if "_template_rejected" in result:
        raise TemplateError(result["_template_rejected"])
    return result


def compile_plan(pid, plan_id):
    enabled()
    from . import commands
    with db.transaction() as c:
        plan = db.get(c, "template_plan", plan_id, pid)
        inst = db.get(c, "template_instance", plan["instance"], pid)
        p = db.get(c, "project", pid)
        if p.get("template_instance") != inst["id"]:
            fail("REVISION_CONFLICT", "/instance", "旧实例不能替代当前工程")
        row = revision(c, inst["template"]["template_id"], inst["template"]["revision"])
        if row["state"] == "retired":
            fail("TEMPLATE_UNAVAILABLE", "/template", "模板已退役")
        files = validate_bindings(c, row["candidate"], plan["expanded"]["options"], pid)
        try:
            operation = db.get(c, "template_compile", plan_id, pid)
        except ValueError:
            font_path = Path(CONFIG.get("font", "C:/Windows/Fonts/msyh.ttc"))
            font = {"id": "template_font", "kind": "font", "path": str(font_path), "sha256": sha(font_path),
                    "source": "configured-font", "license": "local system font"} if font_path.is_file() else None
            doc, mapping = compile_document(row["candidate"], plan, files, routes(), font)
            operation = {"id": plan_id, "project": pid, "state": "prepared", "document": doc, "mapping": mapping,
                         "command_id": "template-compile-" + plan_id, "route_hash": digest(routes()),
                         "implementation_hash": implementation_hash(),
                         "core_project": p.get("native_project"), "base_revision": p.get("native_revision"),
                         "name": row["candidate"]["catalog"]["title"]}
            db.put(c, "template_compile", plan_id, operation, pid)
        if operation["implementation_hash"] != implementation_hash():
            fail("TEMPLATE_VALIDATION_REQUIRED", "/compiler", "编译实现已变化，请重新提交适配计划")
    # Durable operation before touching D. D's mutate() looks up its exact command receipt first.
    e = commands.engine(pid)
    args = {"commandId": operation["command_id"], "document": operation["document"]}
    if operation["core_project"]:
        result = e.edit({**args, "projectId": operation["core_project"], "baseRevision": operation["base_revision"]})
    else:
        result = e.create({**args, "name": operation["name"]})
    with db.transaction() as c:
        p = db.get(c, "project", pid)
        if p.get("template_instance") != inst["id"]:
            fail("REVISION_CONFLICT", "/instance", "编译过程中实例更新；D 回执已保留，未绑定新实例")
        current = e.store.project(result["projectId"])
        if current["sha256"] != result["sha256"] or current["authorRevision"] != result["authorRevision"]:
            fail("REVISION_CONFLICT", "/document", "编译回执后 D 已被编辑")
        report = {"project": pid, "instance": inst["id"], "plan": plan_id, "plan_hash": plan["plan_hash"], "template": inst["template"],
                  "core_project": result["projectId"], "revision": result["authorRevision"], "document_hash": result["sha256"],
                  "compiler_version": COMPILER_VERSION, "route_hash": operation["route_hash"], "structural": "passed",
                  "implementation_hash": operation["implementation_hash"],
                  "visual": "pending", "tier": "assisted", "mapping": operation["mapping"],
                  "binding_hashes": inst["binding_hashes"]}
        try:
            prior = db.get(c, "template_report", plan_id, pid)
            if prior != report:
                fail("IDEMPOTENCY_CONFLICT", "/report", "已存在不同编译报告")
        except ValueError as exc:
            if isinstance(exc, TemplateError):
                raise
            db.put(c, "template_report", plan_id, report, pid)
        commands.bind(c, pid, result)
        p = db.get(c, "project", pid)
        p["template_plan"] = plan_id
        db.put(c, "project", pid, p, pid, True)
        operation.update(state="bound", result={k: result[k] for k in ("projectId", "authorRevision", "sha256")})
        db.put(c, "template_compile", plan_id, operation, pid, True)
    return {"plan_id": plan_id, "report": report, "native": operation["result"]}


def gate(c, pid, source, expected=None, authorized=False):
    p = db.get(c, "project", pid)
    if not p.get("template_instance") and not expected:
        return None
    if not authorized:
        enabled()
    if authorized and expected:
        # Queued authorized work stays pinned even when the composer moves to a new instance.
        plan_id = expected["plan"]
    else:
        plan_id = p.get("template_plan")
    if not plan_id:
        fail("TEMPLATE_VALIDATION_REQUIRED", "/plan", "模板实例尚无已编译校验报告")
    report = db.get(c, "template_report", plan_id, pid)
    if not authorized and report["instance"] != p.get("template_instance"):
        fail("TEMPLATE_VALIDATION_REQUIRED", "/instance", "当前实例没有有效报告")
    plan = db.get(c, "template_plan", plan_id, pid)
    if report["plan_hash"] != plan["plan_hash"] or report["compiler_version"] != COMPILER_VERSION or report["implementation_hash"] != implementation_hash():
        fail("TEMPLATE_VALIDATION_REQUIRED", "/plan", "计划或编译器已变化")
    if (source["projectId"], source["authorRevision"], source["sha256"]) != (report["core_project"], report["revision"], report["document_hash"]):
        fail("TEMPLATE_VALIDATION_REQUIRED", "/document", "D 编辑使模板报告失效；请重新适配编译或显式脱离模板")
    if report["route_hash"] != digest(routes()):
        fail("TEMPLATE_VALIDATION_REQUIRED", "/route", "模板模型路线已变化")
    row = revision(c, report["template"]["template_id"], report["template"]["revision"])
    if not authorized and row["state"] == "retired":
        fail("TEMPLATE_UNAVAILABLE", "/template", "退役模板禁止新制作")
    for fid, h in report["binding_hashes"].items():
        f = db.get(c, "file", fid, pid)
        if sha(Path(f["path"])) != h:
            fail("ASSET_HASH_MISMATCH", "/bindings/" + fid, "原始绑定素材发生变化")
    binding = {k: report[k] for k in ("instance", "plan", "plan_hash", "template", "core_project", "revision", "document_hash", "compiler_version", "implementation_hash", "route_hash")}
    binding["report_hash"] = digest(report)
    if expected is not None and expected != binding:
        fail("TEMPLATE_VALIDATION_REQUIRED", "/quote", "报价绑定的模板/实例/报告已变化")
    return binding


def lifecycle(tid, rev, action, body):
    if action not in {"review", "publish", "retire"}:
        fail("SCHEMA_INVALID", "", "未知生命周期动作")
    with db.transaction() as c:
        def mutate():
            row = revision(c, tid, rev)
            state = db.get(c, "template_state", f"{tid}:{rev}")
            if action == "review":
                if row["state"] != "draft":
                    fail("REVISION_CONFLICT", "", "只有草稿可进入审核")
                state.update(state="reviewed", limitations=body.get("limitations", []))
            elif action == "publish":
                # Published evidence is derived from system tasks/deliveries, never accepted from an import.
                if body.get("tier", "assisted") != "assisted":
                    fail("STAGE_AUTHORIZATION_REQUIRED", "/tier", "T5 尚未验收，禁止自动制作档位")
                validations = [v for v in db.all(c, "template_validation") if v["template_id"] == tid and v["revision"] == rev]
                distinct = {v["product_hash"] for v in validations}
                if row["state"] != "runtime_validated" or len(distinct) < 3:
                    fail("PUBLICATION_EVIDENCE_MISSING", "", "需要三个不同产品的真实系统试作、成片与人工审阅记录")
                state.update(state="published", tier="assisted", sample=validations[0]["sample"])
            else:
                state["state"] = "retired"
            db.put(c, "template_state", f"{tid}:{rev}", state, update=True)
            db.put(c, "template_event", db.uid(), {"template_id": tid, "revision": rev, "action": action,
                                                 "operator": OWNER, "created": time.time(), "state": state})
            return state
        return db.once(c, body["command_id"], {"op": "template-" + action, "id": tid, "revision": rev, "body": body}, mutate)


def detach(pid, body):
    with db.transaction() as c:
        def action():
            p = db.get(c, "project", pid)
            if p.get("template_instance") != body.get("expected_instance"):
                fail("REVISION_CONFLICT", "/expected_instance", "实例已更新")
            key = p.pop("template_instance", None)
            p.pop("template_plan", None)
            db.put(c, "project", pid, p, pid, True)
            event = {"id": db.uid(), "project": pid, "from_instance": key, "state": "detached", "created": time.time()}
            db.put(c, "template_detachment", event["id"], event, pid)
            for quote in db.all(c, "quote", pid):
                if quote["status"] == "pending":
                    quote["status"] = "superseded"
                    db.put(c, "quote", quote["id"], quote, pid, True)
            projects.message(c, pid, "system", "已显式脱离模板约束；历史实例、制作授权和交付保留。", template_detachment=event["id"])
            return event
        return db.once(c, body["command_id"], {"op": "template-detach", "project": pid, "body": body}, action)


def review_run(pid, task_id, body):
    """Operator review of actual delivered bytes, backed by successful production ledger."""
    from . import commands
    from app.workbench_d.commercial.ledger import Ledger
    e = commands.engine(pid)
    with db.transaction() as c:
        def action():
            task = db.get(c, "task", task_id, pid)
            binding = task.get("template_binding")
            if not binding or task["status"] != "succeeded" or not task.get("build_id"):
                fail("PUBLICATION_EVIDENCE_MISSING", "/task", "需要模板实例的成功实际构建")
            build = e.store.build(task["build_id"])
            if build["status"] != "succeeded":
                fail("PUBLICATION_EVIDENCE_MISSING", "/build", "构建尚未成功")
            rows = Ledger(e.store).inspect(task["build_id"])
            # Never accept a caller's synthetic runtime receipt or untraced local fixture.
            if not rows or any(r["state"] != "succeeded" or not r.get("remote") for r in rows):
                fail("PUBLICATION_EVIDENCE_MISSING", "/requests", "必须有成功且含真实远端 ID 的模型账本记录")
            delivery = db.get(c, "delivery", body["delivery_id"], pid)
            if delivery["task_id"] != task_id or delivery["build_id"] != task["build_id"]:
                fail("PUBLICATION_EVIDENCE_MISSING", "/delivery", "交付不属于此构建")
            for kind in ("preview", "zip"):
                if sha(Path(delivery[kind + "_path"])) != delivery[kind + "_sha256"]:
                    fail("ASSET_HASH_MISMATCH", "/delivery", "交付内容发生变化")
            row = revision(c, binding["template"]["template_id"], binding["template"]["revision"])
            state = db.get(c, "template_state", f"{row['template_id']}:{row['revision']}")
            if state["state"] not in {"reviewed", "runtime_validated"}:
                fail("REVISION_CONFLICT", "/state", "模板须先完成操作者审核")
            visual_ids = {x["id"] for x in row["candidate"]["checks"] if x["kind"] != "structural"}
            if set(body.get("checks", {})) != visual_ids or any(v is not True for v in body["checks"].values()) or not body.get("notes", "").strip():
                fail("PUBLICATION_EVIDENCE_MISSING", "/checks", "需逐项人工审阅所有视觉条件并记录意见")
            inst = db.get(c, "template_instance", binding["instance"], pid)
            product = [fid for s in row["candidate"]["input_slots"] if s["identity_kind"] == "product" for fid in inst["options"]["bindings"].get(s["id"], [])[:1]]
            if not product:
                fail("PUBLICATION_EVIDENCE_MISSING", "/bindings", "发布试作需绑定产品")
            rid = digest([pid, task_id])
            receipt = {"id": rid, "project": pid, "template_id": row["template_id"], "revision": row["revision"],
                       "product_hash": digest(sorted(inst["binding_hashes"][f] for f in product)),
                       "task_id": task_id, "build_id": task["build_id"], "structural": binding["report_hash"],
                       "visual": body["checks"], "notes": body["notes"], "reviewer": OWNER,
                       "sample": {"project": pid, "delivery_id": delivery["id"], "sha256": delivery["preview_sha256"]}}
            try:
                prior = db.get(c, "template_validation", rid, pid)
                if prior != receipt:
                    fail("IDEMPOTENCY_CONFLICT", "/review", "本构建已有不同审阅记录")
            except ValueError as exc:
                if isinstance(exc, TemplateError):
                    raise
                db.put(c, "template_validation", rid, receipt, pid)
            validations = [v for v in db.all(c, "template_validation") if v["template_id"] == row["template_id"] and v["revision"] == row["revision"]]
            if len({v["product_hash"] for v in validations}) >= 3:
                state["state"] = "runtime_validated"
                db.put(c, "template_state", f"{row['template_id']}:{row['revision']}", state, update=True)
            return receipt
        return db.once(c, body["command_id"], {"op": "template-review-run", "project": pid, "task": task_id, "body": body}, action)


def cleanup_staged(older_than_seconds=7 * 86400):
    """Remove only expired, unreferenced staging files. Never project media or historical inputs."""
    if older_than_seconds < 7 * 86400:
        fail("SCHEMA_INVALID", "/retention", "暂存保留期至少七天")
    removed = []
    with db.transaction() as c:
        files = {r["id"] for r in db.all(c, "file")}
        instances = {fid for r in db.all(c, "template_instance") for ids in r["options"]["bindings"].values() for fid in ids}
        mounted = {fid for d in db.all(c, "template_composer") for ids in (d.get("template_mount") or {}).get("bindings", {}).values() for fid in ids}
        for row in db.all(c, "template_staged"):
            if not row.get("created") or time.time() - row["created"] < older_than_seconds or row["id"] in files | instances | mounted:
                continue
            path = contained(row["path"], DATA / "template-staging" / row["project"])
            if path.is_file():
                if sha(path) != row["sha256"]:
                    continue
                path.unlink()
            c.execute(db.facts.delete().where(db.facts.c.kind == "template_staged", db.facts.c.id == row["id"], db.facts.c.owner == OWNER))
            removed.append(row["id"])
        if removed:
            db.put(c, "template_cleanup", db.uid(), {"removed": removed, "created": time.time()})
    return {"removed": removed}

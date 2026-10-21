"""Authorized single-product trial, isolated from the operator's existing ledger.

No synthetic media, simulated provider, or auto-confirmation. `init` is local;
`serve` runs the real app/Agent/Worker; `confirm` executes the exact saved quote.
The copied configuration contains credential references only, never secret values.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".local/template-real-daisy-20261020"
EVIDENCE = ROOT / "docs/evidence/template-real-daisy"
SOURCE = ROOT / ".local/data/projects/49b2b8b68b1a46ab99d232d6992e1a52/files/23bcef830cfa402498d6eff6e56998b5.mp4"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf8")


def initialize():
    if (WORK / "ready.json").exists() or (WORK / "data/control.sqlite3").exists():
        raise RuntimeError("Existing trial must be resumed, never reinitialized.")
    config = json.loads((ROOT / "config.local.json").read_text(encoding="utf-8-sig"))
    config.update(data_dir=str(WORK / "data"), database_url="", port=8917, test_budget_cny=100,
                  templates_enabled=True)
    config["template_routes"] = {"reference_guided_video_v1": {
        "provider": "ark", "model": "seedance-2", "max_inputs": 1, "roles": ["first_frame"],
        "exclusive_frame_reference": True, "min_seconds": 4, "max_seconds": 15,
        "max_cost_micros": 33000000, "options": {"resolution": "720p", "generate_audio": False}}}
    write(WORK / "config.json", config)


def context():
    config = json.loads((WORK / "config.json").read_text(encoding="utf8"))
    os.environ.update(VC_CONFIG=str(WORK / "config.json"), VC_DATA=str(WORK / "data"),
                      D_FFMPEG=config["ffmpeg"], D_FFPROBE=config["ffprobe"],
                      PYTHONUTF8="1")
    # An inherited external database must never merge this trial into another ledger.
    os.environ.pop("VC_DATABASE_URL", None)
    sys.path.insert(0, str(ROOT / "server"))


def seed():
    from local import templates, production
    production.setup_media()
    source = templates.register_resource("整理白色雏菊.mp4", SOURCE.read_bytes(), "video")
    observations = [
        {"id": "obs_close", "range_ms": [0, 1], "kind": "observation",
         "description": "0 秒画面：白色多层花瓣、浅黄绿色花心和绿色花茎，放在棕色木条花篮内；窗侧暖光，花店背景虚化。"},
        {"id": "obs_wide", "range_ms": [4000, 4001], "kind": "observation",
         "description": "4 秒画面：镜头比开场更宽，白衣深色围裙的人在整理花篮内的白花，背景为明亮窗户和其他花材。"},
        {"id": "obs_structure", "range_ms": [0, 5000], "kind": "inference",
         "description": "根据 0、2、4 秒抽帧推断可采用白花细节到花篮展示的两段结构；这是本次创作方案，并非来源视频已经验证的可复用模板。"},
    ]
    analysis = templates.register_resource("daisy-analysis.json", json.dumps({
        "source_sha256": source["sha256"], "observations": observations
    }, ensure_ascii=False).encode(), "analysis")
    env = json.loads((ROOT / "docs/examples/template-admission-v1.example.json").read_text(encoding="utf8"))
    env.update(command_id="real-daisy-admission-v1", producer_item_id="real-daisy-two-segments")
    c = env["candidate"]
    c["catalog"] = {"title": "清晨白花 · 两段展示试作", "summary": "基于授权复用的花店白花素材；单产品真实试作，尚未发布。",
                    "category": "product_motion", "tags": ["花束", "真实试作", "待审阅"]}
    c["sources"] = [{"id": "daisy_source", "platform": "user_authorized_local", "canonical_url": None,
                     "media_ref": {k: source[v] for k, v in (("resource_id", "id"), ("sha256", "sha256"))},
                     "analysis_ref": {k: analysis[v] for k, v in (("resource_id", "id"), ("sha256", "sha256"))},
                     "observations": observations}]
    c["preview"] = {"kind": "none", "asset_id": None, "note": "首次真实试作前没有样片；成片待视觉验收。"}
    c["input_slots"][0].update(label="白花参考帧", max_items=1,
                                description="一张授权来源视频的真实抽帧，作为首帧。")
    c["component_slots"] = [{"id": "setting", "default_component_id": "morning_shop",
                              "allowed_component_ids": ["morning_shop"]}]
    c["components"] = [{"id": "morning_shop", "label": "窗边花店", "slot": "setting",
                        "target_segment_ids": ["hook", "hero"], "required_slot_ids": ["product"],
                        "replace_requirement_ids": [], "requirement_ids": [], "incompatible_component_ids": [],
                        "recipe_overrides": [{"recipe_id": "product_motion", "section": "environment",
                                              "text": "保持参考帧的窗边花店、木质花篮与自然暖光，背景柔和，不改变场景。"}]}]
    c["output_policy"].update(aspect_ratios=["16:9"], min_seconds=8, max_seconds=12, default_seconds=10)
    c["segments"] = [s for s in c["segments"] if s["id"] in {"hook", "hero"}]
    for s in c["segments"]:
        s.update(min_seconds=4, max_seconds=6, weight=1)
    c["segments"][0].update(label="花瓣细节", purpose="从参考构图轻轻推近白色花瓣与浅黄绿色花心，保持同一花篮")
    c["segments"][1].update(label="花篮定格", purpose="维持参考图可见的花材和花篮构图，缓慢轻微拉远，最后两秒稳定展示白花")
    c["prompt_recipes"][0]["sections"].update(
        environment="保持参考帧的窗边花店、木质花篮与自然暖光。",
        motion="克制的缓慢镜头运动；人物只做轻微自然整理，不新增人物，不生成复杂手部动作。",
        constraints="保持白色花瓣、浅黄绿色花心、绿色茎叶和棕色花篮；不虚构未见结构，不添加文字、品牌或功效。")
    c["nodes"] = [n for n in c["nodes"] if n["id"] != "feature_video"]
    for n in c["nodes"]:
        n["depends_on"] = [d for d in n["depends_on"] if d["node_id"] != "feature_video"]
        n["output_inputs"] = [d for d in n["output_inputs"] if d["node_id"] != "feature_video"]
        if n["kind"] == "generate":
            n["slot_inputs"] = [{"slot_id": "product", "role": "first_frame", "selection": "first"}]
    for r in c["requirements"]:
        r["target_segment_ids"] = [s for s in r["target_segment_ids"] if s != "feature"]
    c["requirements"][0]["description"] = "先展示白花细节，再以同一花篮稳定收尾，两段均不可省略。"
    c["requirements"][1]["description"] = "核对各段白花、花心颜色、绿色茎叶与木质花篮是否与参考帧一致。"
    c["requirements"][2]["description"] = "结尾至少两秒清楚稳定展示参考图可见的白花；不要求补全未见的花篮底部。"
    receipt = templates.admit(env)
    write(EVIDENCE / "admission.json", {"request": env, "receipt": receipt})
    if not receipt["accepted"]:
        raise RuntimeError(receipt)
    cid = "real-daisy-composer"
    f = templates.stage_file(cid, "白花参考帧.jpg", (WORK / "daisy-reference.jpg").read_bytes())
    mount = {k: receipt[k] for k in ("template_id", "revision", "content_hash")}
    mount.update(bindings={"product": [f["id"]]}, output={"aspect_ratio": "16:9", "duration_seconds": 10},
                 parameters={"end_copy": "清晨 · 白花"})
    draft = templates.save_composer(cid, {"expected_revision": 0, "template_mount": mount})
    text = ("白色雏菊模板真实试作：复用已绑定的花店白花参考帧，10 秒、16:9、两段，结尾文案“清晨 · 白花”。"
            "只做少量试作，本任务新增费用合计不超过100元。请读取本条消息的精确模板实例，"
            "观察附件并使用 propose_template_adaptation、compile_template_plan 完成受限适配和确定性编译，"
            "随后 request_production 报价并结束本轮等待。不要绕过模板工具直接编辑D，不添加镜头或新素材，不重试媒体生成。")
    sent = templates.send({"command_id": "real-daisy-send-v1", "composer_id": cid,
                           "expected_composer_revision": draft["revision"], "text": text})
    write(WORK / "ready.json", {**sent, "template": receipt, "composer": cid})
    write(EVIDENCE / "authorization.json", {
        "date": "2026-10-20", "budget_cny": 100, "scope": "New trial total including planning and media",
        "user_budget": "预算100以内吧，少量测试即可。", "user_material": "复用白色雏菊素材",
        "original_project": "49b2b8b68b1a46ab99d232d6992e1a52", "source_sha256": source["sha256"],
        "trial_directory": str(WORK), "original_config_modified": False, "original_ledger_modified": False,
        "maximum_media_requests_planned": 2, "media_upper_cny_per_request": 33,
        "publication": "Not authorized as validated publication; three distinct product trials and manual review unmet."
    })
    print(json.dumps(sent, ensure_ascii=False))


def snapshot():
    from local import db
    from sqlalchemy import select
    ready = json.loads((WORK / "ready.json").read_text(encoding="utf8"))
    pid = ready["project"]
    with db.transaction() as conn:
        result = {"project": db.get(conn, "project", pid)}
        for kind in ("usage", "quote", "task", "template_plan", "template_report", "delivery", "question", "agent_inbox", "message"):
            rows = db.all(conn, kind, pid)
            if kind == "quote":
                from local.commands import public_quote
                rows = [public_quote(r) for r in rows]
            if kind == "task":
                rows = [{k: v for k, v in r.items() if k not in {"document", "runtime", "generation_keys"}} for r in rows]
            result[kind] = rows
        result["events"] = []
        for kind, raw in conn.execute(select(db.events.c.kind, db.events.c.body).where(
                db.events.c.project == pid).order_by(db.events.c.seq.desc()).limit(40)):
            body = json.loads(raw)
            if kind in {"task/updated", "tool/completed", "delivery/created", "usage/completed"} or (
                    kind == "item/completed" and body.get("item", {}).get("type") in {"mcpToolCall", "agentMessage"}):
                result["events"].append({"kind": kind, "body": body})
    from local.commands import engine
    from app.workbench_d.commercial.ledger import Ledger
    result["remote_requests"] = []
    for task in result["task"]:
        if task.get("build_id"):
            result["remote_requests"].extend({k: v for k, v in r.items() if k not in {"response", "payload"}}
                                             for r in Ledger(engine(pid).store).inspect(task["build_id"]))
    result["reserved_cny"] = sum(r["reserved_micros"] for r in result["usage"] if r["state"] != "released") / 1e6
    write(EVIDENCE / "status.json", result)
    return result


def downscope():
    from local import templates, db
    ready = json.loads((WORK / "ready.json").read_text(encoding="utf8"))
    with db.transaction() as conn:
        if db.all(conn, "task", ready["project"]):
            raise RuntimeError("Cannot change the trial after a media submission.")
    env = json.loads((EVIDENCE / "admission.json").read_text(encoding="utf8"))["request"]
    env.update(command_id="real-daisy-admission-v2-single", expected_revision=1)
    c = env["candidate"]
    c["catalog"].update(title="清晨白花 · 单镜试作", summary="真实链路诊断后的单镜试作；保留同一预算账本，减少为一次媒体生成。")
    c["segments"] = [s for s in c["segments"] if s["id"] == "hero"]
    c["segments"][0].update(min_seconds=10, max_seconds=10,
                            purpose="保持同一花店和白花篮，轻微缓慢推近，最后两秒稳定展示白花")
    c["output_policy"].update(min_seconds=10, max_seconds=10)
    c["nodes"] = [n for n in c["nodes"] if n["id"] != "hook_video"]
    for n in c["nodes"]:
        n["depends_on"] = [d for d in n["depends_on"] if d["node_id"] != "hook_video"]
        n["output_inputs"] = [d for d in n["output_inputs"] if d["node_id"] != "hook_video"]
    for row in c["components"] + c["requirements"]:
        row["target_segment_ids"] = ["hero"]
    c["requirements"][0]["description"] = "单个十秒花篮镜头，以稳定展示收尾，不添加其他生成镜头。"
    receipt = templates.admit(env)
    write(EVIDENCE / "admission-v2.json", {"request": env, "receipt": receipt})
    if not receipt["accepted"]:
        raise RuntimeError(receipt)
    old = templates.instance(ready["project"], ready["template_instance"])
    mount = {k: receipt[k] for k in ("template_id", "revision", "content_hash")}
    mount.update(old["options"])
    draft = templates.get_composer(ready["composer"])
    draft = templates.save_composer(ready["composer"], {"expected_revision": draft["revision"],
                                                        "project": ready["project"], "template_mount": mount})
    text = ("继续这次已授权的少量真实试作，因前轮无效规划已停止，现明确改用v2单镜模板：10秒、16:9、一次媒体请求。"
            "本次合计仍不超过100元，已有规划费用保持计入。请只调用get_template_instance读取新消息精确实例；"
            "propose_template_adaptation的adaptation只填写identity.product（白色花瓣、浅黄绿色花心、绿色茎叶、棕色木花篮、窗边花店）"
            "和parameters.end_copy（清晨 · 白花），省略segment_text。无需搜索源码或任何额外文档。"
            "使用返回plan id调用compile_template_plan，再调用request_production报价后立即结束本轮。不要直接编辑D，不生成任何额外素材。")
    sent = templates.send({"command_id": "real-daisy-send-v2-single", "composer_id": ready["composer"],
                           "expected_composer_revision": draft["revision"], "text": text}, ready["project"])
    write(WORK / "ready.json", {**sent, "template": receipt, "composer": ready["composer"]})
    write(EVIDENCE / "downscope.json", {"reason": "Stopped unproductive Agent adaptation loop. Original costs retained.",
                                       "new_media_requests": 1, "media_upper_cny": 33, "total_budget_cny": 100,
                                       "previous_instance": ready["template_instance"], "new_instance": sent["template_instance"]})
    print(json.dumps(sent))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["init", "seed", "downscope", "serve", "review", "execute", "export", "finalize", "status", "quote", "confirm"])
    parser.add_argument("--quote")
    args = parser.parse_args()
    if args.action == "init":
        initialize()
    context()
    if args.action in {"init", "seed"}:
        seed()
    elif args.action == "downscope":
        downscope()
    elif args.action in {"serve", "review"}:
        import uvicorn
        uvicorn.run("local.main:app", host="127.0.0.1", port=8917, log_level="warning",
                    lifespan="off" if args.action == "review" else "auto")
    elif args.action == "execute":
        # Same production Worker tick, but no post-delivery Agent continuation:
        # keep the user's remaining budget for the single authorized media request.
        from local import production
        production.setup_media()
        previous = None
        for _ in range(1200):
            production.tick()
            s = snapshot()
            task = s["task"][-1] if s["task"] else {}
            state = (task.get("status"), task.get("stage"), task.get("error"))
            if state != previous:
                print(json.dumps({"task": task.get("id"), "status": state[0], "stage": state[1],
                                  "error": state[2], "reserved_cny": s["reserved_cny"]}, ensure_ascii=False), flush=True)
                previous = state
            if task.get("status") in {"succeeded", "failed", "stopped", "needs_attention"}:
                return
            time.sleep(1)
        raise RuntimeError("Trial still pending after bounded wait; query existing request, never resubmit.")
    elif args.action == "status":
        s = snapshot()
        print(json.dumps({k: s[k] for k in ("project", "reserved_cny", "usage", "quote", "task", "question", "agent_inbox", "message", "remote_requests")}, ensure_ascii=False))
    elif args.action == "export":
        from local import commands, production, projects, db
        production.setup_media()
        s = snapshot()
        task = s["task"][-1]
        if task["status"] != "succeeded":
            raise RuntimeError("Cannot deliver before a successful real build")
        pid = s["project"]["id"]
        delivery = commands.dispatch(pid, "d_deliver_mp4", {"commandId": "daisy-deliver-v2", "buildId": task["build_id"]})
        choice = commands.dispatch(pid, "d_choose_export", {"commandId": "daisy-export-choice-v2",
                                                           "deliveryId": delivery["deliveryId"], "format": "jianying", "allowBaked": False})
        draft = commands.dispatch(pid, "d_export_draft", {"commandId": "daisy-export-draft-v2",
                                                         "choiceId": choice["choiceId"], "name": "清晨白花-单镜真实试作"})
        write(EVIDENCE / "export.json", {"delivery": delivery, "choice": choice, "draft": draft})
        with db.transaction() as conn:
            project = db.get(conn, "project", pid)
            project["title"] = "清晨白花 · 单镜真实试作"
            db.put(conn, "project", pid, project, pid, True)
            db.once(conn, "daisy-local-delivery-note", {"delivery": delivery["deliveryId"]}, lambda: projects.message(
                conn, pid, "assistant",
                "执行补充（本地试作记录）：已恢复使用原配置中的 LGPL FFmpeg；按本任务已有的100元授权确认精确报价。"
                "真实视频生成1次，10秒、16:9，MP4与同版剪映草稿已成对交付。规划保守预留62.758224元，"
                "媒体保守预留33元，合计95.758224元；实际账单待供应商核对。为保留余量，关闭了自动规划续跑。"
                "模板仍为作者草稿；视觉检查记录、用户人工审阅与剪映实机验收不可混同，三个产品发布门槛尚未达到。"))
        s = snapshot()
        print(json.dumps(s["delivery"], ensure_ascii=False))
    elif args.action == "finalize":
        import zipfile
        import httpx
        from local import commands
        s = snapshot()
        pid = s["project"]["id"]
        d = s["delivery"][-1]
        checks = {}
        for kind in ("preview", "zip"):
            url = f"http://127.0.0.1:8917/api/projects/{pid}/deliveries/{d['id']}/{kind}"
            response = httpx.get(url, trust_env=False, timeout=30)
            response.raise_for_status()
            checks[kind] = {"status": response.status_code, "bytes": len(response.content),
                            "sha256": hashlib.sha256(response.content).hexdigest()}
            if checks[kind]["sha256"] != d[kind + "_sha256"]:
                raise RuntimeError("Downloaded delivery hash differs from its immutable receipt")
        with zipfile.ZipFile(d["zip_path"]) as archive:
            if archive.testzip():
                raise RuntimeError("Corrupt archive member")
            native = json.loads(archive.read("draft/draft_content.json"))
            checks["native_draft"] = {"duration_microseconds": native["duration"],
                                      "tracks": [{"type": t["type"], "segments": len(t["segments"])} for t in native["tracks"]],
                                      "baked": d["baked"], "editor_ui_verified": False}
        stopped = commands.stop(pid, "real-daisy-finish-no-more-spend")
        s = snapshot()
        result = {"status": "single_product_trial_delivered", "project": pid, "task": s["task"][-1]["id"],
                  "remote_requests": s["remote_requests"], "budget_cny": 100, "reserved_cny": s["reserved_cny"],
                  "planning_reserved_cny": sum(u["reserved_micros"] for u in s["usage"] if u["category"] == "planning" and u["state"] != "released") / 1e6,
                  "actual_provider_bill": "pending_reconciliation", "download_checks": checks,
                  "visual_review": {"reviewer": "assistant_sampled_frames", "frames": [0, 48, 96, 144, 192, 239],
                                    "image": "render-contact.jpg", "user_approved": False,
                                    "observations": ["抽帧中白花、浅黄绿色花心、绿茎与棕色花篮连贯。",
                                                     "后半段露珠特写较突出，是否符合产品设定待用户确认。",
                                                     "单镜即唯一末段，当前文案贯穿该段；浅色花瓣上的白字对比度一般。",
                                                     "只检查抽帧，不宣称手部逐帧连续性、完整视频审片或剪映实机通过。"]},
                  "publication": {"state": "draft", "distinct_products": 1, "required_products": 3,
                                  "T5_automatic": False, "manual_visual_approval": False},
                  "new_work_blocked": stopped["new_work_blocked"],
                  "artifacts": {"mp4": str(WORK / "deliverables/morning-daisy-10s.mp4"),
                                "jianying": str(WORK / "deliverables/morning-daisy-jianying.zip")}}
        write(EVIDENCE / "result.json", result)
        print(json.dumps(result, ensure_ascii=False))
    elif args.action in {"quote", "confirm"}:
        from local import commands, production
        production.setup_media()
        s = snapshot()
        if args.action == "quote":
            print(json.dumps(commands.prepare(s["project"]["id"]), ensure_ascii=False))
            return
        if not args.quote:
            raise RuntimeError("Exact quote ID required")
        q = next(q for q in s["quote"] if q["id"] == args.quote and q["status"] == "pending")
        if q["paid_tasks"] != 1 or q["maximum_micros"] > 33000000 or s["reserved_cny"] + q["maximum_micros"] / 1e6 > 100:
            raise RuntimeError("Quote exceeds the explicitly scoped trial")
        r = commands.confirm(s["project"]["id"], q["id"], "real-daisy-confirm-" + q["id"], source="authorized-trial")
        write(EVIDENCE / "confirmed-quote.json", {"quote": q, "task": {k: r.get(k) for k in ("id", "status", "quote_id")}})
        print(json.dumps({k: r.get(k) for k in ("id", "status", "quote_id")}))


if __name__ == "__main__":
    main()

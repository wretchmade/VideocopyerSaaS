"""Durable per-project inbox. Unknown turn starts require reconciliation, not replay."""
import asyncio
import time
from . import db, bridge, commands
from app.workbench_d.commercial import flow


def recover():
    with db.transaction() as c:
        for item in db.all(c, "agent_inbox"):
            if item["status"] in {"dispatching", "dispatched"}:
                item["status"] = "needs_attention"
                item["reconcile_pending"] = True
                db.put(c, "agent_inbox", item["id"], item, item["project"], True)
                db.emit(c, item["project"], "agent/recovery_required",
                        {"id": item["id"], "message": "上次 Agent 轮次结果待核对，未自动重发。发送消息可继续读取项目状态。"})

async def reconcile(item):
    """Read the persisted Codex history; a correlation ID is never a replay license."""
    pid=item['project'];result=None;error=None
    try:
        if item.get('thread_id'):
            runner=bridge.runner(pid)
            await runner.start()
            result=await runner.rpc('thread/read',{'threadId':item['thread_id'],'includeTurns':True})
    except Exception as exc:error=str(exc)
    turns=(result or {}).get('thread',{}).get('turns',[])
    match=next((t for t in turns if t['id']==item.get('turn') or
                any(i.get('type')=='userMessage' and item.get('client_id') and i.get('clientId')==item['client_id'] for i in t.get('items',[]))),None)
    with db.transaction() as c:
        current=db.get(c,'agent_inbox',item['id'],pid)
        current.update(reconcile_pending=False,recovery_checked=True)
        if error:current['recovery_error']=error
        if match:
            current['turn']=match['id'];current['recovered_turn_status']=match['status']
            if match['status']=='completed':
                current['status']='done'
                for entry in match.get('items',[]):
                    if entry.get('type')=='agentMessage':bridge.record_assistant(c,pid,entry)
        db.put(c,'agent_inbox',item['id'],current,pid,True)
        db.emit(c,pid,'agent/reconciled',{'id':item['id'],'status':current['status'],'replayed':False})

async def tick():
    with db.transaction() as c:
        items = db.all(c, "agent_inbox")
    seen = set()
    for item in items:
        pid = item["project"]
        if item.get('reconcile_pending'):
            await reconcile(item)
            continue
        if item["status"] != "pending" or pid in seen:
            continue
        if item.get('intent') and not item.get('intent_processed'):
            try:await asyncio.to_thread(commands.apply_user_intent,item)
            except Exception as exc:
                with db.transaction() as c:
                    item.update(status='needs_attention',error=str(exc))
                    db.put(c,'agent_inbox',item['id'],item,pid,True)
                    db.emit(c,pid,'agent/error',{'message':str(exc)})
                continue
        seen.add(pid)
        runner = bridge.RUNNERS.get(pid)
        if runner and (runner.active or runner.turn_lock.locked()):
            continue
        e = commands.engine(pid)
        fence = flow.state(e.store)
        if not item.get("user") and fence and (fence["stopped"] or item["epoch"] != fence["epoch"]):
            with db.transaction() as c:
                item["status"] = "suppressed"
                db.put(c, "agent_inbox", item["id"], item, pid, True)
            continue
        runner = bridge.runner(pid)
        async with runner.turn_lock:
            with db.transaction() as c:
                current = db.get(c, "agent_inbox", item["id"], pid)
                if current["status"] != "pending":
                    continue
                current["status"] = "dispatching"
                db.put(c, "agent_inbox", item["id"], current, pid, True)
            runner.inbox_id = item["id"]
            try:
                result = await runner.turn(item["text"], item.get("file_ids"), item.get("selected"))
                with db.transaction() as c:
                    current = db.get(c, "agent_inbox", item["id"], pid)
                    if current["status"] != "done":
                        current.update(status="dispatched", turn=result.get("turn_id"))
                        db.put(c, "agent_inbox", item["id"], current, pid, True)
            except Exception as exc:
                runner.inbox_id = None
                with db.transaction() as c:
                    current.update(status="needs_attention", error=str(exc))
                    db.put(c, "agent_inbox", item["id"], current, pid, True)
                    db.emit(c, pid, "agent/error", {"message": str(exc)})


async def run():
    last_template_cleanup = 0
    while True:
        try:
            await tick()
            if time.monotonic() - last_template_cleanup >= 3600:
                from . import templates
                last_template_cleanup = time.monotonic()
                await asyncio.to_thread(templates.cleanup_staged)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Keep pending work durable; never erase an inbox on transient failure.
            print("Agent coordinator:", type(exc).__name__, flush=True)
        await asyncio.sleep(.5)

"""Real Codex/MCP/Web/FFmpeg with a scripted local Responses fixture, never a paid API."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import io
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import httpx
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
WORK=Path(tempfile.mkdtemp(prefix="parity-web-",dir=ROOT/".local"))
steps=[]
requests=[]
lock=threading.Lock()
jobs={}
allow_b=False
timings={}


class ModelFixture(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path=="/submit":
            with lock:
                jid=str(len(jobs)+1)
                jobs[jid]={"prompt":body.get("prompt"),"cancelled":False}
            return self.reply({"id":jid})
        if self.path.startswith("/cancel/"):
            jobs[self.path.split("/")[-1]]["cancelled"]=True
            return self.reply({"status":"cancelled"})
        with lock:
            requests.append(body)
            step=steps.pop(0) if steps else None
            number=len(requests)
        rid="resp_fixture_"+str(number)
        base={"id":rid,"object":"response","created_at":int(time.time()),"model":body["model"],"status":"in_progress","output":[]}
        events=[{"type":"response.created","response":base}]
        if step:
            name,args=step
            wire=next((t["name"] for t in body.get("tools",[]) if t["name"].endswith(name)),None)
            if not wire:
                (WORK/"missing-tools.json").write_text(json.dumps(body,ensure_ascii=False,indent=2),encoding="utf8")
                raise RuntimeError("MCP tool missing in gateway: "+name)
            item={"type":"function_call","id":"fc_"+str(number),"call_id":"call_"+str(number),"name":wire,"arguments":"","status":"in_progress"}
            events.append({"type":"response.output_item.added","output_index":0,"item":dict(item)})
            arguments=json.dumps(args,ensure_ascii=False)
            events.append({"type":"response.function_call_arguments.delta","item_id":item["id"],"output_index":0,"delta":arguments})
            item.update(arguments=arguments,status="completed")
            events.append({"type":"response.function_call_arguments.done","item_id":item["id"],"output_index":0,"arguments":arguments})
        else:
            item={"type":"message","id":"msg_"+str(number),"role":"assistant","status":"in_progress","content":[]}
            events.append({"type":"response.output_item.added","output_index":0,"item":dict(item)})
            part={"type":"output_text","text":"","annotations":[]}
            events.append({"type":"response.content_part.added","item_id":item["id"],"output_index":0,"content_index":0,"part":dict(part)})
            text="本地协议夹具已完成本轮；这不是模型质量验收。"
            events.append({"type":"response.output_text.delta","item_id":item["id"],"output_index":0,"content_index":0,"delta":text})
            part["text"]=text
            events.append({"type":"response.output_text.done","item_id":item["id"],"output_index":0,"content_index":0,"text":text})
            events.append({"type":"response.content_part.done","item_id":item["id"],"output_index":0,"content_index":0,"part":part})
            item.update(content=[part],status="completed")
        events.append({"type":"response.output_item.done","output_index":0,"item":item})
        events.append({"type":"response.completed","response":{**base,"status":"completed","output":[item],"usage":{"input_tokens":10,"output_tokens":10,"total_tokens":20}}})
        data="".join("data: "+json.dumps({**event,"sequence_number":i},ensure_ascii=False)+"\n\n" for i,event in enumerate(events)).encode()
        self.send_response(200);self.send_header("Content-Type","text/event-stream");self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data)
    def reply(self,value):
        data=json.dumps(value).encode()
        self.send_response(200);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if self.path.startswith("/poll/"):
            jid=self.path.split("/")[-1];job=jobs[jid]
            status="cancelled" if job["cancelled"] else "running" if job["prompt"]=="B" and not allow_b else "succeeded"
            return self.reply({"status":status,"outputs":[f"http://127.0.0.1:{self.server.server_port}/image/{jid}.png"]})
        if self.path.startswith("/image/"):
            jid=int(self.path.split("/")[-1].split(".")[0]);out=io.BytesIO()
            Image.new("RGB",(64,64),((jid*43)%255,(jid*73)%255,(jid*97)%255)).save(out,format="PNG")
            data=out.getvalue();self.send_response(200);self.send_header("Content-Type","image/png");self.send_header("Content-Length",str(len(data)));self.end_headers();self.wfile.write(data)
            return
        self.send_error(404)
    def do_DELETE(self):
        if self.path.startswith("/cancel/"):
            jobs[self.path.split("/")[-1]]["cancelled"]=True
            return self.reply({"status":"cancelled"})
        self.send_error(404)


def wait_for(fn,seconds=45):
    start=time.monotonic()
    while time.monotonic()-start<seconds:
        result=fn()
        if result:return result
        time.sleep(.2)
    raise TimeoutError(f"Condition did not complete; inspect {WORK}")


def main():
    global allow_b
    mock=ThreadingHTTPServer(("127.0.0.1",0),ModelFixture)
    threading.Thread(target=mock.serve_forever,daemon=True).start()
    with socket.socket() as sock:sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
    original=json.loads((ROOT/"config.local.json").read_text(encoding="utf-8-sig"))
    cfg={k:original[k] for k in ("ffmpeg","ffprobe","font")}
    cfg.update(port=port,test_budget_cny=100,data_dir=str(WORK/"data"),media_profile="",
               planning={"base_url":f"http://127.0.0.1:{mock.server_port}","model":original["planning"]["model"],
                         "key_env":"VC_PARITY_FAKE_KEY","input_cny_per_million":12,"output_cny_per_million":60,"max_output_tokens":1024})
    config=WORK/"config.json";config.write_text(json.dumps(cfg),encoding="utf8")
    (WORK/"data").mkdir()
    provider=WORK/"data/providers.json"
    provider.write_text(json.dumps({"fixture":{"base_url":f"http://127.0.0.1:{mock.server_port}","account":"fixture-only","currency":"CNY","credential_env":"VC_PARITY_FAKE_KEY","models":{"fixture":{"output_kind":"image","documentation":"local fixture contract","fields":[],"submit":"/submit","poll":"/poll/{id}","cancel":"/cancel/{id}","output_path":"outputs","poll_seconds":.1,"quote":{"upperMicros":10,"expires":time.time()+3600}}}}}),encoding="utf8")
    env={**os.environ,"VC_CONFIG":str(config),"VC_DATA":str(WORK/"data"),"VC_PARITY_FAKE_KEY":"local-fixture-only",
         "PYTHONPATH":str(ROOT/"server"),"PYTHONUTF8":"1","D_PROVIDERS":str(provider)}
    os.environ.update({k:env[k] for k in ("VC_CONFIG","VC_DATA","VC_PARITY_FAKE_KEY","PYTHONPATH")})
    sys.path.insert(0,str(ROOT/"server"))
    from app.workbench_d.commercial.processes import ProcessTree
    from local import db,commands
    log=(WORK/"server.log").open("wb")
    process=subprocess.Popen([sys.executable,"-m","uvicorn","local.main:app","--host","127.0.0.1","--port",str(port)],
                             cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    tree=ProcessTree(process)
    client=httpx.Client(base_url=f"http://127.0.0.1:{port}",timeout=30)
    try:
        def ready():
            try:return client.get("/api/bootstrap").is_success
            except httpx.TransportError:return False
        wait_for(ready,20)
        client.headers["x-vc-token"]=client.get("/api/bootstrap").json()["token"]
        def post(path,value):
            started=time.perf_counter()
            r=client.post("/api"+path,json=value);r.raise_for_status()
            if path.endswith('/deliver'):timings.setdefault('paired_export_seconds',[]).append(round(time.perf_counter()-started,3))
            if value.get('command_id')=='fixture-stop':timings['stop_acceptance_seconds']=round(time.perf_counter()-started,3)
            return r.json()
        pid=post("/projects",{"text":"非付费完整协议验收","command_id":"fixture-project"})["id"]
        document={"width":64,"height":64,"frames":3,
                  "tasks":[{"id":x,"kind":"generation","provider":"fixture","model":"fixture","prompt":x,"output_kind":"image","max_cost_micros":10} for x in "ACB"],
                  "layers":[{"id":"layer_"+x,"kind":"image","asset":x,"start":i,"end":i+1,"width":64,"height":64} for i,x in enumerate("ABC")]}
        with lock:steps.extend([
            ("d_create_project",{"commandId":"fixture-core-project","name":"offline native","document":document}),
            ("request_production",{})])
        planning_started=time.perf_counter()
        post(f"/projects/{pid}/messages",{"text":"请规划测试视频","command_id":"fixture-chat-1"})
        def snapshot():return client.get(f"/api/projects/{pid}").json()
        planned=wait_for(lambda:snapshot() if snapshot().get("quotes") else None)
        wait_for(lambda:snapshot()["status"] not in {"starting","running"})
        timings['scripted_planning_with_mcp_seconds']=round(time.perf_counter()-planning_started,3)
        assert len(requests)>=3,"Expected tool-result -> next model turn loop"
        assert all(r["model"]==original["planning"]["model"] for r in requests)
        quote=planned["quotes"][0]
        subprocess.run(["node","scripts/parity-browser-test.mjs"],cwd=ROOT,env={**env,"VC_TEST_URL":str(client.base_url),"VC_TEST_PROJECT":pid},check=True,timeout=45)
        cursor=snapshot()['event_cursor']
        with client.stream('GET',f'/api/projects/{pid}/events?after=0',headers={'Last-Event-ID':str(cursor-1)}) as stream:
            first=next(line for line in stream.iter_lines() if line.startswith('id: '))
            assert int(first[4:])==cursor
        pre=len(requests)
        post(f"/projects/{pid}/quotes/{quote['id']}/confirm",{"command_id":"fixture-confirm"})
        wait_for(lambda:len(jobs)==3)
        initial_task=snapshot()['tasks'][-1]
        tree.close()
        process=subprocess.Popen([sys.executable,"-m","uvicorn","local.main:app","--host","127.0.0.1","--port",str(port)],
                                 cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        tree=ProcessTree(process)
        wait_for(ready,20)
        client.headers["x-vc-token"]=client.get("/api/bootstrap").json()["token"]
        def restarted_worker():
            status=post(f'/projects/{pid}/tools/d_build_status',{'buildId':initial_task['build_id']})
            return status['attempt']>=2
        wait_for(restarted_worker,25)
        assert len(jobs)==3,'Accepted provider request must survive Worker restart without another POST'
        post(f"/projects/{pid}/messages",{"text":"全部先停，修改 B，保留 A 和 C","command_id":"fixture-stop"})
        stopped=wait_for(lambda:next((t for t in snapshot()["tasks"] if t["status"]=="cancelled"),None))
        def idle():
            p=snapshot()
            with db.transaction() as c:inbox=db.all(c,"agent_inbox",pid)
            return p["status"] not in {"starting","running"} and all(x["status"] in {"done","suppressed","needs_attention"} for x in inbox)
        wait_for(idle)
        allow_b=True
        def planned_edit(text,modify=None,forced=None):
            wait_for(idle)
            p=snapshot();core=p["native"]
            if modify:
                doc=core["document"]
                modify(doc,p)
                with lock:steps.append(("d_edit_project",{"commandId":"edit-"+str(len(requests)),"projectId":core["projectId"],"baseRevision":core["authorRevision"],"document":doc}))
            with lock:steps.append(("request_production",{"regenerate_nodes":forced} if forced else {}))
            post(f"/projects/{pid}/messages",{"text":text,"command_id":"message-"+str(len(requests))})
            wait_for(idle)
            return snapshot()["quotes"][-1]
        def execute_quote(q):
            task=post(f"/projects/{pid}/quotes/{q['id']}/confirm",{"command_id":"confirm-"+q["id"]})
            result=wait_for(lambda:next((t for t in snapshot()["tasks"] if t["id"]==task["id"] and t["status"] in {"succeeded","failed"}),None),60)
            assert result["status"]=="succeeded",result.get("error")
            wait_for(idle)
            return result
        def change_b(doc,p):
            next(t for t in doc["tasks"] if t["id"]=="B")["prompt"]="B revised"
        second=planned_edit("只改 B，其他复用",change_b)
        assert second["reused_nodes"]==["A","C"] and second["new_nodes"]==["B"],second
        completed=execute_quote(second)
        assert len(jobs)==4
        assert completed["status"]=="succeeded",completed.get("error")
        wait_for(lambda:len(requests)>pre)
        with db.transaction() as c:
            inbox=[r for r in db.all(c,"agent_inbox",pid) if r["id"].startswith("terminal:")]
        wait_for(lambda: any(r["status"]=="done" for r in _inbox(db,pid)))
        assert inbox,"Terminal event must be durable"
        delivered=post(f"/projects/{pid}/deliver",{"task_id":completed["id"],"allow_baked":False,"command_id":"fixture-paired"})
        assert client.get(f"/api/projects/{pid}/deliveries/{delivered['id']}/preview").is_success
        assert client.get(f"/api/projects/{pid}/deliveries/{delivered['id']}/zip").is_success
        # Exact frame enters a real MCP response as image content.
        wait_for(lambda:snapshot()["status"] not in {"starting","running"})
        with lock:steps.extend([("inspect_media",{"build_id":completed["build_id"],"frame":0}),("d_build_status",{"buildId":completed["build_id"]})])
        before=len(requests)
        post(f"/projects/{pid}/messages",{"text":"检查第零帧和构建结果","command_id":"fixture-review"})
        wait_for(lambda:len(requests)>=before+3)
        assert any("data:image/" in json.dumps(r) for r in requests[before:]),"Image did not return to model context"
        wait_for(idle)
        def change_bc(doc,p):
            for t in doc["tasks"]:
                if t["id"] in {"B","C"}:t["prompt"]+=" completed revision"
        third=planned_edit("完成后重规划 B 和 C",change_bc)
        assert third["reused_nodes"]==["A"] and set(third["new_nodes"])=={"B","C"}
        execute_quote(third);assert len(jobs)==6
        forced=planned_edit("B 提示词不变，再生成一次",forced=["B"])
        assert forced["new_nodes"]==["B"]
        subprocess.run(["node","scripts/parity-browser-test.mjs"],cwd=ROOT,
                       env={**env,"VC_TEST_URL":str(client.base_url),"VC_TEST_PROJECT":pid,"VC_TEST_FORCED":"1"},check=True,timeout=45)
        execute_quote(forced);assert len(jobs)==7
        def subtitles(doc,p):
            doc["assets"].append(p["resources"]["font"])
            doc["layers"].append({"id":"subtitle","kind":"text","text":"只改字幕","fonts":["font"],"font_size":12,"start":0,"end":3,"width":64,"height":20,"track":2})
        subtitle=planned_edit("只修改字幕",subtitles)
        assert subtitle["paid_tasks"]==0 and subtitle["new_nodes"]==[]
        final=execute_quote(subtitle);assert len(jobs)==7
        final_delivery=post(f"/projects/{pid}/deliver",{"task_id":final["id"],"allow_baked":False,"command_id":"fixture-final-paired"})
        assert client.get(f"/api/projects/{pid}/deliveries/{delivered['id']}/preview").is_success
        evidence={"project":pid,"data":str(WORK),"base_url":str(client.base_url),"model_unchanged":original["planning"]["model"],
                  "scripted_fixture_not_model_quality":True,"provider_network":"loopback fixture only",
                  "model_requests":len(requests),"mcp_tool_result_continuation":True,"background_terminal_inbox":True,
                  "real_ffmpeg":True,"paired_delivery":delivered["id"],"image_result_return":True,
                  "worker_restart_no_duplicate_submit":True,"sse_last_event_id":True,
                  "stop_edit_B_reuse_AC":True,"completed_edit_BC":True,"unchanged_prompt_forced":True,
                  "subtitle_new_generation_requests":0,"total_mock_generation_submissions":len(jobs),
                  "old_delivery_download":True,"final_delivery":final_delivery["id"]}
        evidence['timings']=timings
        evidence['timing_scope']='Local fixture only; scripted planning is not real model latency or a production SLA'
        (ROOT/"docs/evidence/parity/web-protocol.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf8")
        print(json.dumps(evidence,ensure_ascii=False))
    finally:
        (WORK/"model-requests.json").write_text(json.dumps(requests,ensure_ascii=False,indent=2),encoding="utf8")
        client.close();tree.close();log.close();mock.shutdown()


def _inbox(db,pid):
    with db.transaction() as c:return [r for r in db.all(c,"agent_inbox",pid) if r["id"].startswith("terminal:")]


if __name__=="__main__":main()

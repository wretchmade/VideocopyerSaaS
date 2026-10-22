"""Real pinned Codex startup + MCP discovery, with no turn/model/provider request."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
work=Path(tempfile.mkdtemp(prefix="protocol-",dir=ROOT/".local"))
os.environ["VC_DATA"]=str(work/"data")
sys.path.insert(0,str(ROOT/"server"))
from local import bridge,db,projects
from local.tool_registry import catalog


async def main():
    pid=projects.create(db.uid(),"offline MCP protocol verification")["id"]
    runner=bridge.AgentRunner(pid)
    try:
        await runner.start()
        result=await runner.rpc("mcpServerStatus/list",{"threadId":runner.thread,"serverName":"project_d","detail":"toolsAndAuthOnly"})
        rows=result.get("data",[])
        project=next(r for r in rows if r["name"]=="project_d")
        names=set(project["tools"])
        expected={t["name"] for t in catalog()}
        assert names==expected,(len(names),len(expected),sorted(expected-names))
        evidence={"codex":"0.163.0","project_mcp_tools":len(names),"names":sorted(names),
                  "no_model_turn":True,"no_provider_requests":True,"status":project.get("status"),
                  "schema":"docs/evidence/codex-schema/v2/ListMcpServerStatusParams.json",
                  "temporary_data":str(work)}
        (ROOT/"docs/evidence/parity/mcp-protocol.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf8")
        print(json.dumps(evidence,ensure_ascii=False))
    finally:
        await runner.close()


asyncio.run(main())

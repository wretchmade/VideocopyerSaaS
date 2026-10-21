"""Project MCP stdio transport. The API owns authorization and execution."""
import json
import os
import sys
import urllib.request
from .tool_registry import catalog


def handle(message):
    method = message.get("method")
    if method == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "videocopyer-project-d", "version": "1.0.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": catalog()}
    if method == "tools/call":
        params = message["params"]
        port = int(os.environ["VC_PORT"])
        pid = os.environ["VC_PROJECT_ID"]
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/gateway/{pid}/tools",
            data=json.dumps(params).encode(), method="POST",
            headers={"Authorization": "Bearer " + os.environ["VC_GATEWAY_TOKEN"], "Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=600) as response:
            value = json.load(response)
        return value
    raise ValueError("Unknown MCP method")


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if "id" not in message:
                continue
            result = handle(message)
            response = {"jsonrpc": "2.0", "id": message["id"], "result": result}
        except Exception as exc:
            response = {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32603, "message": str(exc)}}
        print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()

"""Replay one captured tool result through real Codex/MCP; loopback fixtures only.

Run: .venv/Scripts/python.exe scripts/codex_model_config_probe.py
The context values below are test inputs, not verified Doubao specifications.
"""
import asyncio
import copy
import json
import os
import socket
import sqlite3
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import parity_web_probe as fixture

WORK = fixture.WORK


async def main():
    mock = fixture.ThreadingHTTPServer(("127.0.0.1", 0), fixture.ModelFixture)
    threading.Thread(target=mock.serve_forever, daemon=True).start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    original = json.loads((ROOT / "config.local.json").read_text(encoding="utf-8-sig"))
    cfg = {"port": port, "test_budget_cny": 100,
           "planning": {"base_url": f"http://127.0.0.1:{mock.server_port}",
                        "model": original["planning"]["model"], "key_env": "VC_PROBE_KEY",
                        "input_cny_per_million": 12, "output_cny_per_million": 60,
                        "max_output_tokens": 1024}}
    config = WORK / "config.json"
    config.write_text(json.dumps(cfg), encoding="utf8")
    os.environ.update(VC_CONFIG=str(config), VC_DATA=str(WORK / "data"),
                      VC_PROBE_KEY="local-fixture-only")
    # Never attach this probe to a configured production database.
    os.environ.pop("VC_DATABASE_URL", None)
    sys.path.insert(0, str(ROOT / "server"))
    import uvicorn
    from local import bridge, db, projects
    from local.main import app

    source = ROOT / ".local/parity-web-7gn92e8g/data/control.sqlite3"
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as conn:
        captured = json.loads(conn.execute("SELECT body FROM events WHERE seq=202").fetchone()[0])
    assert captured["name"] == "d_build_status" and captured["result"]["status"] == "succeeded"
    result = captured["result"]
    expected = db.dump(result)
    assert len(expected) == 21116, "Captured fixture changed"
    (WORK / "original-tool-result.json").write_text(expected, encoding="utf8")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                         lifespan="off", log_level="error"))
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        if server_task.done():
            await server_task
        await asyncio.sleep(.05)
    spawn = asyncio.create_subprocess_exec
    overrides = {}

    async def configured_spawn(*argv, **kwargs):
        if "app-server" in argv:
            index = argv.index("app-server")
            extra = [part for key, value in overrides.items()
                     for part in ("-c", key + "=" + json.dumps(value))]
            argv = (*argv[:index], *extra, *argv[index:])
        return await spawn(*argv, **kwargs)

    bridge.asyncio.create_subprocess_exec = configured_spawn
    rows = []
    context = {"model_context_window": 256000, "model_auto_compact_token_limit": 230400}
    cases = [("baseline", {}), ("output_limit_only", {"tool_output_token_limit": 10000}),
             ("context_only", context), ("combined", {**context, "tool_output_token_limit": 10000})]
    try:
        for name, settings in cases:
            overrides = settings
            pid = projects.create(db.uid(), "isolated Codex config replay " + name)["id"]
            runner = bridge.AgentRunner(pid)
            calls = []

            async def replay(tool, args, call_id):
                assert tool == "d_build_status", tool
                calls.append({"tool": tool, "arguments": args, "call_id": call_id})
                return copy.deepcopy(result)

            runner.invoke = replay
            start = len(fixture.requests)
            with fixture.lock:
                fixture.steps.append(("d_build_status", {"buildId": result["id"]}))
            try:
                turn = await runner.turn("Replay the captured build status once.")
                async with asyncio.timeout(60):
                    while turn["turn_id"] not in runner.completed_turns:
                        await asyncio.sleep(.05)
                requests = fixture.requests[start:]
                assert len(requests) == 2 and len(calls) == 1, (len(requests), calls)
                outputs = [x for x in requests[1]["input"] if x.get("type") == "function_call_output"]
                assert len(outputs) == 1
                output = outputs[0]["output"]
                texts = [x["text"] for x in output if x.get("type") == "input_text"] if isinstance(output, list) else [output]
                forwarded = texts[-1]
                with db.transaction() as conn:
                    events = list(conn.execute(db.events.select().where(db.events.c.project == pid)).mappings())
                warnings = [json.loads(x["body"]) for x in events if x["kind"] == "warning"]
                usage = [json.loads(x["body"]) for x in events if x["kind"] == "thread/tokenUsage/updated"]
                assert usage
                assert not any("fallback metadata" in x.get("message", "") for x in warnings)
                row = {"case": name, "overrides": settings, "project": pid,
                       "original_chars": len(expected), "forwarded_chars": len(forwarded),
                       "exact_match": forwarded == expected, "truncated": "tokens truncated" in forwarded,
                       "warnings": warnings, "token_usage": usage}
                assert row["exact_match"] and not row["truncated"], row
                rows.append(row)
                case_dir = WORK / name
                case_dir.mkdir()
                for filename, value in [("model-requests.json", requests), ("backend-tool-call.json", calls),
                                        ("events.json", [dict(x) for x in events]), ("result.json", row)]:
                    (case_dir / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf8")
                print(json.dumps({k: row[k] for k in ("case", "original_chars", "forwarded_chars", "exact_match", "truncated")}), flush=True)
            finally:
                await runner.close()
        summary = {"codex": "0.163.0", "scope": "real Codex, MCP and gateway; replayed backend result and scripted model; no paid API",
                   "source": str(source), "source_event": 202, "context_values_are_test_inputs": True, "cases": rows}
        (WORK / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf8")
        print("Evidence: " + str(WORK / "summary.json"), flush=True)
    finally:
        bridge.asyncio.create_subprocess_exec = spawn
        server.should_exit = True
        await server_task
        await asyncio.to_thread(mock.shutdown)


if __name__ == "__main__":
    asyncio.run(main())

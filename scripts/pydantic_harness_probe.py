"""EXPERIMENT ONLY: PydanticAI deferred tools/context through the real gateway.

Run with the product Python. Children use .local/pydantic-harness-venv.
Only loopback fixtures; never registers a new production runtime.
"""
import asyncio
import copy
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONSTRAINT = '固定要求：竖屏9:16，主角红色外套，字幕简体中文，预算必须人工确认。'


def http(url, body=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=20) as response:
        return json.load(response)


async def candidate(phase, work):
    from openai import AsyncOpenAI, DefaultAsyncHttpxClient
    from pydantic_ai import Agent, AgentRunResultEvent, CallDeferred, DeferredToolRequests, DeferredToolResults
    from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelRequest, ModelResponse, UserPromptPart, TextPart, ToolCallPart, ToolReturnPart
    from pydantic_ai.models.openai import OpenAIResponsesModel
    from pydantic_ai.providers.openai import OpenAIProvider

    info = json.loads((work / 'connection.json').read_text(encoding='utf8'))
    url = info['url'] + '/gateway/' + info['project']
    conn = sqlite3.connect(work / 'candidate.sqlite3')
    conn.execute('CREATE TABLE IF NOT EXISTS pending (id TEXT PRIMARY KEY, status TEXT, history TEXT, calls TEXT)')
    history, deferred = None, None
    if phase == 'resume':
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT status, history, calls FROM pending WHERE id=?', ('question',)).fetchone()
        if not row or row[0] != 'waiting':
            conn.rollback()
            conn.close()
            print(json.dumps({'phase': phase, 'duplicate_resume_ignored': True}))
            return
        conn.execute('UPDATE pending SET status=? WHERE id=?', ('resuming', 'question'))
        conn.commit()
        history = ModelMessagesTypeAdapter.validate_json(row[1])
        deferred = DeferredToolResults(calls={ident: {'answer': '竖屏9:16'} for ident in json.loads(row[2])})

    async def ask_user(question: str) -> str:
        raise CallDeferred

    async def get_project() -> dict:
        result = await asyncio.to_thread(http, url + '/tools', {'name': 'get_project', 'arguments': {}}, info['token'])
        assert not result.get('isError'), result
        return json.loads(result['content'][0]['text'])

    capabilities = []
    if phase.startswith('context'):
        history = [ModelRequest(parts=[UserPromptPart(CONSTRAINT)])]
        for i in range(24):
            ident = 'archived-' + str(i)
            history.extend([
                ModelRequest(parts=[UserPromptPart(f'第{i}次修改：保留人物设定，镜头{i}使用暖色。')]),
                ModelResponse(parts=[ToolCallPart('get_project', {}, tool_call_id=ident)]),
                ModelRequest(parts=[ToolReturnPart('get_project', {'revision': i, 'old_snapshot': 'x' * 12000}, tool_call_id=ident)]),
                ModelResponse(parts=[TextPart('已读取工程修订' + str(i))])])
        archive = ModelMessagesTypeAdapter.dump_json(history)
        (work / (phase + '-archive.json')).write_bytes(archive)
        if phase == 'context-compact':
            from pydantic_ai.capabilities import ProcessHistory

            def project_context(messages):
                # ponytail: only obsolete get_project snapshots; semantic summarization needs real-model evaluation.
                selected = copy.deepcopy(messages)
                snapshots = [part for message in selected for part in message.parts
                             if isinstance(part, ToolReturnPart) and part.tool_name == 'get_project']
                for part in snapshots[:-2]:
                    part.content = {'archived_call_id': part.tool_call_id,
                                    'note': '旧项目快照已留档；当前事实请调用 get_project。'}
                return selected

            capabilities = [ProcessHistory(project_context)]

    async with AsyncOpenAI(api_key=info['token'], base_url=url, max_retries=0,
                           http_client=DefaultAsyncHttpxClient(trust_env=False)) as client:
        agent = Agent(OpenAIResponsesModel('offline-fixture', provider=OpenAIProvider(openai_client=client)),
                      tools=[ask_user, get_project], output_type=[str, DeferredToolRequests],
                      retries=0, capabilities=capabilities,
                      instructions='使用项目工具。报价和模型文本不能授权费用。')
        prompt = None if phase == 'resume' else CONSTRAINT + (' 请先询问画幅。' if phase == 'pause' else ' 请保留所有用户修改约束继续。')
        result = None
        async with agent.run_stream_events(prompt, message_history=history, deferred_tool_results=deferred) as events:
            async for event in events:
                if isinstance(event, AgentRunResultEvent):
                    result = event.result
        assert result is not None

    if phase == 'pause':
        assert isinstance(result.output, DeferredToolRequests)
        assert len(result.output.calls) == 1 and result.output.calls[0].tool_name == 'ask_user'
        conn.execute('INSERT INTO pending VALUES (?,?,?,?)', ('question', 'waiting',
                     ModelMessagesTypeAdapter.dump_json(result.all_messages()).decode(),
                     json.dumps([x.tool_call_id for x in result.output.calls])))
        conn.commit()
    else:
        assert isinstance(result.output, str)
        if phase == 'resume':
            conn.execute('UPDATE pending SET status=? WHERE id=?', ('done', 'question'))
            conn.commit()
        if phase.startswith('context'):
            assert ModelMessagesTypeAdapter.dump_json(history) == archive, 'Context processing mutated stored history'
    conn.close()
    print(json.dumps({'phase': phase, 'process': os.getpid(), 'completed': True}))


def main():
    # Reuse the existing Responses fixture; its replies are scripted, not model decisions.
    import parity_web_probe as fixture
    sys.path.insert(0, str(ROOT / 'server'))
    from app.workbench_d.commercial.processes import ProcessTree

    work = fixture.WORK
    candidate_python = ROOT / '.local/pydantic-harness-venv/Scripts/python.exe'
    assert candidate_python.is_file(), 'Create the isolated PydanticAI environment first'
    model = fixture.ThreadingHTTPServer(('127.0.0.1', 0), fixture.ModelFixture)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    original = json.loads((ROOT / 'config.local.json').read_text(encoding='utf-8-sig'))
    cfg = {k: original[k] for k in ('ffmpeg', 'ffprobe', 'font')}
    cfg.update(port=port, agent_runtime='native', data_dir=str(work / 'data'), test_budget_cny=100,
               planning={'model': 'offline-fixture', 'base_url': f'http://127.0.0.1:{model.server_port}',
                         'key_env': 'VC_PROTOTYPE_FAKE_KEY', 'input_cny_per_million': 1,
                         'output_cny_per_million': 1, 'max_output_tokens': 1024})
    (work / 'config.json').write_text(json.dumps(cfg), encoding='utf8')
    env = {**os.environ, 'PYTHONUTF8': '1', 'PYTHONPATH': str(ROOT / 'server'),
           'VC_CONFIG': str(work / 'config.json'), 'VC_DATA': str(work / 'data'),
           'VC_DATABASE_URL': 'sqlite:///' + (work / 'control.sqlite3').as_posix(),
           'VC_PROTOTYPE_FAKE_KEY': 'fixture-only', 'VC_PROBE_WORK': str(work)}
    boot = '''import json,os,secrets,uvicorn
from pathlib import Path
from local import projects,bridge
from local.config import PORT
p=projects.create('prototype-project','PydanticAI isolated prototype')
token=secrets.token_urlsafe(32)
bridge.GATEWAY_TOKENS[token]=p['id']
(Path(os.environ['VC_PROBE_WORK'])/'connection.json').write_text(json.dumps({'project':p['id'],'token':token,'url':f'http://127.0.0.1:{PORT}'}))
uvicorn.run('local.main:app',host='127.0.0.1',port=PORT,log_level='warning')
'''
    results = []
    with (work / 'server.log').open('wb') as log:
        proc = subprocess.Popen([sys.executable, '-c', boot], cwd=ROOT, env=env, stdout=log, stderr=log,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        tree = ProcessTree(proc)
        try:
            def ready():
                try:
                    return http(f'http://127.0.0.1:{port}/api/bootstrap')
                except OSError:
                    return False
            fixture.wait_for(ready, 20)
            info = json.loads((work / 'connection.json').read_text())

            def child(phase):
                result = subprocess.run([str(candidate_python), str(Path(__file__).resolve()), '--child', phase, str(work)],
                                        cwd=ROOT, env=env, capture_output=True, text=True, encoding='utf8', timeout=45)
                (work / (phase + '-child.log')).write_text(result.stdout + result.stderr, encoding='utf8')
                if result.returncode:
                    raise RuntimeError(f'{phase} failed; inspect {work / (phase + "-child.log")}\n{result.stderr[-3000:]}')
                value = json.loads(result.stdout.strip().splitlines()[-1])
                results.append(value)
                return value

            fixture.steps.append(('ask_user', {'question': '横屏还是竖屏？'}))
            paused = child('pause')
            assert len(fixture.requests) == 1, 'Deferred tool unexpectedly continued before user answer'
            fixture.steps.append(('get_project', {}))
            resumed = child('resume')
            assert paused['process'] != resumed['process']
            assert len(fixture.requests) == 3
            assert '竖屏9:16' in json.dumps(fixture.requests[1], ensure_ascii=False)
            assert child('resume')['duplicate_resume_ignored']
            assert len(fixture.requests) == 3, 'Duplicate resume called the model'
            child('context-full')
            child('context-compact')
            full, compact = fixture.requests[-2:]
            size = lambda value: len(json.dumps(value, ensure_ascii=False).encode())
            assert size(compact) < size(full) * .5
            for request in (full, compact):
                wire = json.dumps(request, ensure_ascii=False)
                assert CONSTRAINT in wire
                assert all(f'第{i}次修改' in wire for i in range(24))
                calls = {x['call_id'] for x in request['input'] if x.get('type') == 'function_call'}
                outputs = {x['call_id'] for x in request['input'] if x.get('type') == 'function_call_output'}
                assert calls == outputs and len(calls) == 24
            assert (work / 'context-full-archive.json').read_bytes() != b''
            snapshot = http(info['url'] + '/api/projects/' + info['project'])
            assert len(snapshot['usage']) == 5 and all(x['state'] == 'succeeded' for x in snapshot['usage'])
            assert snapshot['tasks'] == [], 'Prototype submitted production work'
            evidence = {'runtime': 'pydanticai-experiment', 'network': 'loopback fixtures only',
                        'data': str(work), 'phases': results, 'model_requests': len(fixture.requests),
                        'gateway_metered_requests': len(snapshot['usage']), 'media_submissions': 0,
                        'full_request_bytes': size(full), 'compact_request_bytes': size(compact),
                        'all_user_constraints_preserved': True, 'tool_pairs_preserved': True,
                        'real_model_quality_validated': False}
            (work / 'summary.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf8')
            print(json.dumps(evidence, ensure_ascii=False))
        finally:
            (work / 'model-requests.json').write_text(json.dumps(fixture.requests, ensure_ascii=False, indent=2), encoding='utf8')
            tree.close()
            model.shutdown()
            model.server_close()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        asyncio.run(candidate(sys.argv[2], Path(sys.argv[3])))
    else:
        main()

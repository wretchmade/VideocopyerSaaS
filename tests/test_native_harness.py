"""Exercise the real metered gateway and business tools with offline Responses streams."""
import asyncio
import io
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

import httpx
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('VC_DATA', tempfile.mkdtemp(prefix='vc-native-'))
sys.path.insert(0, str(ROOT / 'server'))
from local import bridge, commands, coordinator, db, gateway, projects
from local.native_harness import NativeRunner, read_history


def message(text='完成'):
    return {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': text}]}


def call(name, args, ident):
    return {'type': 'function_call', 'name': name, 'arguments': json.dumps(args), 'call_id': ident}


@pytest.fixture
def model(monkeypatch, tmp_path):
    requests = []
    replies = []
    monkeypatch.setitem(bridge.CONFIG, 'agent_runtime', 'native')
    monkeypatch.setitem(bridge.CONFIG, 'native_harness', {'max_model_requests': 8, 'max_context_bytes': 1000000})
    monkeypatch.setitem(bridge.CONFIG, 'planning', {'model': 'fixture', 'base_url': 'https://fixture.invalid/v1',
        'model_context_window': 1000000, 'input_cny_per_million': 1, 'output_cny_per_million': 1, 'max_output_tokens': 16})
    monkeypatch.setattr(gateway, 'planning_key', lambda: 'fixture-secret')
    for key in ('ffmpeg', 'ffprobe'):
        if bridge.CONFIG.get(key):
            monkeypatch.setenv('D_' + key.upper(), bridge.CONFIG[key])
    monkeypatch.setenv('D_HEAVY_ROOT', str(tmp_path / 'resources'))
    original = httpx.AsyncClient

    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        reply = replies.pop(0) if replies else [message()]
        if callable(reply):
            return reply(body)
        events = [{'type': 'response.output_text.delta', 'delta': '完成'}]
        events.append({'type': 'response.completed', 'response': {'id': 'fixture-' + str(len(requests)),
            'status': 'completed', 'output': reply, 'usage': {'input_tokens': 10, 'output_tokens': 10}}})
        data = ''.join('data: ' + json.dumps(e, ensure_ascii=False) + '\n\n' for e in events)
        return httpx.Response(200, text=data, headers={'content-type': 'text/event-stream'})

    monkeypatch.setattr(gateway.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))

    async def no_subprocess(*args, **kwargs):
        raise AssertionError('native harness must not start an Agent subprocess')
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', no_subprocess)
    yield requests, replies


def new():
    return projects.create(db.uid(), 'native harness offline test')['id']


async def finish(runner, text='开始', files=None):
    result = await runner.turn(text, files)
    await asyncio.wait_for(runner.task, 5)
    return result['turn_id']


def test_real_tool_loop_and_full_result_and_images(model, monkeypatch):
    requests, replies = model
    pid = new()
    image = io.BytesIO()
    Image.new('RGB', (16, 16), 'red').save(image, format='PNG')
    upload = projects.add_file(pid, 'sample.png', image.getvalue())
    # The large text comes from a real bundled resource, not an Agent-side fixture.
    resource = 'references/tools.json'
    replies.extend([[call('read_skill', {'path': resource}, 'read')],
                    [call('inspect_media', {'file_id': upload['id']}, 'image')], [message()]])

    async def check():
        runner = bridge.runner(pid)
        assert isinstance(runner, NativeRunner)
        try:
            tid = await finish(runner, files=[upload['id']])
            assert len(requests) == 3
            assert requests[0]['input'][0]['content'][1]['type'] == 'input_image'
            result = next(i['output'] for i in requests[1]['input'] if i.get('call_id') == 'read' and i['type'] == 'function_call_output')
            assert 'truncated' not in result and len(result) > 20000
            # Exact tool result must reach the model without an Agent truncation layer.
            assert result == db.dump(commands.dispatch(pid, 'read_skill', {'path': resource}))
            image_result = next(i['output'] for i in requests[2]['input'] if i.get('call_id') == 'image' and i['type'] == 'function_call_output')
            assert image_result[0]['type'] == 'input_image'
            assert image_result[0]['image_url'].startswith('data:image/jpeg;base64,')
            assert 'coding agent' not in requests[0]['instructions']
            assert 'feishu-daily-report' not in json.dumps(requests)
            turns = (await runner.read_turn(runner.thread))['thread']['turns']
            assert turns[0]['id'] == tid and turns[0]['status'] == 'completed'
            with db.transaction() as c:
                assert len(db.all(c, 'usage', pid)) == 3
                assert all(x['state'] == 'succeeded' for x in db.all(c, 'usage', pid))
        finally:
            await runner.close()
            bridge.RUNNERS.pop(pid, None)
    asyncio.run(check())


def test_multiple_calls_create_quote_cannot_authorize(model):
    requests, replies = model
    pid = new()
    image = io.BytesIO()
    Image.new('RGB', (64, 64), 'red').save(image, format='PNG')
    upload = projects.add_file(pid, 'sample.png', image.getvalue())
    document = {'width': 64, 'height': 64, 'frames': 3,
        'assets': [{'id': 'image', 'kind': 'image', 'path': 'file:' + upload['id'],
                    'sha256': upload['sha256'], 'license': 'fixture', 'source': 'fixture'}],
        'layers': [{'id': 'image-layer', 'kind': 'image', 'asset': 'image', 'end': 3, 'width': 64, 'height': 64}]}
    replies.append([call('d_create_project', {'commandId': 'native-create-' + pid, 'name': 'fixture', 'document': document}, 'create')])
    replies.append([call('request_production', {}, 'quote'), call('unknown_tool', {}, 'bad')])
    replies.append([message()])

    async def check():
        runner = NativeRunner(pid)
        try:
            await finish(runner)
            assert len(requests) == 3
            outputs = [i for i in requests[2]['input'] if i.get('type') == 'function_call_output']
            assert {i['call_id'] for i in outputs} == {'create', 'quote', 'bad'}
            assert '未知业务工具' in outputs[-1]['output']
            assert 'error' not in json.loads(outputs[1]['output']), outputs[1]['output']
            with db.transaction() as c:
                assert db.get(c, 'project', pid)['native_project']
                assert db.all(c, 'quote', pid), outputs
                assert db.all(c, 'task', pid) == []
            core = projects.snapshot(pid)['native_project']
            value = await runner.invoke('d_submit_build', {'projectId': core, 'revision': 0, 'commandId': db.uid()}, 'no-approval')
            assert value['status'] == 'waiting_user'
            with db.transaction() as c:
                assert db.all(c, 'task', pid) == []
        finally:
            await runner.close()
    asyncio.run(check())


def test_ask_answer_and_stop_waiting_question(model):
    requests, replies = model

    async def wait_question(runner):
        for _ in range(100):
            if runner.requests:
                return next(iter(runner.requests))
            await asyncio.sleep(.01)
        raise AssertionError('Question was not emitted')

    async def check():
        pid = new()
        runner = NativeRunner(pid)
        try:
            replies.extend([[call('ask_user', {'question': '横屏还是竖屏？'}, 'ask')], [message()]])
            await runner.turn('开始')
            qid = await wait_question(runner)
            with pytest.raises(ValueError):
                await runner.answer('another-project-question', '允许')
            await runner.answer(qid, '竖屏')
            await asyncio.wait_for(runner.task, 5)
            assert '竖屏' in requests[-1]['input'][-1]['output']
            replies.append([call('ask_user', {'question': '风格？'}, 'ask-2')])
            await runner.turn('再问')
            qid = await wait_question(runner)
            count = len(requests)
            await runner.stop()
            await asyncio.wait_for(runner.task, 5)
            assert len(requests) == count
            with db.transaction() as c:
                assert db.get(c, 'question', qid, pid)['status'] == 'cancelled'
                assert db.get(c, 'project', pid)['status'] == 'interrupted'
        finally:
            await runner.close()
    asyncio.run(check())


def test_restart_reads_completed_turn_and_does_not_replay_unknown(model):
    requests, replies = model
    pid = new()

    async def check():
        runner = NativeRunner(pid)
        tid = await finish(runner)
        thread = runner.thread
        await runner.close()
        resumed = NativeRunner(pid)
        try:
            await resumed.start()
            assert resumed.thread == thread
            assert (await resumed.read_turn(thread))['thread']['turns'][0]['id'] == tid
            with db.transaction() as c:
                turn = db.get(c, 'native_turn', tid, pid)
                turn['status'] = 'in_progress'
                db.put(c, 'native_turn', tid, turn, pid, True)
            before = len(requests)
            await resumed.start()
            assert resumed.thread != thread and len(requests) == before
            assert read_history(pid, thread)['thread']['turns'][0]['status'] == 'in_progress'
            with pytest.raises(ValueError):
                read_history(new(), thread)
        finally:
            await resumed.close()
    asyncio.run(check())


@pytest.mark.parametrize('failure', ['http', 'disconnect', 'incomplete', 'duplicate', 'invalid-json'])
def test_model_failure_never_retries_or_executes_unfinished_tools(model, failure):
    requests, replies = model
    pid = new()
    command = call('d_create_project', {'commandId': db.uid(), 'document': {}}, 'same')
    if failure == 'http':
        replies.append(lambda body: httpx.Response(500, json={'error': {'code': 'InternalError'}}))
    elif failure == 'duplicate':
        replies.append([command, command])
    else:
        kind = 'response.incomplete' if failure == 'incomplete' else 'response.output_item.done'
        data = 'invalid json' if failure == 'invalid-json' else json.dumps({'type': kind, 'item': command})
        replies.append(lambda body: httpx.Response(200, text='data: ' + data + '\n\n'))

    async def check():
        runner = NativeRunner(pid)
        try:
            await finish(runner)
            assert len(requests) == 1
            with db.transaction() as c:
                project = db.get(c, 'project', pid)
                assert project['status'] == 'failed' and not project.get('native_project')
                assert len(db.all(c, 'usage', pid)) == 1
        finally:
            await runner.close()
    asyncio.run(check())


def test_context_and_turn_limits_do_not_silently_drop_history(model, monkeypatch):
    requests, replies = model
    pid = new()

    async def check():
        runner = NativeRunner(pid)
        try:
            monkeypatch.setitem(bridge.CONFIG, 'native_harness', {'max_context_bytes': 100})
            await finish(runner)
            assert requests == []
            assert runner.history[0]['content'][0]['text'] == '开始'
            monkeypatch.setitem(bridge.CONFIG, 'native_harness', {'max_model_requests': 1})
            replies.append([call('get_project', {}, 'project')])
            await finish(runner)
            assert len(requests) == 1
            with db.transaction() as c:
                assert db.get(c, 'project', pid)['status'] == 'failed'
        finally:
            await runner.close()
    asyncio.run(check())


def test_coordinator_reconciles_native_without_starting_a_runtime(model, monkeypatch):
    requests, replies = model
    pid = new()

    async def check():
        runner = NativeRunner(pid)
        ident = 'user:' + db.uid()
        with db.transaction() as c:
            commands.enqueue(c, pid, ident, '测试恢复', 0)
        runner.inbox_id = ident
        await finish(runner)
        await runner.close()
        with db.transaction() as c:
            inbox = db.get(c, 'agent_inbox', ident, pid)
            inbox.update(status='dispatched', reconcile_pending=True)
            db.put(c, 'agent_inbox', ident, inbox, pid, True)
        monkeypatch.setattr(bridge, 'runner', lambda pid: pytest.fail('Read-only recovery must not start an Agent'))
        before = len(requests)
        await coordinator.reconcile(inbox)
        with db.transaction() as c:
            assert db.get(c, 'agent_inbox', ident, pid)['status'] == 'done'
        assert len(requests) == before
    asyncio.run(check())


@pytest.mark.parametrize('stage', ['connect', 'stream'])
def test_stop_during_model_request_keeps_unknown_cost_reserved(model, monkeypatch, stage):
    async def check():
        entered = asyncio.Event()
        closed = []

        class WaitingStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                entered.set()
                await asyncio.Event().wait()
                yield b''

            async def aclose(self):
                closed.append(True)

        async def handle(request):
            if stage == 'connect':
                entered.set()
                await asyncio.Event().wait()
            return httpx.Response(200, stream=WaitingStream())

        # Capture httpx's actual class, bypassing the offline fixture factory.
        original = httpx._client.AsyncClient
        monkeypatch.setattr(gateway.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
        runner = NativeRunner(new())
        try:
            await runner.turn('等待中的请求')
            await asyncio.wait_for(entered.wait(), 3)
            await runner.stop()
            await asyncio.wait_for(runner.task, 3)
            with db.transaction() as c:
                usage = db.all(c, 'usage', runner.pid)
                assert len(usage) == 1 and usage[0]['state'] == 'reconciling'
                assert db.get(c, 'project', runner.pid)['status'] == 'interrupted'
            if stage == 'stream':
                assert closed
        finally:
            await runner.close()
    asyncio.run(check())


def test_stop_waits_for_started_tool_receipt_before_another_turn(model, monkeypatch):
    requests, replies = model
    entered = threading.Event()
    release = threading.Event()

    def slow_dispatch(pid, name, args):
        entered.set()
        assert release.wait(4)
        return {'completed': True}
    monkeypatch.setattr(commands, 'dispatch', slow_dispatch)
    replies.append([call('d_capabilities', {}, 'slow')])

    async def check():
        runner = NativeRunner(new())
        try:
            await runner.turn('开始')
            assert await asyncio.to_thread(entered.wait, 3)
            await runner.stop()
            assert runner.busy
            with pytest.raises(ValueError, match='仍在运行'):
                await runner.turn('不要并发执行')
            release.set()
            await asyncio.wait_for(runner.task, 3)
            assert len(requests) == 1 and not runner.busy
            assert runner.history[-1]['type'] == 'function_call_output'
            assert 'completed' in runner.history[-1]['output']
        finally:
            release.set()
            await runner.close()
    asyncio.run(check())


def test_two_projects_run_in_one_event_loop_without_shared_history(model):
    requests, replies = model

    async def check():
        runners = [NativeRunner(new()), NativeRunner(new())]
        try:
            await asyncio.gather(*(finish(r, text) for r, text in zip(runners, ['first-project-only', 'second-project-only'])))
            assert len(requests) == 2
            assert runners[0].thread != runners[1].thread
            assert 'second-project-only' not in db.dump(runners[0].history)
            assert 'first-project-only' not in db.dump(runners[1].history)
        finally:
            await asyncio.gather(*(r.close() for r in runners))
    asyncio.run(check())


def test_runtime_switch_preserves_old_thread_and_starts_from_snapshot(model):
    async def check():
        pid = new()
        with db.transaction() as c:
            project = db.get(c, 'project', pid)
            project.update(thread_id='old-codex-thread', tool_registry_hash='old')
            db.put(c, 'project', pid, project, pid, True)
        runner = NativeRunner(pid)
        try:
            await runner.start()
            assert runner.thread.startswith('native:')
            with db.transaction() as c:
                assert db.get(c, 'project', pid)['prior_threads'] == ['old-codex-thread']
            assert '会话迁移' in runner.history[0]['content'][0]['text']
        finally:
            await runner.close()
    asyncio.run(check())

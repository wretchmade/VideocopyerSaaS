"""Offline regressions for the HTTP and provider credential boundaries."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('VC_DATA', tempfile.mkdtemp(prefix='vc-security-'))
sys.path.insert(0, str(ROOT / 'server'))

import pytest
from fastapi.testclient import TestClient
from local import db, gateway
from local.main import app


@pytest.mark.parametrize('payload', [
    {'error': {'code': 'Authorization: Bearer private-test-key'}},
    {'error': {'code': 'https://provider.invalid/?token=private-test-key'}},
    {'error': {'code': 'private_test_key'}},
    {'error': {'code': {'api_key': 'private_test_key'}}},
    {'error': {'code': 'X' * 101}},
    {'error': None},
    [],
])
def test_provider_error_does_not_echo_secrets(payload):
    assert gateway.provider_error_code(json.dumps(payload), 'private_test_key') == 'provider_error'


def test_provider_error_preserves_short_code():
    assert gateway.provider_error_code('{"error":{"code":"RateLimitExceeded"}}', 'private_test_key') == 'RateLimitExceeded'
    assert gateway.provider_error_code(b'not json', 'private_test_key') == 'provider_error'


@pytest.mark.parametrize('endpoint', ['responses', 'tools'])
def test_gateway_rejects_absent_and_cross_project_tokens(endpoint, monkeypatch):
    monkeypatch.setitem(gateway.GATEWAY_TOKENS, 'test-project-token', 'project-a')
    client = TestClient(app, base_url='http://127.0.0.1:8765')
    path = '/gateway/project-b/' + endpoint
    assert client.post(path, json={}).status_code == 403
    assert client.post(path, json={}, headers={'Authorization': 'Bearer test-project-token'}).status_code == 403


def test_provider_error_is_redacted_in_http_and_ledger(monkeypatch):
    import httpx

    secret = 'private_test_key'
    pid = db.uid()
    monkeypatch.setitem(gateway.GATEWAY_TOKENS, 'error-test-token', pid)
    monkeypatch.setattr(gateway, 'planning_key', lambda: secret)
    monkeypatch.setitem(gateway.CONFIG, 'planning', {
        'base_url': 'https://provider.invalid/v1', 'model': 'offline-test',
        'input_cny_per_million': 1, 'output_cny_per_million': 1,
        'max_output_tokens': 10,
    })
    transport = httpx.MockTransport(lambda request: httpx.Response(
        401, json={'error': {'code': secret}}))
    original_client = httpx.AsyncClient
    monkeypatch.setattr(gateway.httpx, 'AsyncClient', lambda **kwargs: original_client(transport=transport, **kwargs))
    client = TestClient(app, base_url='http://127.0.0.1:8765')
    response = client.post('/gateway/' + pid + '/responses', json={'input': []},
                           headers={'Authorization': 'Bearer error-test-token'})
    assert response.status_code == 401
    assert response.json()['error']['code'] == 'provider_error'
    assert secret not in response.text
    with db.transaction() as c:
        usage = db.all(c, 'usage', pid)
    assert len(usage) == 1
    assert usage[0]['error'] == 'provider_error'
    assert usage[0]['state'] == 'released'


@pytest.mark.parametrize('stage', ['connect', 'stream'])
def test_cancelled_request_keeps_pool_and_unknown_cost(monkeypatch, stage):
    import asyncio
    import httpx

    pid, token = db.uid(), db.uid()
    monkeypatch.setitem(gateway.GATEWAY_TOKENS, token, pid)
    monkeypatch.setattr(gateway, 'planning_key', lambda: 'offline-key')
    monkeypatch.setitem(gateway.CONFIG, 'planning', {
        'base_url': 'https://fixture.invalid', 'model': 'offline',
        'input_cny_per_million': 1, 'output_cny_per_million': 1, 'max_output_tokens': 8})
    original = httpx.AsyncClient

    async def check():
        entered = asyncio.Event()
        closed = []
        count = 0

        class WaitingStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                entered.set()
                await asyncio.Event().wait()
                yield b''

            async def aclose(self):
                closed.append(True)

        async def handle(request):
            nonlocal count
            count += 1
            if count == 1:
                if stage == 'connect':
                    entered.set()
                    await asyncio.Event().wait()
                return httpx.Response(200, stream=WaitingStream())
            return httpx.Response(200, text='data: {"type":"response.completed","response":{"usage":{}}}\n\n')

        monkeypatch.setattr(gateway.httpx, 'AsyncClient',
                            lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))

        async def request():
            response = await gateway.agent_response(pid, token, b'{"input":[]}')
            async for _ in response.body_iterator:
                pass

        async with gateway.connection_pool() as client:
            task = asyncio.create_task(request())
            await asyncio.wait_for(entered.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not client.is_closed
            if stage == 'stream':
                assert closed
            await request()
            assert count == 2
            with db.transaction() as c:
                usage = db.all(c, 'usage', pid)
            assert [r['state'] for r in usage] == ['reconciling', 'succeeded']
        assert client.is_closed and gateway._client is None

    asyncio.run(check())


def test_gateway_lifespan_owns_resources(monkeypatch):
    import asyncio
    from unittest.mock import Mock
    from local import main

    worker = Mock()

    def start(*args, **kwargs):
        assert gateway._client is not None and not gateway._client.is_closed
        return worker

    monkeypatch.setattr(main.production, 'setup_media', lambda: None)
    monkeypatch.setattr(main.subprocess, 'Popen', start)
    monkeypatch.setattr(main.bridge, 'RUNNERS', {})

    async def check():
        async with main.lifespan(main.app):
            client = gateway._client
        assert client.is_closed and gateway._client is None
        worker.terminate.assert_called_once()
        launch = Mock()
        monkeypatch.setattr(main.subprocess, 'Popen', launch)
        monkeypatch.setattr(gateway, 'new_client', Mock(side_effect=RuntimeError('fixture startup failure')))
        with pytest.raises(RuntimeError, match='fixture startup failure'):
            async with main.lifespan(main.app):
                pass
        launch.assert_not_called()

    asyncio.run(check())

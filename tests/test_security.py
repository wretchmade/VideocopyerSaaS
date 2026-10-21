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

"""Offline real-socket gateway check. Run with --baseline before the pool change."""
import asyncio
import json
import os
import socket
import sys
import tempfile
import threading
import time
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    work = Path(tempfile.mkdtemp(prefix='gateway-pool-', dir=ROOT / '.local'))
    requests = []

    class Provider(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def setup(self):
            super().setup()
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append((self.client_address, self.headers.get('Authorization'), self.headers.get('Cookie')))
            status = body['input'][0].get('status', 200)
            event = {'type': 'response.completed', 'response': {
                'id': str(len(requests)), 'usage': {'input_tokens': 1, 'output_tokens': 1}}}
            content = ('data: ' + json.dumps(event) + '\n\n').encode() if status == 200 else b'{"error":{"code":"FixtureError"}}'
            self.send_response(status)
            self.send_header('Content-Type', 'text/event-stream' if status == 200 else 'application/json')
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Set-Cookie', 'provider_session=must-not-cross-requests')
            self.end_headers()
            self.wfile.write(content)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    config = work / 'config.json'
    config.write_text(json.dumps({'data_dir': str(work / 'data'), 'test_budget_cny': 100,
        'planning': {'base_url': f'http://127.0.0.1:{server.server_port}', 'model': 'offline',
                     'key_env': 'VC_POOL_FAKE_KEY', 'input_cny_per_million': 1,
                     'output_cny_per_million': 1, 'max_output_tokens': 8}}), encoding='utf8')
    os.environ.update(VC_CONFIG=str(config), VC_DATA=str(work / 'data'),
                      VC_DATABASE_URL='sqlite:///' + (work / 'control.sqlite3').as_posix())
    sys.path.insert(0, str(ROOT / 'server'))
    from fastapi import HTTPException
    from local import db, gateway

    async def check():
        samples = []
        pooled = '--baseline' not in sys.argv
        for _ in range(3):
            start = len(requests)
            started = time.perf_counter()
            context = getattr(gateway, 'connection_pool', nullcontext)() if pooled else nullcontext()
            async with context as client:
                for i, status in enumerate([200] * 8 + [401, 500, 200]):
                    pid, token = db.uid(), db.uid()
                    gateway.GATEWAY_TOKENS[token] = pid
                    os.environ['VC_POOL_FAKE_KEY'] = 'fixture-' + str(i)
                    before = len(requests)
                    response = await gateway.agent_response(pid, token, json.dumps({'input': [{'status': status}]}).encode())
                    if status == 200:
                        async for _ in response.body_iterator:
                            pass
                    assert response.status_code == status
                    assert len(requests) == before + 1, 'Unexpected automatic retry'
                    assert requests[-1][1] == 'Bearer fixture-' + str(i), 'Request credential leaked across calls'
                    assert requests[-1][2] is None, 'Provider cookie leaked across calls'
                    with db.transaction() as c:
                        usage = db.all(c, 'usage', pid)
                    expected = 'succeeded' if status == 200 else 'released' if status < 500 else 'reconciling'
                    assert len(usage) == 1 and usage[0]['state'] == expected
                    try:
                        await gateway.agent_response('other-project', token, b'{}')
                    except HTTPException as exc:
                        assert exc.status_code == 403
                    else:
                        raise AssertionError('Cross-project token accepted')
                    assert len(requests) == before + 1
                    gateway.GATEWAY_TOKENS.pop(token)
                    if client is not None:
                        assert not client.is_closed, 'A response closed the shared pool'
            if client is not None:
                assert client.is_closed, 'Pool leaked after lifecycle shutdown'
            connections = len({x[0] for x in requests[start:]})
            sample = {'requests': len(requests) - start, 'tcp_connections': connections,
                      'elapsed_seconds': round(time.perf_counter() - started, 4)}
            samples.append(sample)
        evidence = {'mode': 'pooled' if pooled else 'baseline', 'samples': samples,
                    'network': 'loopback HTTP/1.1 only', 'data': str(work)}
        (work / 'summary.json').write_text(json.dumps(evidence, indent=2), encoding='utf8')
        print(json.dumps(evidence))
        assert all(s['tcp_connections'] == (1 if pooled else s['requests']) for s in samples), 'Connection reuse regression'

    try:
        asyncio.run(check())
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()

"""Planning settings must reach Codex as root TOML keys, not provider keys."""
import asyncio
import json
import os
import sys
import tempfile
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('VC_DATA', tempfile.mkdtemp(prefix='vc-codex-config-'))
sys.path.insert(0, str(ROOT / 'server'))
from local import bridge, db, projects


def test_model_settings_validate_limits_and_catalog(tmp_path):
    from local.bridge import model_settings
    assert model_settings({'model': 'unknown'}) == {'tool_output_token_limit': 10000}
    for key in ('model_context_window', 'model_auto_compact_token_limit', 'tool_output_token_limit'):
        for value in (0, -1, True, '10000', 1.5):
            with pytest.raises(ValueError, match=key):
                model_settings({key: value})
    with pytest.raises(ValueError, match='model_auto_compact_token_limit'):
        model_settings({'model_context_window': 100000, 'model_auto_compact_token_limit': 95000})
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps({'models': [{'slug': 'custom', 'context_window': 100000}]}))
    with pytest.raises(ValueError, match='model'):
        model_settings({'model': 'other', 'model_catalog_json': str(path)})
    with pytest.raises(ValueError, match='model_context_window'):
        model_settings({'model': 'custom', 'model_catalog_json': str(path), 'model_context_window': 200000})


def test_codex_loads_planning_profile_without_fallback(monkeypatch, tmp_path):
    # A real process checks catalog compatibility and TOML placement without paid requests.
    planning = {'model': 'doubao-seed-2-1-pro-260915',
                'model_context_window': 1024000, 'model_auto_compact_token_limit': 900000,
                'tool_output_token_limit': 10000,
                'model_catalog_json': str(tmp_path / 'codex-doubao-seed-2-1-pro-260915.json')}
    monkeypatch.setitem(bridge.CONFIG, 'planning', planning)
    monkeypatch.setitem(bridge.CONFIG, 'agent_transport', 'dynamic')
    monkeypatch.setattr(bridge, 'DATA', tmp_path)

    async def check():
        pid = projects.create(db.uid(), 'offline profile startup')['id']
        with db.transaction() as c:
            project=db.get(c,'project',pid)
            project.update(thread_id='native:prior-runtime',tool_registry_hash='old-native-tools')
            db.put(c,'project',pid,project,pid,True)
        runner = bridge.AgentRunner(pid)
        try:
            await runner.start()
            config = tomllib.loads((tmp_path / 'agents' / pid / 'config.toml').read_text(encoding='utf8'))
            assert config['model_context_window'] == 1024000
            assert config['model_auto_compact_token_limit'] == 900000
            assert config['tool_output_token_limit'] == 10000
            assert Path(config['model_catalog_json']).is_absolute()
            with db.transaction() as c:
                events = list(c.execute(db.events.select().where(db.events.c.project == pid)).mappings())
            assert not any('fallback metadata' in e['body'] for e in events)
            assert not any(e['kind'] == 'usage/reserved' for e in events)
            with db.transaction() as c:
                assert db.get(c,'project',pid)['prior_threads']==['native:prior-runtime']
                assert db.get(c,'project',pid)['agent_runtime']=='codex'
        finally:
            await runner.close()
    asyncio.run(check())

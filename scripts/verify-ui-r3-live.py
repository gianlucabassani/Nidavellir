#!/usr/bin/env python3
"""UI-R3 real Docker/browser/MCP acceptance; only this invocation's arenas are destroyed.

Start docker-compose.nv06.yml with project nidavellir-ui-r3 and its gateway first.
Set NV_PLAYWRIGHT_MODULE and optionally NV_CHROMIUM_PATH for the browser harness.
New evidence paths refuse overwrite. Caller removes the isolated stack afterward.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('nv06_gate', ROOT / 'scripts/verify-nv06-live.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
gate.COMPOSE = ('docker', 'compose', '-p', 'nidavellir-ui-r3', '-f', 'docker-compose.nv06.yml')

MCP_PROGRAM = r'''
import anyio,json,os
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
async def main():
    async with streamablehttp_client('http://127.0.0.1:9000/mcp') as streams:
        async with ClientSession(*streams[:2]) as session:
            await session.initialize()
            names={tool.name for tool in (await session.list_tools()).tools}
            assert 'compare_http_transactions' in names
            args={'arena_id':os.environ['R3_ARENA'],'digest':os.environ['R3_OWNED'],
                  'path':'/protected/B','headers':{'X-Request-ID':'r3mcp'+os.environ['R3_TAG']},
                  'credential_source_digest':os.environ['R3_OWNED'],'credential_header_names':['Authorization']}
            result=await session.call_tool('replay_http_transaction',arguments=args)
            assert not result.isError,result
            value=result.structuredContent or json.loads(next(x.text for x in result.content if x.type=='text'))
            assert value['status']==403,value
            args={'arena_id':os.environ['R3_ARENA'],'left':os.environ['R3_OWNED'],'right':value['transaction_digest']}
            result=await session.call_tool('compare_http_transactions',arguments=args)
            assert not result.isError,result
            comparison=result.structuredContent or json.loads(next(x.text for x in result.content if x.type=='text'))
            assert comparison['left']['response']['status']==200
            assert comparison['right']['response']['status']==403
            assert comparison['complete'] and comparison['captured_body_equal'] is False
            print('R3_MCP='+json.dumps({'comparison':comparison,'replay_digest':value['transaction_digest']}))
anyio.run(main)
'''


def main():
    tag = datetime.now(timezone.utc).strftime('%Y-%m-%d-') + uuid.uuid4().hex[:8]
    output = ROOT / f'docs/verification/ui-r3-live-{tag}.json'
    with output.open('x') as handle:
        json.dump({'status': 'started', 'date': tag}, handle)
    report = {'schema': 'nidavellir/ui-r3-live/v1', 'date': tag, 'status': 'running'}
    try:
        gate.run('docker', 'build', '-t', 'nidavellir/nv06-authz:acceptance', 'cyber-range/fixtures/nv06-authz')
        image = gate.run('docker', 'image', 'inspect', 'nidavellir/nv06-authz:acceptance', '--format', '{{.Id}}').stdout.strip()
        base = gate.run('docker', 'image', 'inspect', 'python:3.11.14-alpine', '--format', '{{.Id}}').stdout.strip()
        report['fixture_image'] = image
        scenario = {
            'schema': 'nidavellir/v3', 'name': 'UI-R3 two-account calibration',
            'requires': {'provider_class': 'container'}, 'network': {'segments': [{'name': 'lab'}]},
            'nodes': [
                {'name': 'target', 'role': 'victim', 'image': image, 'segments': ['lab'], 'ports': [8080]},
                {'name': 'attacker', 'role': 'attacker', 'image': base, 'segments': ['lab'],
                 'entrypoint': True, 'command': 'sleep infinity'}],
            'agents': [{'stance': 'attacker', 'node': 'attacker'}],
            'lifecycle': {'readiness': {'type': 'http', 'node': 'target', 'port': 8080,
                'path': '/health', 'expected_status': 200, 'timeout_seconds': 20}},
        }
        gate.run(*gate.COMPOSE, 'exec', '-T', 'orchestrator', 'python', '-c',
                 "from database import Database; from auth import hash_api_key; "
                 "db=Database(); key=hash_api_key('nv06-agent-key'); "
                 "db.create_api_key(key,'nv06-agent','agent') if db.get_api_key(key) is None else None")
        sid = 'ui-r3-' + tag[-8:]
        gate.api('POST', '/scenarios', {'id': sid, 'spec': scenario})
        arena = gate.api('POST', '/deploy', {'scenario': sid, 'instance_id': 'ui-r3-live',
            'provider': 'docker-local', 'engagement_purpose': 'calibration', 'participant_mode': 'agent',
            'engagement_time_box_seconds': 900})['instance_id']
        gate.ARENAS.append(arena)
        report['arena'] = arena
        gate.wait('/status/' + arena, lambda value: value.get('status') == 'active')
        gate.bind(arena)
        gate.api('POST', f'/arenas/{arena}/budget/policy', {
            'action_cap': 12, 'deadline': (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            'reason': 'UI-R3 bounded live acceptance'})
        owned = gate.action(arena, '/protected/A', 'r3owned' + tag[-8:])['transaction_digest']
        owner = gate.api('POST', f'/arenas/{arena}/http/request', {
            'node': 'target', 'path': '/protected/B', 'method': 'GET',
            'headers': {'Authorization': 'Bearer token-b-operator', 'X-Request-ID': 'r3owner' + tag[-8:]}})['transaction_digest']
        report.update(owned=owned, owner=owner)
        config = ROOT / f'data/ui-r3-browser-{tag}.json'
        config.parent.mkdir(exist_ok=True)
        config.write_text(json.dumps({'arena': arena, 'owned': owned, 'owner': owner, 'output': str(output) + '.browser.json'}))
        env = {**os.environ, 'NV_R3_CONFIG': str(config)}
        subprocess.run(['node', 'scripts/ui-r3-browser-check.cjs'], cwd=ROOT, env=env, check=True)
        browser = json.loads(Path(str(output) + '.browser.json').read_text())
        report['browser'] = browser
        report['groups'] = gate.api('GET', f'/arenas/{arena}/http/request-groups')['groups']
        assert len(report['groups']) == 2
        assert 'token-' not in json.dumps(report['groups'])
        assert gate.api('GET', f'/arenas/{arena}/http/request-groups', key=gate.AGENT_KEY, expected=(403,))['status'] == 403
        assert gate.api('GET', f'/arenas/{arena}/http/comparison?left={owned}&right={owner}', key=gate.AGENT_KEY, expected=(403,))['status'] == 403
        assert gate.api('GET', f'/arenas/wrong-arena/http/comparison?left={owned}&right={owner}', expected=(404,))['status'] == 404
        pairs = [(owned, browser['denied']), (owned, browser['changed_account'])]
        before = gate.api('GET', f'/arenas/{arena}/budget')
        report['comparisons'] = [gate.api('GET', f'/arenas/{arena}/http/comparison?left={a}&right={b}') for a,b in pairs]
        assert gate.api('GET', f'/arenas/{arena}/budget') == before
        report['budget_unchanged_by_comparison'] = before
        mcp = gate.run(*gate.COMPOSE, 'exec', '-T', '-e', f'R3_ARENA={arena}', '-e', f'R3_OWNED={owned}',
            '-e', f'R3_TAG={tag[-8:]}', 'agent-gateway', 'python', '-c', MCP_PROGRAM).stdout
        report['mcp'] = json.loads(next(line.split('=',1)[1] for line in mcp.splitlines() if line.startswith('R3_MCP=')))
        trace = gate.run(*gate.COMPOSE, 'exec', '-T', 'agent-gateway', 'cat', f'/app/traces/{arena}.jsonl').stdout
        assert all(secret not in trace for secret in ('token-a-public', 'token-b-operator', 'private-A', 'private-B'))
        report['trace_metadata_only'] = True
        gate.api('POST', f'/arenas/{arena}/stop', {'reason': 'UI-R3 stop refusal proof', 'idempotency_key': 'r3stop' + tag[-8:]})
        refused = gate.api('POST', f'/arenas/{arena}/http/transactions/{owned}/replay', {'path': '/protected/B'}, expected=(423,))
        report['stopped_replay_status'] = refused['status']
        # Operator evidence reads still work while stopped and after arena teardown.
        assert gate.api('GET', f'/arenas/{arena}/http/comparison?left={pairs[0][0]}&right={pairs[0][1]}') == report['comparisons'][0]
        gate.api('DELETE', '/destroy/' + arena, expected=(200,202))
        gate.wait('/status/' + arena, lambda value: value.get('status') == 'destroyed')
        assert gate.api('GET', f'/arenas/{arena}/http/request-groups')['groups'] == report['groups']
        for pair, expected in zip(pairs, report['comparisons']):
            assert gate.api('GET', f'/arenas/{arena}/http/comparison?left={pair[0]}&right={pair[1]}') == expected
        config.write_text(json.dumps({'arena': arena, 'retained': True, 'output': str(output) + '.retained-browser.json'}))
        subprocess.run(['node', 'scripts/ui-r3-browser-check.cjs'], cwd=ROOT, env=env, check=True)
        report['retained_browser'] = json.loads(Path(str(output) + '.retained-browser.json').read_text())
        report['status'] = 'passed'
    except BaseException as exc:
        report['status'] = 'failed'
        report['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        gate.cleanup_arenas()
        report['final_resources'] = {arena: gate.inventory(arena) for arena in gate.ARENAS}
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        print('Evidence:', output)
        assert not any(any(count.values()) for count in report['final_resources'].values()), report['final_resources']


if __name__ == '__main__':
    main()

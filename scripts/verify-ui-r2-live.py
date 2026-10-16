#!/usr/bin/env python3
"""Real Docker-local control review. Start an isolated nv06 Compose stack first.

  docker compose -p nidavellir-ui-r2 -f docker-compose.nv06.yml up -d --build postgres redis orchestrator worker webui
  NV_PLAYWRIGHT_MODULE=/path/to/playwright python3 scripts/verify-ui-r2-live.py

Only arenas created here are destroyed. Evidence outputs refuse overwrite. The
caller removes the isolated stack after reviewing post-teardown evidence.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("nv06_gate", ROOT / "scripts/verify-nv06-live.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
gate.COMPOSE = ("docker", "compose", "-p", "nidavellir-ui-r2", "-f", "docker-compose.nv06.yml")


def main():
    tag = datetime.now(timezone.utc).strftime('%Y-%m-%d-') + uuid.uuid4().hex[:8]
    output = ROOT / f'docs/verification/ui-r2-live-{tag}.json'
    # Reserve a new path before any infrastructure work; failed attempts are retained.
    with output.open('x') as handle:
        json.dump({'status': 'started', 'date': tag}, handle)
    report = {'schema': 'nidavellir/ui-r2-live/v1', 'date': tag, 'cases': [], 'status': 'running'}
    try:
        gate.run('docker', 'build', '-t', 'nidavellir/nv06-authz:acceptance', 'cyber-range/fixtures/nv06-authz')
        image = gate.run('docker', 'image', 'inspect', 'nidavellir/nv06-authz:acceptance', '--format', '{{.Id}}').stdout.strip()
        base = gate.run('docker', 'image', 'inspect', 'python:3.11.14-alpine', '--format', '{{.Id}}').stdout.strip()
        report['fixture_image'] = image
        scenario = {
            'schema': 'nidavellir/v3', 'name': 'UI-R2 two-account calibration',
            'requires': {'provider_class': 'container'},
            'network': {'segments': [{'name': 'lab'}]},
            'nodes': [
                {'name': 'target', 'role': 'victim', 'image': image, 'segments': ['lab'], 'ports': [8080]},
                {'name': 'attacker', 'role': 'attacker', 'image': base, 'segments': ['lab'],
                 'entrypoint': True, 'command': 'sleep infinity'}],
            'agents': [{'stance': 'attacker', 'node': 'attacker'}],
            'vulnerabilities': [{'id': 'authz', 'title': 'Cross-account object read', 'cwe': 'CWE-639',
                'node': 'target', 'validator': 'authorization_effect',
                'validation_config': {'actor': 'A', 'owner': 'B', 'control_token': 'token-b-operator'}}],
            'lifecycle': {'readiness': {'type': 'http', 'node': 'target', 'port': 8080,
                'path': '/health', 'expected_status': 200, 'timeout_seconds': 20}},
        }
        gate.run(*gate.COMPOSE, 'exec', '-T', 'orchestrator', 'python', '-c',
                 "from database import Database; from auth import hash_api_key; "
                 "db=Database(); key=hash_api_key('nv06-agent-key'); "
                 "db.create_api_key(key,'nv06-agent','agent') if db.get_api_key(key) is None else None")
        for name, path, expected in [('disclosure', '/objects/B', 'confirmed'),
                                     ('denial', '/protected/B', 'refuted'),
                                     ('failed-control', '/health', 'infrastructure_failure')]:
            current = copy.deepcopy(scenario)
            if name == 'failed-control':
                current['vulnerabilities'][0].update(validator='http_access_control', validation_config={
                    'actor': 'A', 'owner': 'B', 'forbidden_marker': 'nv06-v1',
                    'actor_headers': {'Authorization': 'Bearer token-a-public'},
                    'owner_headers': {'Authorization': 'Bearer token-b-operator'},
                    'action': {'method': 'GET', 'path': '/health'},
                    'control': {'method': 'GET', 'path': '/health'},
                })
            scenario_id = 'ui-r2-' + name + '-' + tag[-8:]
            gate.api('POST', '/scenarios', {'id': scenario_id, 'spec': current})
            arena = gate.api('POST', '/deploy', {'scenario': scenario_id, 'instance_id': 'ui-r2-' + name,
                'provider': 'docker-local', 'engagement_purpose': 'calibration', 'participant_mode': 'agent',
                'engagement_time_box_seconds': 900})['instance_id']
            gate.ARENAS.append(arena)
            gate.wait('/status/' + arena, lambda data: data.get('status') == 'active')
            gate.bind(arena)
            gate.api('POST', f'/arenas/{arena}/budget/policy', {
                'action_cap': 10, 'deadline': (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
                'reason': 'UI-R2 confined live acceptance'})
            action = gate.action(arena, path, 'uir2' + uuid.uuid4().hex)
            finding = gate.finding(arena, action['transaction_digest'])
            route = f'/arenas/{arena}/findings/{finding["finding_id"]}/review'
            budget_before = gate.api('GET', f'/arenas/{arena}/budget')
            review = gate.api('GET', route)
            assert gate.api('GET', f'/arenas/{arena}/budget') == budget_before
            assert review['verdict'] == expected, review
            assert gate.api('GET', route, key=gate.AGENT_KEY, expected=(403,))['status'] == 403
            assert 'token-a-public' not in json.dumps(review) and 'token-b-operator' not in json.dumps(review)
            assert gate.api('GET', f'/arenas/not-this-arena/findings/{finding["finding_id"]}/review', expected=(404,))['status'] == 404
            if name == 'failed-control':
                assert [c['state'] for c in review['controls']] == ['passed', 'failed'], review
                assert gate.api('POST', f'/arenas/{arena}/findings/{finding["finding_id"]}/verify',
                                {'verdict': 'refuted'}, expected=(422,))['status'] == 422
            else:
                assert review['controls'][0]['state'] == 'passed'
            case = {'name': name, 'arena': arena, 'finding_id': finding['finding_id'], 'review': review,
                    'budget_unchanged_by_review': budget_before}
            report['cases'].append(case)
            if name == 'denial':
                missing = gate.finding(arena)
                missing_review = gate.api('GET', f'/arenas/{arena}/findings/{missing["finding_id"]}/review')
                assert missing_review['verdict'] == 'inconclusive' and missing_review['unresolved']
                case['missing_action'] = {'finding_id': missing['finding_id'], 'review': missing_review}
        config = ROOT / f'data/ui-r2-browser-{tag}.json'
        config.parent.mkdir(exist_ok=True)
        config.write_text(json.dumps({'cases': report['cases'], 'output': str(output) + '.browser.json'}))
        browser_env = {**os.environ, 'NV_R2_CONFIG': str(config)}
        subprocess.run(['node', 'scripts/ui-r2-browser-check.cjs'], cwd=ROOT, env=browser_env, check=True)
        report['browser_before_teardown'] = json.loads(Path(str(output) + '.browser.json').read_text())
        for arena in gate.ARENAS:
            gate.api('DELETE', '/destroy/' + arena, expected=(200, 202))
            gate.wait('/status/' + arena, lambda data: data.get('status') == 'destroyed')
        for case in report['cases']:
            arena = case['arena']
            assert gate.api('GET', f'/arenas/{arena}/findings/{case["finding_id"]}/review') == case['review']
            for field in ('control_digest',):
                digest = case['review'][field]
                assert gate.api('GET', f'/arenas/{arena}/validation-evidence/{digest}')['digest'] == digest
        config.write_text(json.dumps({'cases': report['cases'], 'output': str(output) + '.retained-browser.json'}))
        subprocess.run(['node', 'scripts/ui-r2-browser-check.cjs'], cwd=ROOT, env=browser_env, check=True)
        report['browser_after_teardown'] = json.loads(Path(str(output) + '.retained-browser.json').read_text())
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

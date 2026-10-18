"""UI-R3: retained comparisons cannot expose auth headers or execute requests."""
import pytest
from fastapi.testclient import TestClient

import api
import auth
import http_transactions as tx
from database import Database
from tests.test_nv06_validation import _arena


@pytest.fixture()
def setup():
    db = Database()
    clients = []
    for role, name in [('operator', 'r3-operator'), ('agent', 'nv06-agent')]:
        key = auth.generate_api_key()
        db.create_api_key(auth.hash_api_key(key), name=name, role=role)
        client = TestClient(api.app)
        client.headers['X-API-Key'] = key
        clients.append(client)
    arena = _arena(db, 'r3-' + auth.generate_api_key()[-8:])
    return db, arena, *clients


def capture(arena, path='/objects/A', status=200, body='owned', truncated=False, actor='nv06-agent', token='account-a'):
    return tx.record(arena, request={
        'node': 'target', 'method': 'GET', 'path': path, 'params': {}, 'body': None,
        'headers': {'Authorization': 'Bearer ' + token, 'Cookie': 'sid=private-cookie', 'X-Request-ID': 'r3id'}},
        response={'status': status, 'body': body, 'body_bytes': len(body.encode()),
                  'headers': {'Set-Cookie': 'private-response-cookie'}, 'truncated': truncated}, actor=actor)['digest']


def test_compare_is_bounded_secret_safe_and_survives_teardown(setup):
    db, arena, operator, agent = setup
    left = capture(arena)
    right = capture(arena, '/protected/B', 403, 'denied')
    before = db.budget_status(arena)
    route = f'/arenas/{arena}/http/comparison?left={left}&right={right}'
    response = agent.get(route)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['left']['request']['path'] == '/objects/A'
    assert result['right']['response']['status'] == 403
    assert result['captured_body_equal'] is False
    assert result['complete'] is True
    assert '-owned' in result['body_diff'] and '+denied' in result['body_diff']
    assert all(secret not in response.text for secret in ('account-a', 'private-cookie', 'private-response-cookie'))
    assert db.budget_status(arena) == before
    db.update_deployment(arena, status='destroying', actor='test')
    db.update_deployment(arena, status='destroyed', actor='test')
    assert operator.get(route).json() == result


def test_truncated_or_missing_evidence_cannot_claim_complete_comparison(setup):
    _, arena, operator, _ = setup
    left = capture(arena, body='x' * 30000, truncated=True)
    right = capture(arena, body='x' * 30000 + 'y')
    result = operator.get(f'/arenas/{arena}/http/comparison?left={left}&right={right}').json()
    assert result['complete'] is False
    assert result['left']['preview_clipped'] is True
    assert len(result['body_diff']) <= 16384
    assert result['unresolved']
    missing = operator.get(f'/arenas/{arena}/http/comparison?left={left}&right=sha256:' + 'e' * 64)
    assert missing.status_code == 404


def test_saved_named_pairs_validate_scope_and_are_hidden_from_agents(setup):
    db, arena, operator, agent = setup
    left, right = capture(arena), capture(arena, '/protected/B', 403, 'denied')
    payload = {'name': 'Owned versus foreign', 'notes': 'Inspect the owner control before interpreting denial',
               'left': {'digest': left, 'label': 'Owned A'}, 'right': {'digest': right, 'label': 'Foreign B'}}
    route = f'/arenas/{arena}/http/request-groups'
    assert agent.post(route, json=payload).status_code == 403
    saved = operator.post(route, json=payload)
    assert saved.status_code == 200, saved.text
    group = saved.json()
    assert group['name'] == 'Owned versus foreign'
    assert operator.get(route).json()['groups'][0]['group_id'] == group['group_id']
    assert agent.get(route).status_code == 403
    events = agent.get(f'/deployments/{arena}/events').json()['events']
    assert all(e['type'] != 'http_request_group' for e in events)
    foreign = capture('other-arena', '/foreign-only')
    payload['right']['digest'] = foreign
    assert operator.post(route, json=payload).status_code == 404
    db.update_deployment(arena, status='destroying', actor='test')
    db.update_deployment(arena, status='destroyed', actor='test')
    assert operator.get(route).json()['groups'][0] == group


def test_borrow_headers_stays_server_side_and_case_insensitive(setup, monkeypatch):
    _, arena, operator, _ = setup
    parent = capture(arena, token='account-a')
    source = capture(arena, '/objects/B', token='account-b')
    seen = []
    def run(_record, request, _principal):
        seen.append(request.headers)
        return {'success': True, 'status': 200, 'body': 'ok', 'truncated': False}
    monkeypatch.setattr(api, '_run_arena_http', run)
    result = operator.post(f'/arenas/{arena}/http/transactions/{parent}/replay', json={
        'path': '/protected/B', 'headers': {'X-Request-ID': 'newid'},
        'credential_source_digest': source, 'credential_header_names': ['authorization']})
    assert result.status_code == 200, result.text
    assert seen[0]['Authorization'] == 'Bearer account-b'
    assert len([key for key in seen[0] if key.lower() == 'authorization']) == 1
    assert seen[0]['X-Request-ID'] == 'newid'
    assert tx.get(arena, parent)[1]['request']['headers']['Authorization'] == 'Bearer account-a'
    foreign = capture('foreign-source', '/foreign-source-only')
    denied = operator.post(f'/arenas/{arena}/http/transactions/{parent}/replay', json={
        'credential_source_digest': foreign, 'credential_header_names': ['Authorization']})
    assert denied.status_code == 404
    assert len(seen) == 1


def test_agent_cannot_compare_or_borrow_operator_private_capture(setup):
    _, arena, _, agent = setup
    owned = capture(arena)
    private = capture(arena, '/private-control', actor='r3-operator', token='private-control-token')
    assert agent.get(f'/arenas/{arena}/http/comparison?left={owned}&right={private}').status_code == 403
    rejected = agent.post(f'/arenas/{arena}/http/transactions/{owned}/replay', json={
        'credential_source_digest': private, 'credential_header_names': ['Authorization']})
    assert rejected.status_code == 403
    assert 'private-control-token' not in rejected.text


def test_group_history_is_paged_without_losing_saved_evidence(setup):
    _, arena, operator, _ = setup
    left, right = capture(arena), capture(arena, '/other')
    route = f'/arenas/{arena}/http/request-groups'
    ids = []
    for i in range(3):
        ids.append(operator.post(route, json={'name': f'Pair {i}',
            'left': {'digest': left, 'label': 'A'}, 'right': {'digest': right, 'label': 'B'}}).json()['group_id'])
    first = operator.get(route + '?limit=2').json()
    assert [g['group_id'] for g in first['groups']] == ids[:0:-1]
    next_page = operator.get(route + f'?limit=2&before={first["next_before"]}').json()
    assert [g['group_id'] for g in next_page['groups']] == ids[:1]
    assert next_page['next_before'] is None


def test_replay_editor_can_remove_query_and_body_and_override_header_casing(setup, monkeypatch):
    _, arena, operator, _ = setup
    parent = tx.record(arena, request={'node': 'target', 'method': 'POST', 'path': '/search',
        'params': {'old': 'filter'}, 'body': 'old-body', 'headers': {'Authorization': 'old-secret'}},
        response={'status': 200, 'body': 'ok', 'truncated': False}, actor='r3-operator')['digest']
    seen = []
    def run(_record, request, _principal):
        seen.append(request)
        return {'success': True, 'status': 200, 'body': 'ok', 'truncated': False}
    monkeypatch.setattr(api, '_run_arena_http', run)
    response = operator.post(f'/arenas/{arena}/http/transactions/{parent}/replay', json={
        'params': {}, 'replace_params': True, 'body': '', 'headers': {'authorization': 'new-secret'}})
    assert response.status_code == 200, response.text
    assert seen[0].params == {}
    assert seen[0].body == ''
    assert seen[0].headers == {'authorization': 'new-secret'}


def test_agent_access_tracks_successful_capture_despite_cross_actor_dedup(setup):
    db, arena, _, agent = setup
    first = capture(arena, actor='r3-operator')
    repeated = capture(arena, actor='nv06-agent')
    assert repeated == first
    db.record_event(arena, 'http_request', {'transaction_digest': repeated}, actor='nv06-agent')
    own = capture(arena, '/second')
    response = agent.get(f'/arenas/{arena}/http/comparison?left={repeated}&right={own}')
    assert response.status_code == 200, response.text


def test_agent_cannot_inherit_private_credentials_by_using_replay_parent(setup, monkeypatch):
    _, arena, _, agent = setup
    private = capture(arena, '/private-only', actor='r3-operator', token='private-control-token')
    monkeypatch.setattr(api, '_run_arena_http', lambda *_: {'success': True, 'status': 200, 'body': 'ok'})
    rejected = agent.post(f'/arenas/{arena}/http/transactions/{private}/replay', json={})
    assert rejected.status_code == 403


def test_rejected_effective_request_never_echoes_borrowed_secret(setup):
    _, arena, operator, _ = setup
    parent = tx.record(arena, request={'node': 'target', 'method': 'GET', 'path': '/',
        'params': {}, 'headers': {}, 'body': None}, response={'status': 200, 'body': 'ok'})['digest']
    source = capture(arena, '/source-secret', token='secret-reused-account-b')
    response = operator.post(f'/arenas/{arena}/http/transactions/{parent}/replay', json={
        'headers': {f'X-Pad-{i}': 'pad' for i in range(32)},
        'credential_source_digest': source, 'credential_header_names': ['Authorization']})
    assert response.status_code == 422
    assert 'account-b' not in response.text, response.text
    assert 'input_value' not in response.text, response.text


def test_preview_retains_research_headers_while_masking_cookie_values(setup):
    _, arena, operator, _ = setup
    digest = tx.record(arena, request={'node': 'target','method': 'GET','path': '/', 'headers': {}},
        response={'status': 302,'body': '', 'truncated': False,'headers': {
            'Location': '/next?token=private-redirect-token', 'Cache-Control': 'no-store',
            'Set-Cookie': 'sid=private-session; HttpOnly; Secure; SameSite=Lax'}})['digest']
    response = operator.get(f'/arenas/{arena}/http/transactions/{digest}/preview')
    headers = response.json()['response']['headers']
    assert headers['Cache-Control'] == 'no-store'
    assert 'HttpOnly' in headers['Set-Cookie'] and 'Secure' in headers['Set-Cookie']
    assert '/next' in headers['Location']
    assert 'private-session' not in response.text and 'private-redirect-token' not in response.text

"""Control health must gate review conclusions, including historical records."""
import pytest

import api
import validation_evidence
import auth
from fastapi.testclient import TestClient
from database import Database
from tests.test_nv06_validation import _arena, _transaction


@pytest.fixture()
def clients():
    db = Database()
    result = []
    for role in ('operator', 'agent'):
        key = auth.generate_api_key()
        db.create_api_key(auth.hash_api_key(key), name='review-' + role, role=role)
        client = TestClient(api.app)
        client.headers['X-API-Key'] = key
        result.append(client)
    return db, *result


@pytest.mark.parametrize('healthy,expected', [(True, 'refuted'), (False, 'inconclusive')])
def test_review_uses_control_evidence_not_recorded_refutation(clients, healthy, expected):
    db, operator, agent = clients
    arena = _arena(db, f'review-{int(healthy)}')
    action = _transaction(arena, 'review123', '/protected/B')
    effect = validation_evidence.record(arena, {
        'schema': 'nidavellir/validation-observation/v1', 'kind': 'authorization_effect',
        'data': {'actor': 'A', 'owner': 'B', 'status': 403, 'unauthorized_disclosure': False}})
    control = validation_evidence.record(arena, {
        'schema': 'nidavellir/validation-observation/v1', 'kind': 'healthy_control',
        'data': {'actor': 'B', 'owner': 'B', 'status': 200, 'control_ok': healthy}})
    db.record_event(arena, 'finding', {'finding_id': 'review-finding', 'validation': {
        'validator_id': 'authorization_effect', 'validator_version': 1,
        'verdict': 'refuted', 'action_digest': action,
        'observation_digest': effect, 'control_digest': control,
        'review_context': {'actor': 'A', 'owner': 'B'}}}, actor='test')
    path = f'/arenas/{arena}/findings/review-finding/review'
    response = operator.get(path)
    assert response.status_code == 200, response.text
    review = response.json()
    assert review['verdict'] == expected
    assert review['controls'][0]['state'] == ('passed' if healthy else 'failed')
    assert review['actor']['request']['path'] == '/protected/B'
    assert 'token-a-public' not in response.text
    assert review['effect']['data']['unauthorized_disclosure'] is False
    assert agent.get(path).status_code == 403
    assert operator.get('/arenas/other/findings/review-finding/review').status_code == 404
    db.update_deployment(arena, status='destroying', actor='test')
    db.update_deployment(arena, status='destroyed', actor='test')
    assert operator.get(path).json() == review


def test_missing_control_remains_unresolved(clients):
    db, operator, _ = clients
    arena = _arena(db, 'review-missing')
    db.record_event(arena, 'finding', {'finding_id': 'missing', 'validation': {
        'validator_id': 'authorization_effect', 'validator_version': 1, 'verdict': 'refuted',
        'control_digest': 'sha256:' + 'f' * 64}}, actor='test')
    review = operator.get(f'/arenas/{arena}/findings/missing/review').json()
    assert review['verdict'] == 'inconclusive'
    assert review['controls'][0]['state'] == 'unresolved'
    assert review['unresolved']


def test_review_cannot_refute_when_prerequisites_failed(clients):
    db, operator, _ = clients
    arena = _arena(db, 'review-refute')
    db.record_event(arena, 'finding', {'finding_id': 'failed', 'validation': {
        'validator_id': 'authorization_effect', 'validator_version': 1,
        'verdict': 'infrastructure_failure', 'reason_code': 'control_failed'}}, actor='test')
    response = operator.post(f'/arenas/{arena}/findings/failed/verify', json={'verdict': 'refuted'})
    assert response.status_code == 422


@pytest.mark.parametrize('control_state', ['missing', 'corrupt', 'foreign', 'failed'])
def test_confirmation_cannot_survive_missing_prerequisite_evidence(clients, control_state):
    db, operator, _ = clients
    arena = _arena(db, 'review-confirm-' + control_state)
    action = _transaction(arena, 'reviewconfirm', '/objects/B')
    effect = validation_evidence.record(arena, {
        'schema': 'nidavellir/validation-observation/v1', 'kind': 'authorization_effect',
        'data': {'actor': 'A', 'owner': 'B', 'status': 200, 'unauthorized_disclosure': True}})
    control = None
    if control_state != 'missing':
        control_arena = 'different-arena' if control_state == 'foreign' else arena
        control = validation_evidence.record(control_arena, {
            'schema': 'nidavellir/validation-observation/v1', 'kind': 'healthy_control',
            'data': {'actor': 'B', 'owner': 'B', 'status': 200, 'control_ok': control_state != 'failed'}})
        if control_state == 'corrupt':
            validation_evidence._path(arena, control).write_text('{}')
    db.record_event(arena, 'finding', {'finding_id': 'confirmation', 'validation': {
        'validator_id': 'authorization_effect', 'validator_version': 1,
        'verdict': 'confirmed', 'action_digest': action, 'observation_digest': effect, 'control_digest': control,
        'review_context': {'actor': 'A', 'owner': 'B'}}}, actor='test')
    result = operator.get(f'/arenas/{arena}/findings/confirmation/review').json()
    assert result['verdict'] == 'inconclusive'
    assert result['recorded_verdict'] == 'confirmed'
    assert result['controls'][0]['state'] == ('failed' if control_state == 'failed' else 'unresolved')

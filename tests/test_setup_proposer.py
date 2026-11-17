"""
Field-C setup proposer (pure): prompt build, steps extraction, and scope/budget
filtering. The model call is injected — no network.
"""
import json

import pytest

import setup_proposer

_BRIEF = {"victim_nodes": ["web", "db"], "step_budget_remaining": 5}
_REPLY = json.dumps({"steps": [
    {"node": "web", "command": "apt-get install -y nginx", "rationale": "web server"},
    {"node": "db", "command": "systemctl start postgresql", "rationale": "db"},
    {"node": "attacker", "command": "rm -rf /", "rationale": "out of scope"},   # dropped
    {"node": "web", "command": "", "rationale": "empty"},                        # dropped
]})


def test_build_messages_embeds_brief():
    system, messages = setup_proposer.build_messages(_BRIEF)
    assert "JSON object" in system
    assert "web" in messages[0]["content"]


def test_extract_steps_plain_and_fenced():
    assert len(setup_proposer.extract_steps(_REPLY)) == 4
    fenced = "Here you go:\n```json\n" + _REPLY + "\n```"
    assert len(setup_proposer.extract_steps(fenced)) == 4


def test_extract_steps_errors():
    with pytest.raises(setup_proposer.ProposerError):
        setup_proposer.extract_steps("sorry, no")
    with pytest.raises(setup_proposer.ProposerError):
        setup_proposer.extract_steps('{"notsteps": 1}')


def test_generate_filters_scope_and_empty():
    out = setup_proposer.generate_proposals(
        lambda system, messages: _REPLY, _BRIEF, {"web", "db"}, max_steps=10
    )
    nodes = [s["node"] for s in out]
    assert nodes == ["web", "db"]          # out-of-scope + empty dropped
    assert all(s["command"] for s in out)


def test_generate_caps_at_max_steps():
    out = setup_proposer.generate_proposals(
        lambda s, m: _REPLY, _BRIEF, {"web", "db"}, max_steps=1
    )
    assert len(out) == 1


def test_generate_surfaces_provider_error_via_extract():
    # an error sentinel string has no JSON object → ProposerError
    with pytest.raises(setup_proposer.ProposerError):
        setup_proposer.generate_proposals(
            lambda s, m: "[co-pilot] rate limited", _BRIEF, {"web"}, max_steps=5
        )

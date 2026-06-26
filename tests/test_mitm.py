"""
MITM stance (P2-5): the tcpdump flow parser, the mock + docker-local capture
providers, the mitm binding capability, and the `/arenas/{id}/mitm/observe`
endpoint (mitm-bound, audited). The endpoint uses the mock provider in tests, so
no real docker/tcpdump is needed.
"""
import pytest

import bindings
from providers.docker_local import DockerLocalProvider, _parse_tcpdump
from providers.mock import MockProvider

_TCPDUMP = """1700000000.1 IP 10.0.0.3.51020 > 10.0.0.2.80: Flags [S], seq 1
1700000000.2 IP 10.0.0.2.80 > 10.0.0.3.51020: Flags [S.], seq 2
1700000000.3 IP 10.0.0.3 > 10.0.0.2: ICMP echo request, id 1
1700000000.4 ARP, Request who-has 10.0.0.2 tell 10.0.0.3
1700000000.5 IP 10.0.0.3.40000 > 8.8.8.8.53: UDP, length 30
"""


def test_parse_tcpdump_summarizes_flows():
    flows = _parse_tcpdump(_TCPDUMP)
    protos = [f["proto"] for f in flows]
    assert protos.count("tcp") == 2          # the two Flags lines
    assert "icmp" in protos and "udp" in protos
    assert not any(f["proto"] == "ip" for f in flows)  # ARP line (no 'IP a > b') dropped
    tcp = flows[0]
    assert tcp["src"] == "10.0.0.3" and tcp["sport"] == 51020 and tcp["dport"] == 80


def test_mock_capture_is_simulated():
    r = MockProvider().capture_traffic("x")
    assert r["success"] is True and r["flows"] and "simulated" in r.get("note", "")


def test_mitm_binding_permits_observe_only():
    assert bindings.stance_permits("mitm", bindings.CAP_OBSERVE)
    assert not bindings.stance_permits("mitm", bindings.CAP_EXEC)
    assert not bindings.stance_permits("attacker", bindings.CAP_OBSERVE)
    assert bindings.stance_permits(None, bindings.CAP_OBSERVE)  # own-sandbox unrestricted


# --- docker-local capture (mocked client; no real tcpdump) -------------------


class _Net:
    def __init__(self, name, nid):
        self.name, self.id = name, nid


class _FakeContainersRun:
    def __init__(self, out):
        self.out, self.kwargs = out, None

    def run(self, image, **kw):
        self.kwargs = {"image": image, **kw}
        return self.out


class _CapClient:
    def __init__(self, nets, out):
        self._nets = nets
        self.containers = _FakeContainersRun(out)

    class _Networks:
        def __init__(self, nets):
            self._nets = nets

        def list(self, filters=None):
            return self._nets

    @property
    def networks(self):
        return _CapClient._Networks(self._nets)


def test_docker_capture_picks_segment_bridge_not_aux():
    # Real arenas have a segment bridge plus aux ingress/mirror bridges — the tap
    # must land on the SEGMENT (where node↔node traffic flows), not the aux nets.
    nets = [
        _Net("nidavellir-abcd1234-lab", "1111aaaabbbb0000"),
        _Net("nidavellir-abcd1234-ingress", "2222ccccdddd0000"),
        _Net("nidavellir-abcd1234-mirror", "3333eeeeffff0000"),
    ]
    client = _CapClient(nets, _TCPDUMP.encode())
    r = DockerLocalProvider(client=client).capture_traffic("abcd1234-rest", seconds=3, max_packets=50)

    assert r["success"] is True
    assert r["bridge"] == "br-1111aaaabbbb"      # the -lab segment, not -ingress/-mirror
    assert r["packets"] >= 3
    kw = client.containers.kwargs
    assert kw["network_mode"] == "host" and "NET_RAW" in kw["cap_add"]
    assert "tcpdump -i br-1111aaaabbbb" in kw["command"][2]


def test_docker_capture_no_networks_is_clean_error():
    r = DockerLocalProvider(client=_CapClient([], b"")).capture_traffic("nope")
    assert r["success"] is False and "no arena segment networks" in r["error"]


# --- endpoint: POST /arenas/{id}/mitm/observe --------------------------------

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import auth  # noqa: E402
from database import Database  # noqa: E402


def _agent(name):
    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name=name, role="agent")
    c = TestClient(api.app)
    c.headers["X-API-Key"] = key
    return c


def _active_arena(iid):
    db = Database()
    db.create_deployment(iid, iid, "container_web_pentest", provider=None, actor="test")
    db.update_deployment(iid, status="deploying", actor="test")
    db.update_deployment(iid, status="active", outputs={"node_victim_name": "nv-victim"}, actor="test")
    return db


def test_observe_requires_an_mitm_binding():
    c = _agent("mitm-unbound")
    _active_arena("mitm-arena-1")
    assert c.post("/arenas/mitm-arena-1/mitm/observe", json={"seconds": 2}).status_code == 403


def test_observe_with_binding_captures_and_audits():
    c = _agent("mitm-bound")
    db = _active_arena("mitm-arena-2")
    db.record_event("mitm-arena-2", "agent_binding",
                    {"agent_name": "mitm-bound", "stance": "mitm"}, actor="test")
    r = c.post("/arenas/mitm-arena-2/mitm/observe", json={"seconds": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True and body["flows"]   # mock-simulated flows
    assert "mitm_observe" in [e["type"] for e in db.list_events("mitm-arena-2")]


def test_observe_on_inactive_arena_is_409():
    c = _agent("mitm-inactive")
    Database().create_deployment("mitm-arena-3", "x", "container_web_pentest", actor="test")
    assert c.post("/arenas/mitm-arena-3/mitm/observe", json={}).status_code == 409

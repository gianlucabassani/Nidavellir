"""
Tests for the Vulhub → v3 scenario importer (ROADMAP P1-5 / Classic-range track C):

  * vulhub_import.convert_compose — the deterministic compose → v3 conversion
    (image vs build services, ports/environment/command mapping, honest drops,
    the bundled attacker, tags, compose v1),
  * vulhub_import.fetch_vulhub_compose — the GitHub fetch (mocked, SSRF guard,
    .yml/.yaml fallback, path validation),
  * POST /scenarios/import/vulhub — import + dry-run preview + operator-only,
  * Node.environment round-trips through the schema and the provider normalizer.
"""
import pytest

import config
import scenarios
import vulhub_import
from scenario_spec import ScenarioSpec, normalized_nodes


# --- pure converter ----------------------------------------------------------

IMAGE_COMPOSE = {
    "version": "2",
    "services": {
        "web": {
            "image": "vulhub/weblogic:10.3.6.0-2017",
            "ports": ["7001:7001"],
            "environment": ["TZ=UTC", "DEBUG"],
            "volumes": ["./conf:/conf"],
            "depends_on": ["db"],
        },
        "db": {"image": "mysql:5.7", "environment": {"MYSQL_ROOT_PASSWORD": "root"}},
    },
}

BUILD_COMPOSE = {
    "services": {
        "app": {
            "build": {"context": "./php", "dockerfile": "Dockerfile", "args": {"X": "1"}},
            "ports": [{"target": 80, "published": 8080}],
            "command": ["sh", "-c", "apache2-foreground"],
        }
    }
}


def test_convert_image_env_builds_valid_spec():
    raw, warns = vulhub_import.convert_compose(
        IMAGE_COMPOSE, env_path="weblogic/CVE-2017-10271"
    )
    spec = ScenarioSpec.from_raw(raw)  # must validate
    by_name = {n.name: n for n in spec.nodes}

    assert by_name["web"].image == "vulhub/weblogic:10.3.6.0-2017"
    assert by_name["web"].ports == [7001]
    assert by_name["web"].environment == {"TZ": "UTC", "DEBUG": ""}
    assert by_name["db"].environment == {"MYSQL_ROOT_PASSWORD": "root"}
    # a Kali foothold is added and bound as the attacker stance
    assert "kali-cli" in by_name
    assert [(a.stance.value, a.node) for a in spec.agents] == [("attacker", "kali-cli")]
    assert spec.requires.provider_class.value == "container"
    # tags carry provenance + the CVE
    assert "vulhub" in spec.tags and "weblogic" in spec.tags
    assert "CVE-2017-10271" in spec.tags
    # honest drops are reported, not silent
    assert any("depends_on" in w and "volumes" in w for w in warns)
    assert any("DEBUG" in w for w in warns)


def test_convert_build_env_maps_to_gated_source():
    raw, warns = vulhub_import.convert_compose(
        BUILD_COMPOSE, env_path="thinkphp/5.0.23-rce", ref="abc123",
        include_attacker=False,
    )
    spec = ScenarioSpec.from_raw(raw)
    app = next(n for n in spec.nodes if n.name == "app")

    assert app.image is None
    assert app.service is not None
    src = app.service.source
    assert src.repo == vulhub_import.VULHUB_REPO_URL
    assert src.ref == "abc123"
    # context is rooted at the env dir + the compose build context
    assert src.context == "thinkphp/5.0.23-rce/php"
    assert src.dockerfile == "Dockerfile"
    assert app.ports == [80]
    assert app.command == "sh -c apache2-foreground"
    assert not spec.agents  # include_attacker=False
    assert any("NIDAVELLIR_ALLOW_SOURCE_BUILD" in w for w in warns)
    assert any("build args" in w for w in warns)
    assert any("list-form command" in w for w in warns)


def test_image_wins_when_both_image_and_build():
    compose = {"services": {"s": {"image": "vulhub/x:1", "build": "."}}}
    raw, warns = vulhub_import.convert_compose(compose, include_attacker=False)
    spec = ScenarioSpec.from_raw(raw)
    node = spec.nodes[0]
    assert node.image == "vulhub/x:1"
    assert node.service is None
    assert any("both `image` and `build`" in w for w in warns)


def test_compose_v1_no_services_key():
    compose = {"target": {"image": "h:1", "ports": ["127.0.0.1:9000:9090/tcp"]}}
    raw, _ = vulhub_import.convert_compose(compose, env_path="foo/bar",
                                           include_attacker=False)
    spec = ScenarioSpec.from_raw(raw)
    assert spec.nodes[0].ports == [9090]


def test_service_name_slug_collision_is_deduped():
    compose = {"services": {"Web.App": {"image": "a:1"}, "web-app": {"image": "b:1"}}}
    raw, _ = vulhub_import.convert_compose(compose, include_attacker=False)
    names = [n["name"] for n in raw["nodes"]]
    assert len(names) == len(set(names))  # unique after slugify+dedup


def test_empty_or_bad_compose_raises():
    with pytest.raises(vulhub_import.VulhubImportError):
        vulhub_import.convert_compose({"services": {}})
    with pytest.raises(vulhub_import.VulhubImportError):
        vulhub_import.convert_compose({"version": "3"})  # services not a mapping
    with pytest.raises(vulhub_import.VulhubImportError):
        vulhub_import.convert_compose({"services": {"x": {"ports": ["80"]}}})  # no image/build


def test_port_parsing_forms():
    assert vulhub_import._container_port("8080:80") == 80
    assert vulhub_import._container_port("80") == 80
    assert vulhub_import._container_port("127.0.0.1:8080:80/tcp") == 80
    assert vulhub_import._container_port({"target": 443}) == 443
    assert vulhub_import._container_port("not-a-port") is None


# --- fetch (mocked network) --------------------------------------------------


class _Resp:
    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text


def test_fetch_builds_pinned_raw_url(monkeypatch):
    seen = []

    def fake_get(url, timeout=15):
        seen.append(url)
        return _Resp(200, "services:\n  web:\n    image: vulhub/x:1\n")

    monkeypatch.setattr(vulhub_import.requests, "get", fake_get)
    compose, env_path = vulhub_import.fetch_vulhub_compose(
        "weblogic/CVE-2017-10271", ref="v1.2.3"
    )
    assert env_path == "weblogic/CVE-2017-10271"
    assert "services" in compose
    assert seen[0] == (
        "https://raw.githubusercontent.com/vulhub/vulhub/v1.2.3/"
        "weblogic/CVE-2017-10271/docker-compose.yml"
    )


def test_fetch_falls_back_to_yaml_extension(monkeypatch):
    def fake_get(url, timeout=15):
        if url.endswith(".yml"):
            return _Resp(404)
        return _Resp(200, "services:\n  web:\n    image: vulhub/x:1\n")

    monkeypatch.setattr(vulhub_import.requests, "get", fake_get)
    compose, _ = vulhub_import.fetch_vulhub_compose("a/b")
    assert "services" in compose


def test_fetch_missing_raises(monkeypatch):
    monkeypatch.setattr(vulhub_import.requests, "get", lambda url, timeout=15: _Resp(404))
    with pytest.raises(vulhub_import.VulhubImportError):
        vulhub_import.fetch_vulhub_compose("a/b")


def test_fetch_rejects_path_traversal():
    for bad in ["../etc/passwd", "/abs/path", "a/../../b", "a b"]:
        with pytest.raises(vulhub_import.VulhubImportError):
            vulhub_import.fetch_vulhub_compose(bad)


# --- Node.environment round-trips --------------------------------------------


def test_environment_round_trips_through_spec_and_normalizer():
    raw = {
        "schema": "nidavellir/v3",
        "name": "env-lab",
        "network": {"segments": [{"name": "lab"}]},
        "nodes": [{"name": "web", "role": "victim", "image": "x:1",
                   "segments": ["lab"], "environment": {"FOO": "bar"}}],
    }
    spec = ScenarioSpec.from_raw(raw)
    assert spec.nodes[0].environment == {"FOO": "bar"}
    norm = normalized_nodes(raw)
    assert norm[0]["environment"] == {"FOO": "bar"}


# --- API endpoint ------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_imported():
    config.SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    for f in config.SCENARIOS_DIR.glob("*.yaml"):
        f.unlink()
    yield
    for f in config.SCENARIOS_DIR.glob("*.yaml"):
        f.unlink()


@pytest.fixture()
def client():
    import api
    import auth
    from database import Database
    from fastapi.testclient import TestClient

    op_key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(op_key), name="vh-op", role="operator")
    ag_key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(ag_key), name="vh-agent", role="agent")

    c = TestClient(api.app)
    c.headers["X-API-Key"] = op_key
    c.agent_key = ag_key
    return c


def test_import_vulhub_from_pasted_compose_persists(client):
    resp = client.post(
        "/scenarios/import/vulhub",
        json={"compose": IMAGE_COMPOSE, "name": "weblogic-rce"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "imported"
    assert body["id"] == "weblogic-rce"
    assert body["warnings"]  # the lossy-conversion notes are surfaced
    # actually persisted into the registry
    assert scenarios.load_scenario_spec("weblogic-rce") is not None
    listing = {s["id"]: s for s in scenarios.list_scenarios()}
    assert listing["weblogic-rce"]["source"] == "imported"


def test_import_vulhub_dry_run_does_not_persist(client):
    resp = client.post(
        "/scenarios/import/vulhub",
        json={"compose": IMAGE_COMPOSE, "name": "dryrun-lab", "dry_run": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["valid"] is True
    assert body["topology"]["nodes"]
    assert scenarios.load_scenario_spec("dryrun-lab") is None


def test_import_vulhub_by_path_fetches(client, monkeypatch):
    import api

    def fake_fetch(path, ref="master", timeout=15):
        return IMAGE_COMPOSE, "weblogic/CVE-2017-10271"

    monkeypatch.setattr(api.vulhub_import, "fetch_vulhub_compose", fake_fetch)
    resp = client.post(
        "/scenarios/import/vulhub", json={"path": "weblogic/CVE-2017-10271"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "imported"


def test_import_vulhub_requires_operator(client):
    resp = client.post(
        "/scenarios/import/vulhub",
        json={"compose": IMAGE_COMPOSE},
        headers={"X-API-Key": client.agent_key},
    )
    assert resp.status_code == 403


def test_import_vulhub_rejects_both_or_neither_source(client):
    both = client.post(
        "/scenarios/import/vulhub",
        json={"path": "a/b", "compose": IMAGE_COMPOSE},
    )
    assert both.status_code == 422
    neither = client.post("/scenarios/import/vulhub", json={})
    assert neither.status_code == 422


def test_import_vulhub_unconvertible_returns_422(client):
    resp = client.post(
        "/scenarios/import/vulhub", json={"compose": {"services": {}}}
    )
    assert resp.status_code == 422

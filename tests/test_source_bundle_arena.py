"""Local source-bundle upload, preview, deploy, and provenance integration."""
import io
import tarfile

import pytest
from fastapi.testclient import TestClient

import catalog
from scenario_spec import normalized_nodes


def _archive_bytes(name="project/app.py", content=b"print('ok')\n"):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return output.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import api
    import auth
    import source_bundle
    from database import Database

    monkeypatch.setattr(
        source_bundle.config, "SOURCE_BUNDLES_DIR", tmp_path / "source-bundles"
    )
    dispatched = {}

    class _FakeTask:
        def delay(self, *args, **kwargs):
            dispatched.update(kwargs)

    monkeypatch.setattr(api, "deploy_lab", _FakeTask())
    monkeypatch.setattr(api.image_check, "missing_images", lambda refs: [])
    key = auth.generate_api_key()
    Database().create_api_key(
        auth.hash_api_key(key), name="bundle-tests", role="operator"
    )
    test_client = TestClient(api.app)
    test_client.headers["X-API-Key"] = key
    test_client.dispatched = dispatched
    return test_client


def _upload(client, data=None):
    return client.post(
        "/targets/source-bundles",
        files={
            "file": (
                "project.tar.gz",
                data if data is not None else _archive_bytes(),
                "application/gzip",
            )
        },
    )


def test_upload_returns_content_addressed_artifact(client):
    response = _upload(client)
    assert response.status_code == 200, response.text
    artifact = response.json()["artifact"]
    assert artifact["digest"].startswith("sha256:")
    assert artifact["payload_digest"].startswith("sha256:")
    assert artifact["filename"] == "project.tar.gz"
    assert artifact["stripped_root"] == "project"
    assert artifact["file_count"] == 1


def test_upload_rejects_traversal_archive(client):
    response = _upload(client, _archive_bytes("../escape.py"))
    assert response.status_code == 422
    assert "escapes" in response.text


def test_source_bundle_preview_and_deploy_are_pinned(client):
    from database import Database

    artifact = _upload(client).json()["artifact"]
    request = {
        "instance_id": "bundle-target",
        "artifact_digest": artifact["digest"],
        "ports": [8000],
        "authorization_basis": "owned",
        "authorization_confirmed": True,
    }
    preview = client.post("/arenas/source-bundle/preview", json=request)
    assert preview.status_code == 200
    assert preview.json()["valid"] is True
    assert preview.json()["target_manifest"]["kind"] == "source_bundle"
    assert preview.json()["target_manifest"]["resolved_ref"] == artifact["digest"]

    response = client.post("/arenas/source-bundle", json=request)
    assert response.status_code == 200, response.text
    arena_id = response.json()["instance_id"]
    victim = next(
        node
        for node in normalized_nodes(client.dispatched["scenario_config"])
        if node["name"] == "sut"
    )
    assert victim["sut_bundle"]["digest"] == artifact["digest"]
    assert victim["sut_bundle"]["payload_digest"] == artifact["payload_digest"]
    prearm = client.dispatched["setup_prearm"]
    assert prearm["open_setup"] is True
    assert prearm["auto_build"] is False

    event = next(
        item
        for item in Database().list_events(arena_id)
        if item["type"] == "setup_prearm"
    )
    assert event["payload"]["artifact"]["digest"] == artifact["digest"]
    pending = client.get(f"/arenas/{arena_id}/preflight")
    assert pending.status_code == 200
    assert pending.json()["target"]["kind"] == "source_bundle"


def test_source_bundle_deploy_requires_authorization(client):
    artifact = _upload(client).json()["artifact"]
    response = client.post(
        "/arenas/source-bundle",
        json={
            "instance_id": "bundle-no-auth",
            "artifact_digest": artifact["digest"],
        },
    )
    assert response.status_code == 422
    assert "authorized" in response.text


def test_build_source_bundle_scenario_is_setup_workspace():
    raw = catalog.build_source_bundle_scenario(
        "bundle",
        "sha256:" + "a" * 64,
        "sha256:" + "b" * 64,
        include_attacker=False,
    )
    victim = normalized_nodes(raw)[0]
    assert victim["image"] == "ubuntu:22.04"
    assert victim["command"] == "sleep infinity"
    assert victim["sut_bundle"]["path"] == "/opt/sut"

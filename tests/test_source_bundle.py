"""Bounded, content-addressed local source-bundle intake."""
import io
import tarfile

import pytest

import source_bundle


def _tar(entries, *, gzip=False):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz" if gzip else "w") as archive:
        for name, content, kind in entries:
            info = tarfile.TarInfo(name)
            if kind == "file":
                data = content.encode()
                info.size = len(data)
                info.mode = 0o755 if name.endswith(".sh") else 0o644
                archive.addfile(info, io.BytesIO(data))
            elif kind == "dir":
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = content
                archive.addfile(info)
    output.seek(0)
    return output


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(source_bundle.config, "SOURCE_BUNDLES_DIR", tmp_path / "bundles")
    monkeypatch.setattr(source_bundle.config, "SOURCE_BUNDLE_MAX_UPLOAD_BYTES", 1024 * 1024)
    monkeypatch.setattr(source_bundle.config, "SOURCE_BUNDLE_MAX_EXPANDED_BYTES", 1024 * 1024)
    monkeypatch.setattr(source_bundle.config, "SOURCE_BUNDLE_STORE_MAX_BYTES", 4 * 1024 * 1024)


def test_ingest_normalizes_root_and_is_content_addressed():
    stream = _tar(
        [
            ("project", "", "dir"),
            ("project/app.py", "print('ok')\n", "file"),
            ("project/run.sh", "#!/bin/sh\n", "file"),
        ],
        gzip=True,
    )
    artifact = source_bundle.ingest(stream, "../../project.tar.gz")

    assert artifact["digest"].startswith("sha256:")
    assert artifact["filename"] == "project.tar.gz"
    assert artifact["stripped_root"] == "project"
    assert artifact["file_count"] == 2
    assert source_bundle.get_artifact(artifact["digest"]) == artifact

    payload = source_bundle.read_payload(
        artifact["digest"], artifact["payload_digest"]
    )
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as normalized:
        assert normalized.getnames() == ["app.py", "run.sh"]
        assert normalized.getmember("run.sh").mode == 0o755

    duplicate = source_bundle.ingest(_tar([("app.py", "print('ok')\n", "file")]), "x.tar")
    assert duplicate["digest"] != artifact["digest"]


@pytest.mark.parametrize(
    "entries, message",
    (
        ([("../escape", "x", "file")], "escapes"),
        ([("/etc/passwd", "x", "file")], "escapes"),
        ([(".git/config", "x", "file")], ".git"),
        ([("link", "../../etc/passwd", "symlink")], "link or special"),
        ([("same", "a", "file"), ("same", "b", "file")], "duplicate"),
    ),
)
def test_ingest_rejects_unsafe_members(entries, message):
    with pytest.raises(source_bundle.SourceBundleError, match=message):
        source_bundle.ingest(_tar(entries), "unsafe.tar")


def test_ingest_rejects_bundle_without_regular_files():
    with pytest.raises(source_bundle.SourceBundleError, match="regular file"):
        source_bundle.ingest(_tar([("empty", "", "dir")]), "empty.tar")


def test_ingest_rejects_upload_and_expanded_bounds(monkeypatch):
    monkeypatch.setattr(source_bundle.config, "SOURCE_BUNDLE_MAX_UPLOAD_BYTES", 100)
    with pytest.raises(source_bundle.SourceBundleTooLarge, match="upload"):
        source_bundle.ingest(io.BytesIO(b"x" * 101), "large.tar")

    monkeypatch.setattr(source_bundle.config, "SOURCE_BUNDLE_MAX_UPLOAD_BYTES", 1024 * 1024)
    monkeypatch.setattr(source_bundle.config, "SOURCE_BUNDLE_MAX_EXPANDED_BYTES", 4)
    with pytest.raises(source_bundle.SourceBundleTooLarge, match="expanded"):
        source_bundle.ingest(_tar([("large.txt", "12345", "file")]), "large.tar")


def test_read_payload_detects_tampering():
    artifact = source_bundle.ingest(_tar([("app.py", "safe", "file")]), "app.tar")
    artifact_dir = source_bundle._artifact_dir(artifact["digest"])
    payload = artifact_dir / "payload.tar"
    artifact_dir.chmod(0o700)
    payload.chmod(0o600)
    payload.write_bytes(b"tampered")

    with pytest.raises(source_bundle.SourceBundleError, match="integrity"):
        source_bundle.read_payload(artifact["digest"], artifact["payload_digest"])

"""Content-addressed, arena-scoped workspace evidence artifacts."""
import pytest

import config
import evidence_artifact


def test_patch_artifact_is_content_addressed_and_arena_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EVIDENCE_ARTIFACTS_DIR", tmp_path)
    patch = b"diff --git a/app.py b/app.py\n-old\n+new\n"
    metadata = evidence_artifact.store_patch(
        "arena-a", patch, {"node": "victim", "changed_file_count": 1}
    )

    assert metadata["digest"].startswith("sha256:")
    assert metadata["bytes"] == len(patch)
    assert evidence_artifact.get("arena-a", metadata["digest"])[1] == patch
    assert evidence_artifact.store_patch(
        "arena-a", patch, {"node": "victim", "changed_file_count": 1}
    ) == metadata
    with pytest.raises(evidence_artifact.EvidenceArtifactError, match="not found"):
        evidence_artifact.get("arena-b", metadata["digest"])


def test_patch_artifact_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "EVIDENCE_ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(config, "EVIDENCE_ARTIFACT_MAX_BYTES", 3)
    with pytest.raises(evidence_artifact.EvidenceArtifactError, match="limit"):
        evidence_artifact.store_patch("arena", b"four", {"node": "victim"})

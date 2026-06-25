"""
Field-A image-existence checking: the ref parser (pure) and the Docker Hub
existence check (network stubbed). Confident 404 → missing; unknown / other
registry / network error → no false alarm.
"""
import image_check


def test_parse_official_image():
    assert image_check.parse_ref("ubuntu:22.04") == ("library", "ubuntu", "22.04")
    assert image_check.parse_ref("nginx") == ("library", "nginx", "latest")


def test_parse_namespaced_image():
    assert image_check.parse_ref("vulnerables/web-dvwa:latest") == (
        "vulnerables", "web-dvwa", "latest")


def test_parse_other_registry_or_digest_is_unknown():
    assert image_check.parse_ref("ghcr.io/owner/app:1.0") is None      # non-hub registry
    assert image_check.parse_ref("localhost:5000/x:1") is None
    assert image_check.parse_ref("ubuntu@sha256:deadbeef") is None     # digest-pinned
    assert image_check.parse_ref("") is None


class _Resp:
    def __init__(self, code):
        self.status_code = code


def test_exists_true_false_unknown(monkeypatch):
    monkeypatch.setattr(image_check.netguard, "assert_public_host", lambda *a, **k: None)
    # 200 → exists
    monkeypatch.setattr(image_check.requests, "get", lambda *a, **k: _Resp(200))
    assert image_check.exists_on_hub("nginx:1.25") is True
    # 404 → missing
    monkeypatch.setattr(image_check.requests, "get", lambda *a, **k: _Resp(404))
    assert image_check.exists_on_hub("ghost/none:latest") is False
    # network error → unknown (no false alarm)
    def boom(*a, **k):
        raise OSError("no egress")
    monkeypatch.setattr(image_check.requests, "get", boom)
    assert image_check.exists_on_hub("nginx:1.25") is None
    # other-registry ref → unknown without any network call
    assert image_check.exists_on_hub("ghcr.io/o/a:1") is None


def test_missing_images_filters_to_confident_404s(monkeypatch):
    monkeypatch.setattr(image_check.netguard, "assert_public_host", lambda *a, **k: None)

    def fake_get(url, **k):
        return _Resp(404 if "ghost" in url else 200)

    monkeypatch.setattr(image_check.requests, "get", fake_get)
    missing = image_check.missing_images(["nginx:1.25", "ghost/x:latest", "ghost/x:latest"])
    assert missing == ["ghost/x:latest"]   # de-duplicated; real image omitted

"""Research code-intel: answer-shaped, read-only queries over a pinned repo.

Core is tested against scratch git repos (hermetic, no network); the API
surface is operator-only with bounded inputs and an audit event per call.
"""
import json
import subprocess

import pytest
from fastapi.testclient import TestClient


def _git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    import research_code

    root = tmp_path / "target"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "-c", "user.email=t@lab.invalid", "-c", "user.name=lab",
         "commit", "-q", "--allow-empty", "-m", "init")
    monkeypatch.setenv("RESEARCH_REPO_DIR", str(root))
    assert research_code.repo_root() == root
    return root


def _commit(repo, files, message):
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        _git(repo, "add", name)
    _git(repo, "-c", "user.email=t@lab.invalid", "-c", "user.name=lab",
         "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


def test_fix_lookup_extracts_check_line(repo):
    import research_code

    sha = _commit(repo, {"pkg/views.py": (
        "from perms import has_perms_owner_aware\n"
        "class ShareLinkSerializer:\n"
        "    def validate_document(self, document):\n"
        "        if has_perms_owner_aware(self.user, 'view_document', document):\n"
        "            return document\n"
        "        raise PermissionDenied()\n")}, "Fix GHSA-xxxx")
    result = research_code.fix_lookup(repo, sha, "GHSA-xxxx")
    assert result["data"]["check_line"] == (
        "added has_perms_owner_aware gate in validate_document (pkg/views.py)")
    assert result["data"]["advisory_id"] == "GHSA-xxxx"
    assert result["truncation"]["truncated"] is False
    assert result["digest"] == research_code._digest(
        {k: v for k, v in result.items() if k != "digest"})


def test_fix_lookup_bad_ref_and_verb_refused(repo):
    import research_code

    with pytest.raises(research_code.ResearchCodeError):
        research_code.fix_lookup(repo, "not a ref!!")
    with pytest.raises(research_code.ResearchCodeError):
        research_code.run_git(repo, "clone", "https://example.invalid/x")
    with pytest.raises(research_code.ResearchCodeError):
        research_code.run_git(repo, "log", "--upload-pack=x")


def test_read_only_inventory_accepts_git_words_in_literal_paths(repo):
    import research_code

    _commit(repo, {"pkg/test_api_remote_version.py":
                   "def f():\n    return Document.objects.all()\n"}, "Literal path")
    result = research_code.sibling_search(
        repo, "HEAD", "unscoped-queryset", ["pkg/test_api_remote_version.py"])
    assert result["data"]["total_matches"] == 1
    assert result["data"]["sites"][0]["classification"] == "no-local-owner-check"
    with pytest.raises(research_code.ResearchCodeError):
        research_code.run_git(repo, "remote", "--", "pkg/test_api_remote_version.py")


def test_repo_root_unprovisioned(tmp_path, monkeypatch):
    import research_code

    monkeypatch.setenv("RESEARCH_REPO_DIR", str(tmp_path / "missing"))
    with pytest.raises(research_code.ResearchCodeError, match="not provisioned"):
        research_code.repo_root()


def test_layer_diff_counts_permission_delta(repo):
    import research_code

    _commit(repo, {"pkg/views.py": "from perms import thing\nx = 1\n"},
            "base")
    _commit(repo, {"pkg/views.py": (
        "from perms import thing\n"
        "from perms import has_perms_owner_aware\n"
        "x = 1\n"
        "def view():\n"
        "    return has_perms_owner_aware(u, 'view_document', d)\n")},
            "add gate")
    result = research_code.layer_diff(repo, "HEAD~1", "HEAD", ["pkg/"])
    files = result["data"]["files"]
    assert files["pkg/views.py"]["added"] == 2
    assert len(result["data"]["sites"]) == 2
    empty = research_code.layer_diff(repo, "HEAD", "HEAD", ["pkg/"])
    assert empty["data"]["files"] == {}
    assert empty["truncation"]["truncated"] is False


def test_sibling_search_composition_status(repo):
    import research_code

    _commit(repo, {"pkg/views.py": (
        "class AView:\n"
        "    permission_classes = (IsAuthenticated,)\n"
        "    def covered(self):\n"
        "        qs = Widget.objects.filter(name='x')\n"
        "        allowed = get_objects_for_user_owner_aware(u, 'view_widget', Widget)\n"
        "        return qs\n"
        "    def bare(self):\n"
        "        return Widget.objects.filter(name='y')\n"
        "    def bulk(self):\n"
        "        has_perms = user.has_perm('x')\n"
        "    def composed(self):\n"
        "        has_perms = has_perms and user_is_owner\n")}, "views")
    bare = research_code.sibling_search(repo, "HEAD", "bare-auth-view", ["pkg/"])
    assert [(s["line"], s["classification"]) for s in bare["data"]["sites"]] == [(2, "bare-auth-class")]
    unscoped = research_code.sibling_search(
        repo, "HEAD", "unscoped-queryset", ["pkg/"])
    by_line = {s["line"]: s["status"] for s in unscoped["data"]["sites"]}
    # An owner-aware call in the same function is a signal, not proof that
    # the returned queryset is filtered by it ("allowed" is unused here).
    assert by_line[4] == "manual-review" and by_line[8] == "uncovered"
    bulk = research_code.sibling_search(repo, "HEAD", "bulk-permission", ["pkg/"])
    by_line = {s["line"]: s["status"] for s in bulk["data"]["sites"]}
    assert by_line[10] == "initializer" and by_line[12] == "covered"
    with pytest.raises(research_code.ResearchCodeError, match="unknown pattern"):
        research_code.sibling_search(repo, "HEAD", "everything")


def test_sibling_inventory_can_be_read_without_losing_residuals(repo):
    import research_code

    _commit(repo, {"pkg/views.py": "\n".join(
        f"def f{i}():\n    return Document.objects.all()" for i in range(1200))},
        "Many residual candidates")
    sites = []
    offset = 0
    while True:
        result = research_code.sibling_search(
            repo, "HEAD", "unscoped-queryset", ["pkg/"], offset=offset)
        assert result["data"]["total_matches"] == 1200
        assert result["data"]["total_matches_complete"]
        sites.extend(result["data"]["sites"])
        offset = result["data"]["next_offset"]
        if offset is None:
            break
    assert len(sites) == 1200
    assert len({(s["file"], s["line"]) for s in sites}) == 1200
    assert all(s["status"] == "uncovered" for s in sites)


@pytest.mark.parametrize("pattern,affected,fixed,reason", [
    ("field-validation", "class S:\n    queryset = Document.objects.all()\n",
     "class S:\n    def validate_document(self, d):\n        return d\n",
     "serializer-queryset-policy-unverified"),
    ("privilege-flags", "def update(data):\n    return data['is_superuser']\n",
     "def update(data):\n    return bool(data['is_superuser'])\n",
     "privilege-value-parsing-unverified"),
    ("template-context", "context = {'document': document}\n",
     "context = {'title': title}\n", "template-context-contents-unverified"),
    ("mutation-order", "def delete(obj):\n    obj.delete()\n",
     "def delete(obj):\n    if permitted(obj):\n        obj.delete()\n",
     "check-before-mutation-unverified"),
])
def test_additional_fix_shapes_retain_both_versions_for_review(
        repo, pattern, affected, fixed, reason):
    import research_code

    before = _commit(repo, {"pkg/views.py": affected}, "Affected shape")
    after = _commit(repo, {"pkg/views.py": fixed}, "Changed shape")
    for ref in (before, after):
        result = research_code.sibling_search(repo, ref, pattern, ["pkg/"])
        assert result["data"]["sites"]
        assert all(site["status"] == "manual-review" and site["classification"] == reason
                   for site in result["data"]["sites"])


# --- API surface -------------------------------------------------------------

def _client(role, name, *, raise_server_exceptions=True):
    import api
    import auth
    from database import Database

    key = auth.generate_api_key()
    Database().create_api_key(auth.hash_api_key(key), name=name, role=role)
    client = TestClient(api.app, raise_server_exceptions=raise_server_exceptions)
    client.headers["X-API-Key"] = key
    return client


def test_research_api_is_operator_only_and_bounded(repo):
    operator = _client("operator", name="op-research-code")
    agent = _client("agent", name="agent-research-code")
    assert agent.post("/research/code/fix-lookup",
                      json={"fix_ref": "abc123"}).status_code == 403
    body = operator.post("/research/code/fix-lookup",
                         json={"fix_ref": "not a ref!!"})
    assert body.status_code == 422
    body = operator.post("/research/code/sibling-search",
                         json={"pattern": "everything"})
    assert body.status_code == 422


def test_research_api_returns_answers_and_audits(repo):
    from database import Database

    operator = _client("operator", name="op-research-code-2")
    sha = _commit(repo, {"pkg/views.py": (
        "class ShareLinkSerializer:\n"
        "    def validate_document(self, document):\n"
        "        if has_perms_owner_aware(self.user, 'view_document', document):\n"
        "            return document\n")}, "Fix GHSA-xxxx")
    response = operator.post("/research/code/fix-lookup",
                             json={"fix_ref": sha, "advisory_id": "GHSA-xxxx"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "validate_document" in payload["data"]["check_line"]
    events = Database().list_events(
        lab_id="research-code", limit=10, types=("research_code_lookup",))
    assert events and events[0]["payload"]["digest"] == payload["digest"]
    assert "has_perms_owner_aware" not in json.dumps(events[0]["payload"])


@pytest.mark.parametrize("route,body,function", [
    ("fix-lookup", {"fix_ref": "abc123"}, "fix_lookup"),
    ("layer-diff", {"from_ref": "HEAD", "to_ref": "HEAD"}, "layer_diff"),
    ("sibling-search", {"pattern": "bare-auth-view"}, "sibling_search"),
])
@pytest.mark.parametrize("unexpected", [False, True])
def test_admitted_research_failures_are_audited_without_error_content(
        repo, monkeypatch, route, body, function, unexpected):
    import research_code
    from database import Database

    name = f"audit-failure-{function}-{unexpected}"
    operator = _client("operator", name=name, raise_server_exceptions=False)

    def fail(*args, **kwargs):
        error = RuntimeError if unexpected else research_code.ResearchCodeError
        raise error("private-checkout-content-secret")

    monkeypatch.setattr(research_code, function, fail)
    response = operator.post(f"/research/code/{route}", json=body)
    assert response.status_code == (500 if unexpected else 422)
    events = Database().list_events(
        lab_id="research-code", limit=100, types=("research_code_lookup",))
    matches = [event for event in events if event["actor"] == name]
    assert len(matches) == 1
    payload = matches[0]["payload"]
    assert payload["tool"] == function
    assert payload["outcome"] == "failed"
    assert payload["status_code"] == response.status_code
    assert "private-checkout-content-secret" not in json.dumps(payload)
    assert "digest" not in payload


def test_half_composed_check_statuses(repo):
    import research_code

    _commit(repo, {"pkg/views.py": (
        "from rest_framework.permissions import IsAuthenticated\n"
        "class FullView:\n"
        "    permission_classes = (IsAuthenticated, PaperlessObjectPermissions)\n"
        "    def both(self):\n"
        "        if not request.user.has_perm('documents.view_thing'):\n"
        "            raise Denied()\n"
        "        return has_perms_owner_aware(u, 'view_thing', o)\n"
        "    def obj_only(self):\n"
        "        return has_perms_owner_aware(u, 'view_thing', o)\n"
        "class BareView:\n"
        "    permission_classes = (IsAuthenticated,)\n"
        "    def naked(self):\n"
        "        return has_perms_owner_aware(u, 'view_thing', o)\n"
        "value = has_perms_owner_aware(u, 'view_thing', o)\n")}, "views")
    result = research_code.sibling_search(
        repo, "HEAD", "half-composed-check", ["pkg/"])
    by_line = {s["line"]: s["status"] for s in result["data"]["sites"]}
    assert result["data"]["total_matches"] == 4
    # The object's implicit model namespace is not inferred from the global
    # permission it is being compared against.
    assert by_line[7] == "manual-review"
    assert by_line[9] == "class-covered"
    assert by_line[13] == "not composed"
    assert by_line[14] == "manual-review"


def test_unguarded_verb_statuses(repo):
    import research_code

    _commit(repo, {"pkg/views.py": (
        "from rest_framework.permissions import IsAuthenticated\n"
        "from rest_framework.decorators import action\n"
        "class GuardedView:\n"
        "    permission_classes = (IsAuthenticated, PaperlessObjectPermissions)\n"
        "    @action(methods=['get'], detail=True)\n"
        "    def listed(self, request, pk=None):\n"
        "        return has_perms_owner_aware(u, 'view_thing', o)\n"
        "class BareView:\n"
        "    permission_classes = (IsAuthenticated,)\n"
        "    @action(methods=['post'], detail=True)\n"
        "    def exposed(self, request, pk=None):\n"
        "        return do_thing()\n"
        "class CustomView:\n"
        "    permission_classes = (IsAuthenticated, CustomPerm)\n"
        "    @action(methods=['get'], detail=True)\n"
        "    def maybe(self, request, pk=None):\n"
        "        return do_other()\n")}, "verbs")
    result = research_code.sibling_search(
        repo, "HEAD", "unguarded-verb", ["pkg/"])
    by_line = {s["line"]: s["status"] for s in result["data"]["sites"]}
    assert result["data"]["total_matches"] == 3
    assert by_line[5] == "class-covered"
    assert by_line[10] == "not composed"
    assert by_line[15] == "manual-review"

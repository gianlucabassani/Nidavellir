"""Regression evidence for the independently reproduced code-intel defects."""
import json
import subprocess

import pytest

import research_code as code


@pytest.fixture()
def scratch(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def commit(repo, text, name="views.py"):
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "-c", "user.name=audit", "-c", "user.email=a@lab.invalid",
        "commit", "-qm", "scratch evidence")
    return git(repo, "rev-parse", "HEAD")


def search(repo, pattern):
    return code.sibling_search(repo, "HEAD", pattern, ["views.py"])


def test_byte_cut_reports_incomplete_counts(scratch):
    old = commit(scratch, "# " + "x" * 70000 + "\n")
    new = commit(scratch, "# " + "y" * 70000 +
                 "\npermission_classes = (IsAuthenticated,)\n")
    result = code.layer_diff(scratch, old, new, ["views.py"])
    assert result["truncation"]["truncated"]
    assert result["data"]["counts_complete"] is False
    assert "complete" not in result["truncation"]["note"] or "incomplete" in result["truncation"]["note"]


def test_external_diff_and_textconv_helpers_disabled(scratch, monkeypatch):
    old = commit(scratch, "x = 1\n")
    new = commit(scratch, "x = 2\n")
    marker = scratch / "executed"
    helper = scratch / "helper"
    helper.write_text(f"#!/bin/sh\nprintf executed > '{marker}'\n")
    helper.chmod(0o700)
    git(scratch, "config", "diff.external", str(helper))
    git(scratch, "config", "diff.hostile.textconv", str(helper))
    (scratch / ".gitattributes").write_text("*.py diff=hostile\n")
    monkeypatch.setenv("GIT_EXTERNAL_DIFF", str(helper))
    result = code.layer_diff(scratch, old, new, ["views.py"])
    assert not marker.exists()
    assert result["data"]["counts_complete"]
    code.fix_lookup(scratch, new)
    assert not marker.exists()


def test_subprocess_output_bounded_in_bytes(scratch):
    commit(scratch, "# " + "é" * 100000 + "\n")
    out = code.run_git(scratch, "show", "HEAD:views.py")
    assert out.truncated
    assert len(out.encode()) <= code.MAX_BYTES


def test_missing_object_cannot_launch_promisor_helper(scratch):
    commit(scratch, "x = 1\n")
    blob = git(scratch, "rev-parse", "HEAD:views.py")
    marker = scratch / "fetch-executed"
    helper = scratch / "fetch-helper"
    helper.write_text(f"#!/bin/sh\nprintf executed > '{marker}'\n")
    helper.chmod(0o700)
    git(scratch, "config", "remote.origin.promisor", "true")
    git(scratch, "config", "remote.origin.url", f"ext::{helper}")
    git(scratch, "config", "protocol.ext.allow", "always")
    (scratch / ".git/objects" / blob[:2] / blob[2:]).unlink()
    with pytest.raises(code.ResearchCodeError):
        code.run_git(scratch, "show", "HEAD:views.py")
    assert not marker.exists()


@pytest.mark.parametrize("args", [
    ("show", "--filters", "HEAD:views.py"),
    ("grep", "--open-files-in-pager=helper", "x", "HEAD"),
])
def test_other_helper_options_refused(scratch, args):
    commit(scratch, "x = 1\n")
    with pytest.raises(code.ResearchCodeError, match="refusing git argument"):
        code.run_git(scratch, *args)


def test_same_method_names_do_not_share_guards(scratch):
    commit(scratch, """class A:
    def get(self):
        permitted_object_ids(user, objects)
        return Thing.objects.filter(owner=user)
class B:
    def get(self):
        return Thing.objects.filter(secret=True)
""")
    sites = search(scratch, "unscoped-queryset")["data"]["sites"]
    assert sites[0]["status"] != sites[1]["status"]
    assert sites[1]["status"] == "uncovered"


@pytest.mark.parametrize("global_check", [
    "user.has_perm('unrelated.change_other')",
    "user.has_perm('documents.view_thing')",  # wrong verb
    "user.has_perm(variable)",
])
def test_irrelevant_or_dynamic_global_check_not_composed(scratch, global_check):
    commit(scratch, f"""class View:
    permission_classes = (IsAuthenticated,)
    def update(self):
        if not {global_check}:
            raise Denied()
        return has_perms_owner_aware(user, 'change_thing', thing)
""")
    site = search(scratch, "half-composed-check")["data"]["sites"][0]
    assert site["status"] != "composed"
    assert site["classification"]


def test_matching_enforced_global_argument_is_composed(scratch):
    commit(scratch, """class View:
    permission_classes = (IsAuthenticated,)
    def update(self):
        if not user.has_perms(['documents.change_thing']):
            raise Denied()
        return has_perms_owner_aware(user, 'documents.change_thing', thing)
""")
    assert search(scratch, "half-composed-check")["data"]["sites"][0]["status"] == "composed"


def test_permission_namespace_is_not_discarded(scratch):
    commit(scratch, """class View:
    permission_classes = (IsAuthenticated,)
    def update(self):
        if not user.has_perm('unrelated.change_thing'):
            raise Denied()
        return has_perms_owner_aware(user, 'documents.change_thing', thing)
""")
    assert search(scratch, "half-composed-check")["data"]["sites"][0]["status"] != "composed"


def test_conditional_denial_does_not_establish_guard(scratch):
    commit(scratch, """class View:
    permission_classes = (IsAuthenticated,)
    def update(self):
        if not user.has_perm('documents.change_thing') and feature_flag:
            raise Denied()
        return has_perms_owner_aware(user, 'documents.change_thing', thing)
""")
    site = search(scratch, "half-composed-check")["data"]["sites"][0]
    assert site["status"] == "manual-review"
    assert site["classification"] == "ambiguous-permission-control-flow"


def test_unreachable_denial_does_not_establish_guard(scratch):
    commit(scratch, """class View:
    permission_classes = (IsAuthenticated,)
    def update(self):
        if not user.has_perm('documents.change_thing'):
            return secrets()
            raise Denied()
        return has_perms_owner_aware(user, 'documents.change_thing', thing)
""")
    assert search(scratch, "half-composed-check")["data"]["sites"][0]["status"] == "manual-review"


def test_unused_permission_call_does_not_guard_action(scratch):
    commit(scratch, """class View:
    permission_classes = (IsAuthenticated,)
    @action(methods=['get'])
    def exposed(self):
        user.has_perm('documents.view_thing')
        return secrets()
""")
    assert search(scratch, "unguarded-verb")["data"]["sites"][0]["status"] == "not composed"


def test_queryset_forms_and_overwrite_are_classified(scratch):
    commit(scratch, """def bare():
    a = Thing.objects.all()
    b = Thing.objects.get(pk=1)
    return Thing.objects.exclude(owner=user)
def bulk():
    has_perms = user.has_perm('documents.change_thing')
    has_perms = user_is_owner_of_all_documents
    has_perms = has_perms and owner_check
    has_perms = False
""")
    assert search(scratch, "unscoped-queryset")["data"]["total_matches"] == 3
    sites = search(scratch, "bulk-permission")["data"]["sites"]
    assert [s["classification"] for s in sites] == [
        "initializer", "overwrite", "and-composed", "deny-reset"]
    assert sites[1]["status"] == "uncovered"


def test_field_and_envelope_cuts_reported(scratch):
    commit(scratch, "def bare():\n    return Thing.objects.filter(" +
           "name='" + "x" * 300 + "')\n")
    result = search(scratch, "unscoped-queryset")
    assert result["truncation"]["truncated"]
    assert "evidence" in result["truncation"]["note"]
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= code.MAX_BYTES


def test_unconfigured_repo_never_defaults_to_cwd(scratch, monkeypatch):
    commit(scratch, "x = 1\n")
    monkeypatch.chdir(scratch)
    monkeypatch.delenv("RESEARCH_REPO_DIR", raising=False)
    with pytest.raises(code.ResearchCodeError, match="not provisioned"):
        code.repo_root()


def test_fix_lookup_reports_long_evidence_and_file_limit(scratch):
    commit(scratch, "x = 1\n")
    for i in range(code.MAX_HUNKS + 1):
        (scratch / f"v{i}.py").write_text(
            "permission_classes = (IsAuthenticated,) # " + "x" * 300 + "\n")
    git(scratch, "add", ".")
    git(scratch, "-c", "user.name=audit", "-c", "user.email=a@lab.invalid",
        "commit", "-qm", "many checks")
    result = code.fix_lookup(scratch, "HEAD")
    assert result["truncation"]["truncated"]
    assert result["data"]["counts_complete"] is False
    assert "evidence" in result["truncation"]["note"]
    assert result["digest"] == code._digest({k: v for k, v in result.items() if k != "digest"})


def test_site_and_grep_limits_do_not_claim_complete_coverage(scratch, monkeypatch):
    commit(scratch, "def bare():\n" +
           "".join(f"    v{i} = Thing.objects.all()\n" for i in range(60)))
    result = search(scratch, "unscoped-queryset")
    assert result["data"]["total_matches"] == 60
    assert result["data"]["total_matches_complete"]
    assert len(result["data"]["sites"]) == code.MAX_SITES
    assert result["truncation"]["truncated"]
    original = code.run_git

    def smaller(repo, *args, **kwargs):
        if args[0] == "grep":
            kwargs["max_bytes"] = 512
        return original(repo, *args, **kwargs)

    monkeypatch.setattr(code, "run_git", smaller)
    partial = search(scratch, "unscoped-queryset")
    assert partial["truncation"]["truncated"]
    assert partial["data"]["total_matches_complete"] is False
    assert partial["data"]["total_matches"] < 60


def test_oversized_source_and_invalid_utf8_are_explicit(scratch):
    commit(scratch, "# " + "x" * code.MAX_FILE_BYTES +
           "\ndef bare():\n    return Thing.objects.all()\n")
    result = search(scratch, "unscoped-queryset")
    assert result["truncation"]["truncated"]
    assert result["data"]["sites"][0]["classification"] == "unparsed-source"
    assert code.GitOutput(b"bad\xffsource", False).truncated


def test_exact_diff_site_limit_is_not_truncation(scratch):
    old = commit(scratch, "x = 1\n")
    new = commit(scratch, "x = 1\n" + "permission_classes = ()\n" * code.MAX_DIFF_SITES)
    result = code.layer_diff(scratch, old, new, ["views.py"])
    assert len(result["data"]["sites"]) == code.MAX_DIFF_SITES
    assert not result["truncation"]["truncated"]


def test_checkout_owned_by_another_user_is_still_read(tmp_path, monkeypatch):
    """A read-only bind mount is owned by the host operator, not the service user.

    Git refuses such a repository unless it is named as safe. The service's Git
    calls ignore global config, so only the directory they were pointed at is named.
    """
    import subprocess

    import research_code

    root = tmp_path / "target"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@lab.invalid", "-c",
                    "user.name=lab", "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()
    real, commands = subprocess.Popen, []

    def other_owner(command, **kwargs):
        commands.append(command)
        kwargs["env"] = {**kwargs["env"], "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"}
        return real(command, **kwargs)

    monkeypatch.setattr(research_code.subprocess, "Popen", other_owner)
    assert research_code.run_git(root, "rev-parse", "HEAD").strip() == head
    safe = [token for token in commands[0] if token.startswith("safe.directory=")]
    assert safe == [f"safe.directory={root}"]

    # Without the exception the same read is refused, so the test proves the cause.
    def without_exception(command, **kwargs):
        kept = [token for token in command if not token.startswith("safe.directory=")]
        kept = [token for index, token in enumerate(kept)
                if not (token == "-c" and kept[index + 1:index + 2] == ["rev-parse"])]
        return other_owner(kept, **kwargs)

    monkeypatch.setattr(research_code.subprocess, "Popen", without_exception)
    with pytest.raises(research_code.ResearchCodeError, match="dubious ownership"):
        research_code.run_git(root, "rev-parse", "HEAD")


def test_repository_config_cannot_run_a_signature_program(tmp_path):
    """log.showSignature + gpg.program in .git/config would run a command on `log`."""
    import subprocess

    import research_code

    root = tmp_path / "target"
    root.mkdir()

    def git(*args, **kwargs):
        return subprocess.run(["git", "-C", str(root), *args], check=True,
                              capture_output=True, text=True, **kwargs).stdout.strip()

    git("init", "-q")
    tree = git("write-tree")
    # A commit that carries a signature header, as signed upstream merges do.
    signed = git("hash-object", "-t", "commit", "-w", "--stdin", input=(
        f"tree {tree}\nauthor lab <t@lab.invalid> 0 +0000\n"
        "committer lab <t@lab.invalid> 0 +0000\n"
        "gpgsig -----BEGIN PGP SIGNATURE-----\n \n iQEzBAAB\n -----END PGP SIGNATURE-----\n"
        "\nsigned commit\n"))
    marker = tmp_path / "ran"
    program = tmp_path / "fake-gpg"
    program.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
    program.chmod(0o755)
    git("config", "log.showSignature", "true")
    git("config", "gpg.program", str(program))

    # Control: plain Git with this config does run the program.
    subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%s", signed],
                   capture_output=True, check=False)
    assert marker.exists(), "the fixture does not trigger the signature program"
    marker.unlink()

    assert research_code.run_git(root, "log", "-1", "--format=%s", signed).strip() == "signed commit"
    research_code.run_git(root, "show", "--format=", signed)
    assert not marker.exists()


@pytest.mark.parametrize("verb", ["blame", "describe", "cat-file"])
def test_unused_git_verbs_are_refused(tmp_path, verb):
    import research_code

    with pytest.raises(research_code.ResearchCodeError, match="non-read git verb"):
        research_code.run_git(tmp_path, verb, "HEAD")


@pytest.mark.parametrize("lazy_fetch_guard", [True, False])
def test_partial_clone_never_fetches_a_missing_object(tmp_path, monkeypatch, lazy_fetch_guard):
    """A promisor remote in repository config must not make a read fetch.

    GIT_NO_LAZY_FETCH exists only from Git 2.45. Without it (older Git) the
    protocol allow-list alone has to hold, so both cases are exercised.
    """
    import subprocess

    import research_code

    def git(cwd, *args):
        return subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@lab.invalid",
                               "-c", "user.name=lab", *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    source, partial = tmp_path / "source", tmp_path / "partial"
    source.mkdir()
    git(source, "init", "-q")
    (source / "secret.py").write_text("value = 1\n")
    git(source, "add", "secret.py")
    git(source, "commit", "-q", "-m", "init")
    git(source, "config", "uploadpack.allowFilter", "true")
    blob = git(source, "rev-parse", "HEAD:secret.py")
    subprocess.run(["git", "clone", "-q", "--no-checkout", "--filter=blob:none",
                    f"file://{source}", str(partial)], check=True, capture_output=True)

    def present():
        # --batch-check with this variable never fetches; it only reports.
        result = subprocess.run(["git", "-C", str(partial), "cat-file", "-e", blob],
                                capture_output=True, check=False,
                                env={"PATH": "/usr/bin:/bin", "GIT_NO_LAZY_FETCH": "1",
                                     "GIT_ALLOW_PROTOCOL": ""})
        return result.returncode == 0

    assert not present(), "the fixture is not a partial clone"
    if not lazy_fetch_guard:
        real = subprocess.Popen

        def older_git(command, **kwargs):
            if "env" in kwargs:  # only the module's own calls carry one
                kwargs["env"] = {key: value for key, value in kwargs["env"].items()
                                 if key != "GIT_NO_LAZY_FETCH"}
            return real(command, **kwargs)

        monkeypatch.setattr(research_code.subprocess, "Popen", older_git)
    head = git(partial, "rev-parse", "HEAD")
    try:
        research_code.run_git(partial, "show", f"{head}:secret.py")
    except research_code.ResearchCodeError:
        pass  # refusing is fine; fetching is not
    assert not present(), "a read fetched the missing object from the promisor remote"
    monkeypatch.undo()

    # Control: plain Git on the same repository does fetch it.
    subprocess.run(["git", "-C", str(partial), "show", f"{head}:secret.py"],
                   capture_output=True, check=True)
    assert present()

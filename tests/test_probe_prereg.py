"""Registration must bind executable definitions before any fixture work."""
import copy
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("probe_paperless_variants", ROOT / "scripts/probe-paperless-variants.py")
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

FILES = ["scripts/probe-paperless-variants.py", "scripts/research_registration.py",
         "cyber-range/fixtures/paperless/build_fixture.py",
         "cyber-range/services/scenario-orchestrator/research_code.py"]


def _git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _commit(repo, message="registration"):
    _git(repo, "add", ".")
    _git(repo, "-c", "user.email=t@lab.invalid", "-c", "user.name=lab", "commit", "-q", "--allow-empty", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "history"
    root.mkdir()
    _git(root, "init", "-q")
    for name in FILES:
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((ROOT / name).read_bytes() if (ROOT / name).exists() else b"# gate not implemented yet\n")
    (root / "docs").mkdir()
    (root / "docs/JOURNAL.md").write_text("# journal\n")
    _commit(root, "seed")
    return root


def _registration(repo):
    # The candidate is reviewed/committed before a later call can execute it.
    assert hasattr(probe, "registration_candidate"), "structured registration is missing"
    return probe.registration_candidate("mail-hunt", root=repo)


def _register(repo, data=None):
    data = _registration(repo) if data is None else data
    path = repo / "docs/research/registrations/mail-hunt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return _commit(repo)


def test_substrings_do_not_bind_a_run(repo):
    (repo / "docs/JOURNAL.md").write_text("mail-hunt elsewhere\nhypotheses: CSS layout only\n")
    sha = _commit(repo)
    with pytest.raises(SystemExit, match="registration"):
        probe.check_prereg(sha, "mail-hunt", root=repo)


def test_valid_registration_retains_identity(repo):
    sha = _register(repo)
    receipt = probe.check_prereg(sha, "mail-hunt", root=repo)
    assert receipt["registration_commit"] == sha
    assert receipt["hypothesis_ids"] == [f"H{i}" for i in range(1, 7)] + [f"M{i}" for i in range(1, 7)]
    assert receipt["execution_digest"]
    assert receipt["registration_digest"]


@pytest.mark.parametrize("field", ["target", "hypotheses", "sources", "round_tag", "schema"])
def test_registration_field_mismatch_refused(repo, field):
    data = _registration(repo)
    data[field] = {"wrong": True}
    sha = _register(repo, data)
    with pytest.raises(SystemExit, match="registration"):
        probe.check_prereg(sha, "mail-hunt", root=repo)


def test_registered_m6_trash_is_not_executed_account_detail(repo):
    data = _registration(repo)
    m6 = next(h for h in data["hypotheses"] if h["id"] == "M6")
    m6["definitions"] = ["GET /api/trash/; DELETE /api/trash/{document}/"]
    # Keep every ID and every executable digest unchanged: name-only and
    # script-only gates both miss the registered-vs-executed substitution.
    sha = _register(repo, data)
    with pytest.raises(SystemExit, match="hypotheses"):
        probe.check_prereg(sha, "mail-hunt", root=repo)


@pytest.mark.parametrize("name", FILES)
def test_uncommitted_executable_drift_refused(repo, name):
    sha = _register(repo)
    with (repo / name).open("a") as handle:
        handle.write("\n# changed after registration\n")
    with pytest.raises(SystemExit, match="sources"):
        probe.check_prereg(sha, "mail-hunt", root=repo)


def test_uncommitted_manifest_does_not_replace_committed_one(repo):
    sha = _register(repo)
    path = repo / "docs/research/registrations/mail-hunt.json"
    path.write_text('{}')
    assert probe.check_prereg(sha, "mail-hunt", root=repo)["registration_commit"] == sha


def test_future_or_unknown_registration_refused(repo):
    sha = _register(repo)
    _git(repo, "checkout", "-q", "HEAD~1")
    with pytest.raises(SystemExit, match="ancestor"):
        probe.check_prereg(sha, "mail-hunt", root=repo)
    with pytest.raises(SystemExit, match="unknown"):
        probe.check_prereg("deadbeef", "mail-hunt", root=repo)


def test_bad_tag_and_extra_registration_fields_refused(repo):
    with pytest.raises(SystemExit, match="round-tag"):
        probe.check_prereg("deadbeef", "NOT A TAG!!", root=repo)
    data = _registration(repo)
    data["unbound_note"] = "M6 is trash despite the executable account request"
    sha = _register(repo, data)
    with pytest.raises(SystemExit, match="registration"):
        probe.check_prereg(sha, "mail-hunt", root=repo)


def test_refusal_precedes_fixture_import_and_stack_work(repo, monkeypatch):
    # Invalid registration must not even import the fixture, whose modified
    # top-level code could otherwise execute before the old gate.
    marker = repo / "fixture-imported"
    path = repo / FILES[2]
    path.write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    monkeypatch.setattr(probe, "ROOT", repo)
    with pytest.raises(SystemExit):
        probe.main(_git(repo, "rev-parse", "HEAD"), "mail-hunt")
    assert not marker.exists()


def test_missing_duplicate_or_extra_result_ids_refused(repo):
    assert hasattr(probe, "finalize_results"), "result correspondence is missing"
    receipt = probe.check_prereg(_register(repo), "mail-hunt", root=repo)
    results = [{"id": hid, "verdict": "infrastructure-failure"} for hid in receipt["hypothesis_ids"]]
    out = probe.finalize_results(results, receipt)
    assert out["registration"] == receipt
    assert out["recorded_hypothesis_ids"] == receipt["hypothesis_ids"]
    assert all(row["definition_digest"] for row in out["hypotheses"])
    for invalid in [results[:-1], results + results[:1], results + [{"id": "X1"}]]:
        with pytest.raises(SystemExit, match="hypothesis IDs"):
            probe.finalize_results(invalid, receipt)


def test_source_manifest_is_secret_free_and_target_pinned(repo):
    data = _registration(repo)
    assert data["target"]["version"] == "3.3.0"
    assert all("@sha256:" in image for image in data["target"]["pins"].values())
    encoded = json.dumps(data)
    assert "lab-admin-only" not in encoded
    assert "lab-member-only" not in encoded
    assert all(len(v) == 64 for v in data["sources"].values())
    assert hashlib.sha256((repo / FILES[0]).read_bytes()).hexdigest() == data["sources"][FILES[0]]


def test_changed_control_definition_is_refused_even_with_same_script(repo):
    data = copy.deepcopy(_registration(repo))
    m5 = next(h for h in data["hypotheses"] if h["id"] == "M5")
    m5["definitions"] = ["assert each target row survives"]
    with pytest.raises(SystemExit, match="hypotheses"):
        probe.check_prereg(_register(repo, data), "mail-hunt", root=repo)


def test_registration_for_new_disk_code_cannot_authorize_old_loaded_probe(repo):
    path = repo / FILES[0]
    path.write_text(path.read_text().replace('"M6", "MailAccountViewSet detail', '"M6", "changed definition'))
    sha = _register(repo)
    with pytest.raises(SystemExit, match="loaded executable"):
        probe.check_prereg(sha, "mail-hunt", root=repo)


def test_fixture_changed_after_gate_is_not_imported(repo, monkeypatch):
    sha = _register(repo)
    original = probe.check_prereg
    marker = repo / "fixture-imported-after-check"

    def race(*args, **kwargs):
        monkeypatch.setattr(probe, "check_prereg", original)
        receipt = original(*args, **kwargs)
        (repo / FILES[2]).write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
        return receipt

    monkeypatch.setattr(probe, "ROOT", repo)
    monkeypatch.setattr(probe, "check_prereg", race)
    with pytest.raises(SystemExit, match="fixture changed"):
        probe.main(sha, "mail-hunt")
    assert not marker.exists()


def test_valid_run_emits_receipt_for_all_recorded_ids(repo, monkeypatch, capsys):
    # Credential-free fixture adapter: exercise the real probe sequence and
    # final JSON envelope without Docker, sockets or a target experiment.
    path = repo / FILES[2]
    path.write_text('''VERSION = "3.3.0"
PINS = {"paperless": "example/paperless@sha256:" + "0" * 64}
ADMIN = {"password": "synthetic-admin"}
MEMBER = {"password": "synthetic-member"}
MAILBOX = {"password": "synthetic-mail"}
def build(keep=False):
    return {"base_url": "http://fixture.invalid", "tokens": {"A": "fake-a", "B": "fake-b"},
            "restricted_document": 1, "shared_document": 2, "member_id": 3, "mail_account_id": 4}
def run(*args, **kwargs):
    return None
def _call(base, method, path, **kwargs):
    if method == "GET" and path.startswith(("/api/share_links/?", "/api/groups/?", "/api/processed_mail/?")):
        return 200, {"results": [{"id": 5}]}
    return 200, {"versions": [{"id": 6}]}
'''.replace('"example/paperless@sha256:" + "0" * 64', repr("example/paperless@sha256:" + "0" * 64)))
    sha = _register(repo)
    cleanup = []
    monkeypatch.setattr(probe, "ROOT", repo)
    monkeypatch.setattr(probe.subprocess, "run", lambda argv, **kwargs: cleanup.append(argv))
    probe.main(sha, "mail-hunt")
    out = json.loads(capsys.readouterr().out)
    assert out["registration"]["registration_commit"] == sha
    assert out["recorded_hypothesis_ids"] == [f"H{i}" for i in range(1, 7)] + [f"M{i}" for i in range(1, 7)]
    assert all(row["definition_digest"] for row in out["hypotheses"])
    assert len(cleanup) == 7
    assert "fake-a" not in json.dumps(out)
    assert "fake-b" not in json.dumps(out)


def test_duplicate_json_keys_refused(repo):
    sha = _register(repo)
    path = repo / "docs/research/registrations/mail-hunt.json"
    raw = path.read_text()
    path.write_text('{"schema":"ignored",' + raw[1:])
    sha = _commit(repo)
    with pytest.raises(SystemExit, match="structured manifest"):
        probe.check_prereg(sha, "mail-hunt", root=repo)


def test_symlinked_executable_refused(repo, tmp_path):
    path = repo / FILES[2]
    outside = tmp_path / "fixture.py"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(SystemExit, match="source path"):
        _registration(repo)


def test_fresh_source_hash_does_not_hide_stale_loaded_m6_code(repo, monkeypatch):
    path = repo / FILES[0]
    value = path.read_text().replace('f"/api/mail_accounts/{acct}/", token=B),', 'f"/api/trash/{acct}/", token=B),')
    assert value != path.read_text()
    path.write_text(value)
    # A timestamp-cache import can execute older code while computing a fresh
    # __file__ hash at module startup. Emulate that hash without replacing main.
    monkeypatch.setattr(probe, "_LOADED_PROBE_DIGEST", hashlib.sha256(path.read_bytes()).hexdigest())
    sha = _register(repo)
    with pytest.raises(SystemExit, match="loaded executable"):
        probe.check_prereg(sha, "mail-hunt", root=repo)


def test_two_source_reads_cannot_bind_registered_bytes_to_other_loaded_code(repo, monkeypatch):
    import types

    sha = _register(repo)
    original = (repo / FILES[0]).read_bytes()
    different = original.replace(b'"M6", "MailAccountViewSet detail', b'"M6", "different executable detail')
    assert original != different
    compiled = compile(different, probe.main.__code__.co_filename, "exec", dont_inherit=True)
    other_main = next(c for c in compiled.co_consts if isinstance(c, types.CodeType) and c.co_name == "main")
    monkeypatch.setattr(probe.main, "__code__", other_main)
    original_read = probe.registration.source_bytes
    reads = []

    def changed_between_reads(root, name):
        if name == FILES[0]:
            reads.append(name)
            return original if len(reads) == 1 else different
        return original_read(root, name)

    monkeypatch.setattr(probe.registration, "source_bytes", changed_between_reads)
    with pytest.raises(SystemExit, match="loaded executable"):
        probe.check_prereg(sha, "mail-hunt", root=repo)


@pytest.mark.parametrize("replacement", ['"latest"', 'None'])
def test_unpinned_or_missing_target_identity_refused(repo, replacement):
    path = repo / FILES[2]
    with path.open("a") as handle:
        handle.write(f'\nPINS = {{"paperless": {replacement}}}\n')
    with pytest.raises(SystemExit, match="immutable target"):
        _registration(repo)


def test_stale_wrapper_cannot_omit_loaded_main_from_validation(repo, monkeypatch):
    import types

    sha = _register(repo)
    original = (repo / FILES[0]).read_bytes()
    different = original.replace(b'"M6", "MailAccountViewSet detail', b'"M6", "stale executable detail')
    different = different.replace(b'(main, status_of, finalize_results, registration_candidate, check_prereg)', b'(status_of,)')
    assert different != original
    compiled = compile(different, probe.main.__code__.co_filename, "exec", dont_inherit=True)
    functions = {c.co_name: c for c in compiled.co_consts if isinstance(c, types.CodeType)}
    monkeypatch.setattr(probe.main, "__code__", functions["main"])
    monkeypatch.setattr(probe.check_prereg, "__code__", functions["check_prereg"])
    with pytest.raises(SystemExit, match="loaded executable"):
        probe.check_prereg(sha, "mail-hunt", root=repo)

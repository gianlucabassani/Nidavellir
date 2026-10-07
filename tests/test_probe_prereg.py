"""RESEARCH-R4: the pre-reg gate binds content as well as ordering.

Proven against scratch git repos (no target, no network): an unrelated
ancestor commit is refused, a pre-reg commit introducing another round's
block is refused, and only a commit introducing this round's hypothesis
block passes — plus the bogus-sha and bad-tag refusals.
"""
import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "probe_paperless_variants",
    ROOT / "scripts/probe-paperless-variants.py")
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)


def _git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "history"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "-c", "user.email=t@lab.invalid", "-c", "user.name=lab",
         "commit", "-q", "--allow-empty", "-m", "init")
    (root / "docs").mkdir()
    (root / "docs/JOURNAL.md").write_text("# journal\n")
    _git(root, "add", "docs/JOURNAL.md")
    _git(root, "-c", "user.email=t@lab.invalid", "-c", "user.name=lab",
         "commit", "-q", "-m", "journal seed")
    return root


def _commit_journal(repo, text):
    with open(repo / "docs/JOURNAL.md", "a") as handle:
        handle.write(text)
    _git(repo, "add", "docs/JOURNAL.md")
    _git(repo, "-c", "user.email=t@lab.invalid", "-c", "user.name=lab",
         "commit", "-q", "-m", "round pre-registration")
    return _git(repo, "rev-parse", "HEAD").strip()


def test_unrelated_ancestor_refused(repo):
    sha = _git(repo, "rev-parse", "HEAD").strip()
    with pytest.raises(SystemExit, match="does not introduce"):
        probe.check_prereg(sha, "mail-hunt", root=repo)


def test_other_round_block_refused(repo):
    sha = _commit_journal(repo, "\n## PRE-REGISTRATION: endpoint round\n"
                                "hypotheses: H1 probe /\n")
    with pytest.raises(SystemExit, match="does not introduce"):
        probe.check_prereg(sha, "mail-hunt", root=repo)


def test_matching_block_accepted(repo, capsys):
    sha = _commit_journal(repo, "\n## PRE-REGISTRATION: mail-hunt\n"
                                "hypotheses: M1 process another account\n")
    probe.check_prereg(sha, "mail-hunt", root=repo)
    assert "mail-hunt" in capsys.readouterr().out


def test_bogus_sha_and_bad_tag_refused(repo):
    with pytest.raises(SystemExit, match="unknown pre-registration"):
        probe.check_prereg("deadbeef", "mail-hunt", root=repo)
    head = _git(repo, "rev-parse", "HEAD").strip()
    with pytest.raises(SystemExit, match="round-tag"):
        probe.check_prereg(head, "NOT A TAG!!", root=repo)

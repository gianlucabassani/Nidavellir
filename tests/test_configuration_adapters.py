"""Bounded Docker and Git adapters never execute profile code."""
from copy import deepcopy
from types import SimpleNamespace
import subprocess

import pytest

from configuration_capture import runtime_snapshot
from tests.test_configuration_capture import PROFILE, recipe
from providers.base import RangeProvider
from providers.docker_local import DockerLocalProvider
import research_code


def test_runtime_configuration_collects_only_profile_env_and_owned_nodes():
    class Containers:
        def list(self, *, all, filters):
            assert filters == {"label": "nidavellir.lab_id=runtime-arena"}
            return [SimpleNamespace(labels={"nidavellir.lab_id": "runtime-arena",
                "nidavellir.node": "target", "nidavellir.role": "victim"},
                attrs={"Config": {"Env": ["DISABLE_AUTH=true", "PRIVATE=hidden"]},
                       "State": {"Status": "running"}, "Image": "sha256:" + "a" * 64},
                reload=lambda: None, diff=lambda: [])]

    provider = object.__new__(DockerLocalProvider)
    provider._client = SimpleNamespace(containers=Containers())
    selectors = [{"kind": "runtime_env", "node": "target", "selector": "DISABLE_AUTH",
                  "key": "service.authorization.disabled"}]
    observed = provider.observe_configuration("runtime-arena", selectors)
    assert "hidden" not in repr(observed)
    profile = deepcopy(PROFILE)
    profile["facts"][0]["sources"].append({"kind": "runtime_env", "node": "target", "selector": "DISABLE_AUTH"})
    snapshot = runtime_snapshot("runtime-arena", recipe(profile=profile), observed)
    # Config.Env proves supplied input, not application consumption.
    assert snapshot["effective"][0]["value"] is False
    assert snapshot["effective"][0]["source_class"] == "scenario"
    assert snapshot["completeness"]["status"] == "partial"
    with pytest.raises(ValueError):
        provider.observe_configuration("runtime-arena", [{**selectors[0], "path": "/etc/shadow"}])
    with pytest.raises(NotImplementedError):
        RangeProvider.observe_configuration(SimpleNamespace(name="unverified"), "arena", selectors)


def test_active_runtime_readback_uses_fixed_bounded_observer():
    import json
    calls = []
    class Container:
        labels = {"nidavellir.lab_id": "readback-arena", "nidavellir.node": "target", "nidavellir.role": "victim"}
        attrs = {"State": {"Status": "running"}, "Image": "sha256:" + "a" * 64}
        def reload(self):
            pass
        def diff(self):
            return []
        def exec_run(self, command, **kwargs):
            calls.append(command)
            return SimpleNamespace(exit_code=0, output=json.dumps({
                "schema": "nidavellir/configuration-runtime/v1", "values": {"DISABLE_AUTH": True}}).encode())
    provider = object.__new__(DockerLocalProvider)
    provider._client = SimpleNamespace(containers=SimpleNamespace(list=lambda **_: [Container()]))
    observed = provider.observe_configuration("readback-arena", [{"kind": "runtime_readback", "node": "target",
        "key": "service.authorization.disabled", "selector": "DISABLE_AUTH"}])
    assert observed["facts"][0]["complete"] is True
    assert observed["facts"][0]["value"] is True
    assert len(calls) == 1
    assert "/oracle/configuration" in calls[0][-1]
    assert "16385" in calls[0][-1]


def test_configuration_history_reads_pinned_files_and_proves_ancestry(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()
    git("init")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.test")
    profile = deepcopy(PROFILE)
    profile["facts"][0]["sources"] = [{"kind": "source_file", "path": "defaults.env",
                                      "parser": "dotenv", "selector": "DISABLE_AUTH"}]
    refs = []
    for value in ("false", "true", "true"):
        (repo / "defaults.env").write_text("DISABLE_AUTH=" + value + "\n")
        (repo / "version").write_text(str(len(refs)))
        git("add", ".")
        git("commit", "-m", "state")
        refs.append(git("rev-parse", "HEAD"))
    history = research_code.configuration_history(repo, refs, profile)
    assert [item["facts"][0]["value"] for item in history["states"]] == [False, True, True]
    assert history["states"][1]["parent_digest"] == refs[0]
    assert history["states"][1]["adjacent_to_previous"] is True
    skipped = research_code.configuration_history(repo, [refs[0], refs[2]], profile)
    assert skipped["states"][1]["adjacent_to_previous"] is False
    with pytest.raises(research_code.ResearchCodeError):
        research_code.configuration_history(repo, [refs[0]] * 33, profile)
    bad = deepcopy(profile)
    bad["facts"][0]["sources"][0]["path"] = "../outside"
    with pytest.raises(ValueError):
        research_code.configuration_history(repo, refs, bad)

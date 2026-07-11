"""
M2 monitor tests (ROADMAP M2 item 5, ADR-0009).

Covers the pure crash oracle (`monitor.detect_signals`), the docker-local
`collect_monitor_signals` collector, the mock provider, and the `monitor_arenas`
Celery task (collect → detect → dedup → record), without Redis or a real daemon.
"""
import monitor


# --- pure detector: detect_signals ------------------------------------------

def _obs(name="victim", role="victim", state="running", exit_code=0,
         oom_killed=False, restart_count=0, log_tail=""):
    return {"name": name, "role": role, "state": state, "exit_code": exit_code,
            "oom_killed": oom_killed, "restart_count": restart_count, "log_tail": log_tail}


def test_healthy_running_container_yields_no_signal():
    assert monitor.detect_signals([_obs(state="running", exit_code=0)]) == []


def test_clean_exit_zero_is_not_a_crash():
    assert monitor.detect_signals([_obs(state="exited", exit_code=0)]) == []


def test_nonzero_exit_is_a_crash():
    sigs = monitor.detect_signals([_obs(state="exited", exit_code=139)])
    assert len(sigs) == 1
    assert sigs[0]["kind"] == monitor.CRASH
    assert sigs[0]["severity"] == "high"
    assert sigs[0]["node"] == "victim"
    assert "139" in sigs[0]["summary"]


def test_dead_state_nonzero_is_a_crash():
    sigs = monitor.detect_signals([_obs(state="dead", exit_code=1)])
    assert [s["kind"] for s in sigs] == [monitor.CRASH]


def test_oom_kill_is_resource_exhaustion_and_suppresses_generic_crash():
    # OOM sets exit 137; the more specific OOM signal wins, no duplicate crash.
    sigs = monitor.detect_signals([_obs(state="exited", exit_code=137, oom_killed=True)])
    assert [s["kind"] for s in sigs] == [monitor.RESOURCE_EXHAUSTION]
    assert "OOM" in sigs[0]["summary"]


def test_restart_count_over_threshold_is_crash_loop():
    sigs = monitor.detect_signals(
        [_obs(state="restarting", exit_code=1, restart_count=5)]
    )
    assert sigs[0]["kind"] == monitor.CRASH
    assert "crash-looping" in sigs[0]["summary"]


def test_running_with_restarts_is_not_flagged():
    # A container that restarted but is currently running is not crash-looping.
    assert monitor.detect_signals([_obs(state="running", restart_count=5)]) == []


def test_sanitizer_abort_detected_in_logs():
    log = "==1==ERROR: AddressSanitizer: heap-use-after-free on address 0x..."
    sigs = monitor.detect_signals([_obs(log_tail=log)])
    assert any(s["kind"] == monitor.SANITIZER_ABORT for s in sigs)


def test_ubsan_runtime_error_detected():
    log = "main.c:10:5: runtime error: signed integer overflow"
    sigs = monitor.detect_signals([_obs(log_tail=log)])
    assert [s["kind"] for s in sigs] == [monitor.SANITIZER_ABORT]


def test_python_traceback_is_unhandled_5xx():
    log = 'Traceback (most recent call last):\n  File "app.py"\nValueError: boom'
    sigs = monitor.detect_signals([_obs(log_tail=log)])
    assert any(s["kind"] == monitor.UNHANDLED_5XX for s in sigs)


def test_access_log_500_is_unhandled_5xx():
    log = '10.0.0.3 - - [x] "GET /boom HTTP/1.1" 500 120'
    sigs = monitor.detect_signals([_obs(log_tail=log)])
    assert any(s["kind"] == monitor.UNHANDLED_5XX for s in sigs)


def test_go_panic_is_a_crash():
    log = "panic: runtime error: index out of range [3] with length 2"
    sigs = monitor.detect_signals([_obs(state="running", log_tail=log)])
    assert any(s["kind"] == monitor.CRASH for s in sigs)


def test_benign_logs_yield_nothing():
    log = "listening on :8000\nGET / 200 5ms\nserving request\n"
    assert monitor.detect_signals([_obs(log_tail=log)]) == []


def test_keys_are_stable_across_log_churn_for_state_signals():
    # Same crash, different trailing log lines -> same dedup key (recorded once).
    a = monitor.detect_signals([_obs(state="exited", exit_code=2, log_tail="line A")])
    b = monitor.detect_signals([_obs(state="exited", exit_code=2, log_tail="line B different")])
    assert a[0]["key"] == b[0]["key"]


def test_distinct_faults_get_distinct_keys():
    crash = monitor.detect_signals([_obs(state="exited", exit_code=1)])[0]
    san = monitor.detect_signals([_obs(log_tail="ERROR: AddressSanitizer: bug")])[0]
    assert crash["key"] != san["key"]


def test_duplicate_lines_deduped_within_one_tick():
    log = "panic: boom\npanic: boom\npanic: boom"
    sigs = [s for s in monitor.detect_signals([_obs(log_tail=log)]) if s["kind"] == monitor.CRASH]
    assert len(sigs) == 1


def test_log_signals_are_capped_per_node():
    log = "\n".join(f'"GET /{i} HTTP/1.1" 500 1' for i in range(50))
    sigs = monitor.detect_signals([_obs(log_tail=log)])
    assert len(sigs) <= monitor._MAX_LOG_SIGNALS


def test_empty_and_none_observations():
    assert monitor.detect_signals([]) == []
    assert monitor.detect_signals(None) == []


# --- docker-local collector --------------------------------------------------

class _FakeC:
    def __init__(self, name, labels, state="running", exit_code=0,
                 oom=False, restarts=0, log=b""):
        self.name = name
        self.labels = labels
        self._log = log
        self.attrs = {
            "State": {"Status": state, "ExitCode": exit_code, "OOMKilled": oom},
            "RestartCount": restarts,
        }

    def reload(self):
        pass

    def logs(self, tail=200):
        return self._log


class _FakeContainersList:
    def __init__(self, containers):
        self._containers = containers

    def list(self, all=False, filters=None):
        return list(self._containers)


class _FakeClientList:
    def __init__(self, containers):
        self.containers = _FakeContainersList(containers)


def _provider(containers):
    from providers.docker_local import DockerLocalProvider
    return DockerLocalProvider(client=_FakeClientList(containers))


def test_collector_reports_observations_and_skips_harness():
    from providers.docker_local import LABEL_LAB_ID, LABEL_NODE, LABEL_ROLE
    base = {LABEL_LAB_ID: "arena-1"}
    containers = [
        _FakeC("nv-a-victim", {**base, LABEL_NODE: "victim", LABEL_ROLE: "victim"},
               state="exited", exit_code=139, log=b"boom\n"),
        _FakeC("nv-a-attacker", {**base, LABEL_NODE: "attacker", LABEL_ROLE: "attacker"}),
        _FakeC("nv-a-mirror", {**base, LABEL_NODE: "mirror", LABEL_ROLE: "mirror"}),
    ]
    result = _provider(containers).collect_monitor_signals("arena-1")
    assert result["success"] is True
    nodes = {o["name"] for o in result["observations"]}
    assert nodes == {"victim"}  # attacker + mirror skipped
    obs = result["observations"][0]
    assert obs["state"] == "exited" and obs["exit_code"] == 139
    assert obs["log_tail"].strip() == "boom"


def test_collector_feeds_detect_signals_end_to_end():
    from providers.docker_local import LABEL_LAB_ID, LABEL_NODE, LABEL_ROLE
    containers = [
        _FakeC("nv-a-web", {LABEL_LAB_ID: "arena-1", LABEL_NODE: "web", LABEL_ROLE: "victim"},
               state="running", log=b"ERROR: AddressSanitizer: heap-buffer-overflow\n"),
    ]
    result = _provider(containers).collect_monitor_signals("arena-1")
    sigs = monitor.detect_signals(result["observations"])
    assert [s["kind"] for s in sigs] == [monitor.SANITIZER_ABORT]
    assert sigs[0]["node"] == "web"


def test_mock_provider_collects_nothing():
    from providers.mock import MockProvider
    result = MockProvider().collect_monitor_signals("arena-1")
    assert result == {"success": True, "observations": []}


def test_base_provider_refuses_cleanly():
    import pytest
    from providers.base import RangeProvider

    class _Bare(RangeProvider):
        name = "bare"

        def deploy(self, *a, **k):
            return {"success": True, "outputs": {}}

        def destroy(self, *a, **k):
            return {"success": True}

    with pytest.raises(NotImplementedError):
        _Bare().collect_monitor_signals("arena-1")


# --- monitor_arenas task: collect -> detect -> dedup -> record ---------------

class _FakeDB:
    def __init__(self, deployments):
        self._deployments = deployments
        self.events = []  # (lab_id, type, payload, actor)

    def list_deployments(self):
        return self._deployments

    def list_events(self, lab_id=None, limit=100, types=None):
        out = []
        for lab, typ, payload, actor in reversed(self.events):
            if lab_id is not None and lab != lab_id:
                continue
            if types is not None and typ not in types:
                continue
            out.append({"lab_id": lab, "type": typ, "payload": payload, "actor": actor})
        return out[:limit]

    def record_event(self, lab_id, type, payload=None, actor="system"):
        self.events.append((lab_id, type, payload, actor))


def _run_monitor(monkeypatch, db, observations_by_arena):
    import tasks

    monkeypatch.setattr(tasks, "Database", lambda: db)

    class _FakeOrch:
        def __init__(self, provider_name=None):
            pass

        def collect_monitor_signals(self, instance_id):
            obs = observations_by_arena.get(instance_id)
            if obs is None:
                raise NotImplementedError
            return {"success": True, "observations": obs}

    monkeypatch.setattr(tasks, "Orchestrator", _FakeOrch)
    return tasks.monitor_arenas()


def test_task_records_signal_for_active_arena(monkeypatch):
    db = _FakeDB([{"id": "arena-1", "status": "active", "provider": "docker-local"}])
    out = _run_monitor(monkeypatch, db,
                       {"arena-1": [_obs(state="exited", exit_code=1, log_tail="boom")]})
    assert out == {"scanned": 1, "recorded": 1}
    assert len(db.events) == 1
    lab, typ, payload, actor = db.events[0]
    assert typ == "monitor_signal" and actor == "monitor"
    assert payload["kind"] == monitor.CRASH


def test_task_skips_non_active_arenas(monkeypatch):
    db = _FakeDB([{"id": "arena-1", "status": "destroying", "provider": "docker-local"}])
    out = _run_monitor(monkeypatch, db,
                       {"arena-1": [_obs(state="exited", exit_code=1)]})
    assert out == {"scanned": 0, "recorded": 0}
    assert db.events == []


def test_task_dedups_persistent_fault_across_ticks(monkeypatch):
    db = _FakeDB([{"id": "arena-1", "status": "active", "provider": "docker-local"}])
    obs = {"arena-1": [_obs(state="exited", exit_code=1, log_tail="boom")]}
    first = _run_monitor(monkeypatch, db, obs)
    second = _run_monitor(monkeypatch, db, obs)  # same fault next tick
    assert first["recorded"] == 1
    assert second["recorded"] == 0  # already on the stream
    assert len(db.events) == 1


def test_task_skips_provider_without_support(monkeypatch):
    db = _FakeDB([{"id": "vm-arena", "status": "active", "provider": "aws"}])
    # observations_by_arena has no entry -> _FakeOrch raises NotImplementedError
    out = _run_monitor(monkeypatch, db, {})
    assert out == {"scanned": 0, "recorded": 0}
    assert db.events == []

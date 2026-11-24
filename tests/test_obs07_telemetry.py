"""OBS-07 (FR-13): structured logs with request IDs, /metrics, optional OTLP."""
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import otlp
import spans
import tasks
import telemetry
from database import Database
from tests.research_support import active_arena, client

FAMILIES = (
    "nidavellir_http_request_duration_seconds",
    "nidavellir_task_duration_seconds",
    "nidavellir_arena_lifecycle_duration_seconds",
    "nidavellir_celery_queue_depth",
    "nidavellir_arenas",
    "nidavellir_budget_refusals_total",
    "nidavellir_validator_verdicts_total",
    "nidavellir_reaper_actions_total",
)


def test_metrics_exposes_every_family_and_requires_authority(monkeypatch):
    operator = client("operator")
    arena = active_arena()
    operator.post(f"/arenas/{arena}/exec", json={"node": "victim", "command": "id"})
    spans.record(Database(), name="exec", kind="tool", actor="a", actor_kind="agent",
                 arena_id=arena, status="budget_refused")
    body = operator.get("/metrics")
    assert body.status_code == 200 and body.headers["content-type"].startswith("text/plain")
    text = body.text
    for family in FAMILIES:
        assert f"# TYPE {family} " in text, family
    assert 'route="/arenas/{instance_id}/exec"' in text
    assert 'nidavellir_arenas{state="active"}' in text
    refusals = next(line for line in text.splitlines()
                    if line.startswith("nidavellir_budget_refusals_total "))
    assert int(refusals.split()[1]) >= 1

    from fastapi.testclient import TestClient
    import api
    anonymous = TestClient(api.app)
    assert anonymous.get("/metrics").status_code == 401
    assert client("agent").get("/metrics").status_code == 403
    monkeypatch.setenv("NIDAVELLIR_METRICS_TOKEN", "scrape-token-for-tests")
    assert anonymous.get("/metrics", headers={
        "Authorization": "Bearer scrape-token-for-tests"}).status_code == 200
    assert anonymous.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_request_ids_are_accepted_or_minted_returned_and_logged():
    operator = client("operator")
    given = operator.get("/scenarios", headers={"X-Request-ID": "trace-me-12345"})
    assert given.headers["X-Request-ID"] == "trace-me-12345"
    minted = operator.get("/scenarios", headers={"X-Request-ID": "bad id\x7f"})
    assert minted.headers["X-Request-ID"] != "bad id\x7f" and len(minted.headers["X-Request-ID"]) == 32

    token = telemetry.REQUEST_ID.set("rid-abcdef12")
    try:
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "hello %s", ("world",), None)
        line = json.loads(telemetry.JsonFormatter().format(record))
    finally:
        telemetry.REQUEST_ID.reset(token)
    assert line["msg"] == "hello world" and line["request_id"] == "rid-abcdef12"
    assert line["level"] == "INFO" and line["ts"].endswith("Z")


class _FakeRedis:
    def __init__(self):
        self.hashes, self.sets = {}, {}

    def pipeline(self):
        return self

    def hincrby(self, key, field, amount):
        h = self.hashes.setdefault(key, {})
        h[field] = h.get(field, 0) + amount

    hincrbyfloat = hincrby

    def sadd(self, key, member):
        self.sets.setdefault(key, set()).add(member)

    def execute(self):
        pass

    def smembers(self, key):
        return self.sets.get(key, set())

    def hgetall(self, key):
        return self.hashes.get(key, {})


def test_a_worker_task_logs_the_request_id_that_enqueued_it(monkeypatch):
    fake = _FakeRedis()
    import readiness
    monkeypatch.setattr(readiness, "redis_client", lambda *a, **k: fake)
    headers = {}
    token = telemetry.REQUEST_ID.set("api-request-777")
    try:
        tasks._carry_request_id(headers=headers)
    finally:
        telemetry.REQUEST_ID.reset(token)
    assert headers == {"nv_request_id": "api-request-777"}

    task = SimpleNamespace(name="tasks.deploy_lab",
                           request=SimpleNamespace(nv_request_id=headers["nv_request_id"]))
    tasks._enter_task_context(task_id="t-1", task=task, args=("arena-9",))
    record = logging.LogRecord("tasks", logging.INFO, __file__, 1, "deploying", (), None)
    line = json.loads(telemetry.JsonFormatter().format(record))
    tasks._leave_task_context(task_id="t-1", task=task, state="SUCCESS")
    assert line["request_id"] == "api-request-777" and line["arena_id"] == "arena-9"
    assert telemetry.REQUEST_ID.get() is None
    text = telemetry.render(redis_client=fake, arena_states={}, budget_refusals=0,
                            verdicts={}, reaper_actions={}, queue_depths={"celery": 3})
    assert 'nidavellir_task_duration_seconds_count{task="tasks.deploy_lab"} 1' in text
    assert 'nidavellir_arena_lifecycle_duration_seconds_count{operation="deploy"} 1' in text
    assert 'nidavellir_celery_queue_depth{queue="celery"} 3' in text


def test_otlp_export_delivers_a_trial_trace_to_a_local_collector(monkeypatch):
    received = []

    class Collector(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.path, json.loads(body)))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Collector)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{server.server_port}")
        db = Database()
        arena = active_arena()
        trace = spans.trace_id_for(arena_id=arena)
        spans.record(db, name="model.call", kind="model", actor="build-a", actor_kind="agent",
                     arena_id=arena, trial_id="trial-otlp", trace_id=trace,
                     attrs={"gen_ai.usage.input_tokens": 12})
        spans.record(db, name="exec", kind="tool", actor="build-a", actor_kind="agent",
                     arena_id=arena, status="error")
        otlp.flush()
        for _ in range(50):
            sent = [s for _, body in received for rs in body["resourceSpans"]
                    for ss in rs["scopeSpans"] for s in ss["spans"] if s["traceId"] == trace]
            if len(sent) == 2:
                break
            threading.Event().wait(0.1)
    finally:
        server.shutdown()
    assert received and received[0][0] == "/v1/traces"
    assert {s["name"] for s in sent} == {"model.call", "exec"}
    model = next(s for s in sent if s["name"] == "model.call")
    attrs = {a["key"]: a["value"] for a in model["attributes"]}
    assert attrs["gen_ai.usage.input_tokens"] == {"intValue": "12"}
    assert attrs["nv.trial_id"] == {"stringValue": "trial-otlp"}
    assert next(s for s in sent if s["name"] == "exec")["status"]["code"] == 2


def test_otlp_is_off_by_default(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert otlp.endpoint() is None
    otlp.export({"trace_id": "a" * 32, "span_id": "b" * 16, "name": "x"})  # no thread, no error

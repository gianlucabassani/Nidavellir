"""OBS-08: a finished run exports as one trace with findings linked to spans."""
import importlib.util
import io
import json
from pathlib import Path

from database import Database
from tests.research_support import active_arena, bind, client


def _spans(body):
    return [s for rs in body["resourceSpans"] for ss in rs["scopeSpans"] for s in ss["spans"]]


def _attrs(span):
    return {a["key"]: next(iter(a["value"].values())) for a in span["attributes"]}


def test_run_exports_as_one_trace_with_findings_and_verdicts_after_teardown():
    operator, agent = client("operator"), client("agent")
    arena = active_arena()
    bind(operator, arena, agent, "attacker")
    assert operator.post(f"/arenas/{arena}/exec",
                         json={"node": "victim", "command": "id"}).status_code == 200
    reported = agent.post(f"/arenas/{arena}/findings", json={"title": "IDOR on /admin",
                                                             "node": "victim"})
    assert reported.status_code == 200
    finding_id = reported.json()["finding_id"]
    verdict = operator.post(f"/arenas/{arena}/findings/{finding_id}/verify",
                            json={"verdict": "refuted", "note": "control showed no effect"})
    assert verdict.status_code == 200, verdict.text
    Database().update_deployment(arena, status="destroying", actor="test")
    Database().update_deployment(arena, status="destroyed", actor="test")

    response = operator.get(f"/arenas/{arena}/trace")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    body = response.json()
    sent = _spans(body)
    assert len({s["traceId"] for s in sent}) == 1
    assert [s["name"] for s in sent] == ["exec", "findings", "findings/verify"]
    linked = [_attrs(s) for s in sent if _attrs(s).get("nv.finding_id") == finding_id]
    assert len(linked) == 2  # the report and the verdict
    assert all(a["nv.finding.verdict"] == "refuted" and a["nv.finding.title"] == "IDOR on /admin"
               for a in linked)
    resource = {a["key"]: a["value"]["stringValue"] for a in body["resourceSpans"][0]["resource"]["attributes"]}
    assert resource["nv.arena_id"] == arena
    assert agent.get(f"/arenas/{arena}/trace").status_code == 403
    assert operator.get("/arenas/missing/trace").status_code == 404


def test_cli_writes_the_trace(monkeypatch, tmp_path, capsys):
    path = Path(__file__).resolve().parents[1] / "scripts" / "nv-trace-export.py"
    spec = importlib.util.spec_from_file_location("nv_trace_export", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    body = {"resourceSpans": [{"resource": {"attributes": []}, "scopeSpans": [
        {"scope": {"name": "x"}, "spans": [{"traceId": "a" * 32, "spanId": "b" * 16},
                                           {"traceId": "a" * 32, "spanId": "c" * 16}]}]}]}
    seen = {}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        seen["url"], seen["key"] = request.full_url, request.headers.get("X-api-key")
        return Response(json.dumps(body).encode())

    monkeypatch.setattr(module.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("NIDAVELLIR_API_KEY", "operator-key-for-test")
    monkeypatch.setenv("NIDAVELLIR_API_URL", "http://127.0.0.1:8000")
    out = tmp_path / "t.json"
    assert module.main(["arena/1", "-o", str(out)]) == 0
    assert seen["url"] == "http://127.0.0.1:8000/arenas/arena%2F1/trace"
    assert seen["key"] == "operator-key-for-test"
    assert json.loads(out.read_text()) == body
    assert "exported 2 spans in 1 trace(s)" in capsys.readouterr().err
    monkeypatch.delenv("NIDAVELLIR_API_KEY")
    assert module.main(["arena"]) == 2

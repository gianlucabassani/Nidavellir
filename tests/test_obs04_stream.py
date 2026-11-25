"""OBS-04 (FR-14): a real push stream with Last-Event-ID replay.

Inserts publish to Redis after commit; the orchestrator's SSE reads the
database only when a message arrives (no periodic polls), resumes from the
event+span cursor without losing or repeating rows, and gives agent keys only
allowlisted event kinds and agent-visible spans.
"""
import json
import time


import spans
import streams
from database import Database
from tests.research_support import active_arena, bind, client


def _parse(frames):
    """[(event name, id, data)] from SSE text frames."""
    out = []
    for frame in frames:
        if frame.startswith(":") or frame.startswith("retry"):
            continue
        fields = dict(line.split(": ", 1) for line in frame.strip().splitlines())
        out.append((fields["event"], fields.get("id"), json.loads(fields["data"])))
    return out


class _Store:
    def __init__(self):
        self.events, self.spans, self.reads = [], [], 0

    def read_events(self, after, limit):
        self.reads += 1
        return [e for e in self.events if e["id"] > after][:limit]

    def read_spans(self, after, limit):
        return [s for s in self.spans if s["id"] > after][:limit]

    def latest(self):
        return (self.events[-1]["id"] if self.events else 0,
                self.spans[-1]["id"] if self.spans else 0)


class _PubSub:
    def __init__(self, store=None, inject=None):
        self.store, self.inject, self.closed = store, inject or [], False

    def get_message(self, ignore_subscribe_messages=True, timeout=0.0):
        if self.inject:
            kind, row = self.inject.pop(0)
            getattr(self.store, kind).append(row)
            return {"type": "message", "data": "{}"}
        time.sleep(timeout)
        return None

    def close(self):
        self.closed = True


def _frames(store, cursor, pubsub, seconds=0.4):
    return list(streams.arena_frames(
        arena_id="a", cursor=cursor, read_events=store.read_events,
        read_spans=store.read_spans, read_state=lambda: {"status": "active", "outputs": {}},
        latest=store.latest, subscribe=lambda _a: pubsub, max_seconds=seconds))


def test_no_periodic_reads_without_messages(monkeypatch):
    monkeypatch.setattr(streams, "KEEPALIVE_SECONDS", 0.05)
    store = _Store()
    store.events = [{"id": 1, "type": "created"}]
    pubsub = _PubSub()
    gen = streams.arena_frames(
        arena_id="a", cursor=None, read_events=store.read_events,
        read_spans=store.read_spans, read_state=lambda: {"status": "active", "outputs": {}},
        latest=store.latest, subscribe=lambda _a: pubsub, max_seconds=0.5)
    frames, reads_at_first_keepalive = [], None
    for frame in gen:
        frames.append(frame)
        if frame.startswith(": keepalive") and reads_at_first_keepalive is None:
            reads_at_first_keepalive = store.reads
    # One initial drain (a batch, then the empty read that ends it); keepalives
    # are comments and never read the database.
    assert reads_at_first_keepalive == store.reads == 2
    assert sum(f.startswith(": keepalive") for f in frames) >= 3
    assert pubsub.closed


def test_a_message_pushes_new_rows_and_reconnect_loses_nothing(monkeypatch):
    monkeypatch.setattr(streams, "KEEPALIVE_SECONDS", 0.05)
    store = _Store()
    store.events = [{"id": i, "type": "agent_exec"} for i in (1, 2)]
    pubsub = _PubSub(store, inject=[("events", {"id": 3, "type": "agent_exec"}),
                                    ("spans", {"id": 7, "name": "exec"})])
    first = _parse(_frames(store, (0, 0), pubsub))
    seen_events = [e["id"] for name, _, d in first if name == "activity" for e in d["events"]]
    seen_spans = [s["id"] for name, _, d in first if name == "spans" for s in d["spans"]]
    assert seen_events == [1, 2, 3] and seen_spans == [7]
    last_id = [i for _, i, _ in first if i][-1]
    assert last_id == "3.7"
    # Rows written while disconnected arrive on reconnect, nothing repeats.
    store.events.append({"id": 4, "type": "status"})
    store.spans.append({"id": 8, "name": "http/request"})
    second = _parse(_frames(store, streams.parse_cursor(last_id), _PubSub()))
    assert [e["id"] for n, _, d in second if n == "activity" for e in d["events"]] == [4]
    assert [s["id"] for n, _, d in second if n == "spans" for s in d["spans"]] == [8]
    # A status event re-sends the arena state.
    assert [n for n, _, _ in second].count("state") == 2


def test_first_connection_backfills_recent_context():
    store = _Store()
    store.events = [{"id": i, "type": "x"} for i in range(1, 101)]
    frames = _parse(_frames(store, None, _PubSub(), seconds=0.1))
    events = [e["id"] for n, _, d in frames if n == "activity" for e in d["events"]]
    assert events == list(range(61, 101))


def test_cursor_parsing():
    assert streams.parse_cursor("12.5") == (12, 5)
    assert streams.parse_cursor("12") == (12, 0)
    for bad in (None, "", "x.y", "a"):
        assert streams.parse_cursor(bad) is None


def test_inserts_publish_after_commit_only(monkeypatch):
    sent = []
    monkeypatch.setattr(streams, "publish", lambda messages, evaluations=(): sent.extend(messages))
    db = Database()
    arena = active_arena()
    sent.clear()
    db.record_event(arena, "agent_exec", {"command": "id"}, actor="a")
    span_id = spans.record(db, name="exec", kind="tool", actor="a", actor_kind="agent",
                           arena_id=arena)
    kinds = [(a, k) for a, k, _ in sent]
    assert (arena, "event") in kinds and (arena, "span") in kinds
    assert (arena, "span", span_id) in sent


def _stream(c, arena, **headers):
    with c.stream("GET", f"/arenas/{arena}/stream", headers=headers) as r:
        assert r.status_code == 200
        return _parse([b + "\n\n" for b in r.read().decode().split("\n\n") if b.strip()])


def test_api_stream_filters_for_agents(monkeypatch):
    monkeypatch.setattr(streams, "MAX_SECONDS", 0.3)
    monkeypatch.setattr(streams, "redis_subscribe", lambda _a: None)
    monkeypatch.setattr(streams, "FALLBACK_POLL_SECONDS", 0.05)
    db = Database()
    operator, agent, stranger = client("operator"), client("agent"), client("agent")
    arena = active_arena()
    bind(operator, arena, agent, "attacker")
    db.record_event(arena, "agent_exec", {"command": "id"}, actor=agent.name)
    db.record_event(arena, "lifecycle_observation", {"truth": "hidden"}, actor="worker")
    spans.record(db, name="exec", kind="tool", actor=agent.name, actor_kind="agent",
                 arena_id=arena)
    spans.record(db, name="validate", kind="validation", actor="worker",
                 actor_kind="system", arena_id=arena)

    op = _stream(operator, arena)
    op_types = {e["type"] for n, _, d in op if n == "activity" for e in d["events"]}
    assert {"agent_exec", "lifecycle_observation"} <= op_types
    assert {s["name"] for n, _, d in op if n == "spans" for s in d["spans"]} == {"exec", "validate"}

    mine = _stream(agent, arena)
    types = {e["type"] for n, _, d in mine if n == "activity" for e in d["events"]}
    assert "agent_exec" in types and "lifecycle_observation" not in types
    assert {s["name"] for n, _, d in mine if n == "spans" for s in d["spans"]} == {"exec"}
    state = next(d for n, _, d in mine if n == "state")
    assert state["status"] == "active" and "node_victim_name" in state["outputs"]

    with stranger.stream("GET", f"/arenas/{arena}/stream") as r:
        assert r.status_code == 403

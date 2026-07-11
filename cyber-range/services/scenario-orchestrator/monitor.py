"""
monitor.py — service-under-test monitoring: turn raw per-node runtime
observations into structured, scoring-ready signals (ROADMAP M2, ADR-0009).

Pure and network-free (like `repo_introspect.analyze` / `build_planner.plan_build`):
`detect_signals(observations)` takes what a provider observed about each arena
node — container state plus a bounded tail of its logs — and returns a list of
monitor signals. A crash, a sanitizer abort, an unhandled 5xx, or resource
exhaustion is first-class evidence, so a target with **no known-CVE manifest is
still scorable** (the M2 unlock). The Celery `monitor_arenas` task polls
providers, runs this, and appends new signals to the append-only `events` stream
(the defender feed + the input the M2 scorer will consume).

Provider observation contract (one dict per node):
    {name, role, state, exit_code, oom_killed, restart_count, log_tail}

Signal shape:
    {kind, node, severity, summary, evidence, key}

`key` is a stable dedup fingerprint: the monitor records a persistent fault once,
not on every tick. State signals key off the fault itself (exit code / oom /
crash-loop) so log churn doesn't re-fire them; log signals key off the matched
line so a genuinely new fault line surfaces while a repeated one stays deduped.

The deterministic **state** signals (non-zero exit, OOM-kill, crash-loop) are the
reliable ones. The **log** heuristics are deliberately conservative best-effort —
they add coverage (a worker process that crashed while its container lives on)
without pretending to be exhaustive; the M2 deterministic validators (item 6)
are what confirm a finding before it is credited.
"""
import hashlib
import re

# Signal kinds.
CRASH = "crash"
SANITIZER_ABORT = "sanitizer_abort"
UNHANDLED_5XX = "unhandled_5xx"
RESOURCE_EXHAUSTION = "resource_exhaustion"

SEVERITY = {
    CRASH: "high",
    SANITIZER_ABORT: "high",
    RESOURCE_EXHAUSTION: "high",
    UNHANDLED_5XX: "medium",
}

_KIND_SUMMARY = {
    SANITIZER_ABORT: "sanitizer abort reported in logs",
    RESOURCE_EXHAUSTION: "resource exhaustion reported in logs",
    CRASH: "crash indicator reported in logs",
    UNHANDLED_5XX: "unhandled server error / 5xx in logs",
}

# Restart count at/above which a non-running container is treated as crash-looping.
CRASH_LOOP_RESTARTS = 2

# Bound the evidence stored per signal (keeps a chatty log out of the DB/payload).
_MAX_EVIDENCE = 1200
# How many distinct log lines we turn into signals per node per tick.
_MAX_LOG_SIGNALS = 5
# Tail of the log kept as evidence for a state signal.
_STATE_EVIDENCE_LINES = 8

# Log-line patterns -> signal kind, tried in order; the first match on a line
# wins. CRASH is first so a Go `panic: runtime error: ...` line is a crash, not
# mistaken for a UBSan `runtime error:` abort. Kept conservative on purpose —
# see the module docstring.
_LOG_RULES: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    (CRASH, re.compile(
        r"Segmentation fault|SIGSEGV|SIGABRT|core dumped|"
        r"fatal runtime error|goroutine \d+ \[|panic:|panicked")),
    (SANITIZER_ABORT, re.compile(
        r"AddressSanitizer|LeakSanitizer|ThreadSanitizer|"
        r"UndefinedBehaviorSanitizer|MemorySanitizer|"
        r"runtime error:|SUMMARY:\s+\w*Sanitizer")),
    (RESOURCE_EXHAUSTION, re.compile(
        r"OutOfMemoryError|Cannot allocate memory|std::bad_alloc|"
        r"too many open files|No space left on device")),
    (UNHANDLED_5XX, re.compile(
        r"Traceback \(most recent call last\)|Unhandled exception|"
        r"Internal Server Error|\"\s*5\d\d\s|HTTP/1\.[01]\"?\s+5\d\d")),
)


def detect_signals(observations) -> list[dict]:
    """Turn provider observations into deduplicated monitor signals."""
    signals: list[dict] = []
    for obs in observations or []:
        node = obs.get("name") or "?"
        state = (obs.get("state") or "").lower()
        exit_code = obs.get("exit_code")
        oom = bool(obs.get("oom_killed"))
        restarts = int(obs.get("restart_count") or 0)
        log_tail = obs.get("log_tail") or ""

        # --- deterministic state signals (the reliable ones) ------------------
        # OOM is the more specific cause than the exit code it also produces
        # (137), so it wins the elif-chain and we don't double-count.
        if oom:
            signals.append(_signal(
                RESOURCE_EXHAUSTION, node,
                f"{node} was OOM-killed (out of memory)",
                _last_lines(log_tail), key_basis="oom"))
        elif state in ("exited", "dead") and exit_code not in (0, None):
            signals.append(_signal(
                CRASH, node,
                f"{node} exited with a non-zero status ({exit_code})",
                _last_lines(log_tail), key_basis=f"exit:{exit_code}"))
        elif state == "restarting" or (restarts >= CRASH_LOOP_RESTARTS and state != "running"):
            signals.append(_signal(
                CRASH, node,
                f"{node} is crash-looping (restart_count={restarts})",
                _last_lines(log_tail), key_basis="crashloop"))

        # --- log-derived signals (conservative best-effort) -------------------
        for kind, line in _scan_logs(log_tail):
            signals.append(_signal(
                kind, node, f"{node}: {_KIND_SUMMARY[kind]}",
                line, key_basis=line))

    return _dedup(signals)


def _scan_logs(log_tail: str) -> list[tuple[str, str]]:
    """Return up to `_MAX_LOG_SIGNALS` (kind, matched_line) pairs from a log tail."""
    out: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in (log_tail or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        for kind, pat in _LOG_RULES:
            if pat.search(line):
                fp = (kind, line)
                if fp not in seen:
                    seen.add(fp)
                    out.append((kind, line))
                break
        if len(out) >= _MAX_LOG_SIGNALS:
            break
    return out


def _last_lines(text: str, n: int = _STATE_EVIDENCE_LINES) -> str:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def _signal(kind: str, node: str, summary: str, evidence: str,
            key_basis: str | None = None) -> dict:
    evidence = (evidence or "").strip()[:_MAX_EVIDENCE]
    basis = key_basis if key_basis is not None else evidence
    # sha256 (not sha1) so bandit doesn't flag it; this is a dedup fingerprint,
    # never a security control.
    digest = hashlib.sha256(f"{kind}|{node}|{basis}".encode("utf-8", "replace")).hexdigest()[:12]
    return {
        "kind": kind,
        "node": node,
        "severity": SEVERITY.get(kind, "medium"),
        "summary": summary,
        "evidence": evidence,
        "key": f"{kind}:{node}:{digest}",
    }


def _dedup(signals: list[dict]) -> list[dict]:
    """Keep the first signal per `key`, preserving order."""
    seen: set[str] = set()
    out: list[dict] = []
    for sig in signals:
        if sig["key"] in seen:
            continue
        seen.add(sig["key"])
        out.append(sig)
    return out

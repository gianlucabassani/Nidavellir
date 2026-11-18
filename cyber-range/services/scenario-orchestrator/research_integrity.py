"""
Research integrity layer (work order 2026-11-18, phase 2).

Makes the *record* enforce the research method instead of trusting the agent
to follow it. Pure logic only: the API layer owns authorization, persistence
(append-only audit events, serialized by ``Database.guarded_append``) and the
per-arena ``research_mode`` opt-in. Nothing here changes behaviour for an arena
whose operator has not switched research mode on.

R1 — hypothesis contract: a probe in research mode must cite a registered,
     still-open hypothesis whose declared ``probe_budget`` is not spent.
R2 — root-cause fingerprint: a finding in research mode states its root cause;
     the normalised fingerprint links it to earlier findings of the same
     lineage as ``duplicate``/``variant``/``independent``, and a duplicate can
     never be confirmed.
R3 — causality gate: in research mode a finding is confirmed only when its
     record cites a trace, a fixed-build (or guard) control and the single
     toggle, each backed by an immutable evidence digest.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

# --- events -------------------------------------------------------------------

MODE_EVENT = "research_mode"
HYPOTHESIS_REGISTERED = "hypothesis_registered"
HYPOTHESIS_TESTED = "hypothesis_tested"
HYPOTHESIS_PROBE = "hypothesis_probe"
HYPOTHESIS_EVENT_TYPES = (HYPOTHESIS_REGISTERED, HYPOTHESIS_TESTED, HYPOTHESIS_PROBE)


class ResearchRefused(Exception):
    """A typed refusal; the API maps it to ``status`` with ``{code, message}``."""

    def __init__(self, code: str, message: str, status: int = 409, **extra):
        super().__init__(message)
        self.code = code
        self.status = status
        self.extra = extra

    def detail(self) -> dict:
        return {"code": self.code, "message": str(self), **self.extra}


# --- R1: hypothesis contract ----------------------------------------------------

HYPOTHESIS_SCHEMA = "nidavellir.hypothesis.v1"
SOURCES = ("fix-diff", "primitive", "history", "invariant", "fuzz", "paper")
OUTCOMES = ("supported", "refuted", "inconclusive")
MAX_PROBE_BUDGET = 500

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1024)]


class SourceSink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Text
    sink: Text


class HypothesisContract(BaseModel):
    """One falsifiable research hypothesis. Every field is required: a contract
    that cannot say how it would be disproved (``negative_control``), when to
    stop (``stop_condition``, ``probe_budget``) or what it duplicates
    (``dedup_key``) is not registered."""

    model_config = ConfigDict(extra="forbid", title="Nidavellir research hypothesis")

    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$",
                    description="Caller-chosen id, unique per arena")
    source: Literal[SOURCES]  # type: ignore[valid-type]
    provenance: Text = Field(description="Commit, advisory or citation the idea comes from")
    preconditions: list[Text] = Field(min_length=1, max_length=20,
                                      description="State/rights the trigger needs; "
                                                  "state 'none' explicitly")
    invariant: Text = Field(description="The property the target is supposed to keep")
    source_sink: SourceSink
    expected_observable: Text = Field(description="What the probe should observe if true")
    negative_control: Text = Field(description="The observation that would refute it")
    dedup_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1,
                                                max_length=256)]
    probe_budget: int = Field(ge=1, le=MAX_PROBE_BUDGET)
    stop_condition: Text


REQUIRED_FIELDS = tuple(HypothesisContract.model_fields)


def hypothesis_json_schema() -> dict:
    return {"$id": HYPOTHESIS_SCHEMA, **HypothesisContract.model_json_schema()}


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def contract_digest(contract: dict) -> str:
    return "sha256:" + hashlib.sha256(_canonical(contract)).hexdigest()


def validate_contract(raw) -> dict:
    """Return the normalised contract or raise ``ResearchRefused`` (422) naming
    every missing field first, then every malformed one."""
    if not isinstance(raw, dict):
        raise ResearchRefused("invalid_hypothesis", "a hypothesis contract is a JSON object",
                              status=422, missing=list(REQUIRED_FIELDS), errors=[])
    missing = [name for name in REQUIRED_FIELDS if raw.get(name) is None]
    try:
        contract = HypothesisContract.model_validate(raw)
    except ValidationError as exc:
        errors = [{"field": ".".join(str(part) for part in item["loc"]), "message": item["msg"]}
                  for item in exc.errors(include_input=False, include_context=False,
                                         include_url=False)
                  if not (len(item["loc"]) == 1 and item["loc"][0] in missing)]
        message = ("missing required field(s): " + ", ".join(missing) if missing
                   else "invalid field(s): " + ", ".join(e["field"] for e in errors))
        raise ResearchRefused("invalid_hypothesis", message, status=422,
                              missing=missing, errors=errors) from exc
    return contract.model_dump()


def hypothesis_views(events: list[dict]) -> dict[str, dict]:
    """Current state per hypothesis id from newest-first hypothesis events.
    Status is ``open`` until a ``hypothesis_tested`` event closes it."""
    views: dict[str, dict] = {}
    for event in reversed(events):
        payload = event.get("payload") or {}
        kind = event.get("type")
        if kind == HYPOTHESIS_REGISTERED:
            contract = payload.get("contract") or {}
            hid = contract.get("id")
            if hid and hid not in views:
                views[hid] = {"id": hid, "status": "open", "outcome": None,
                              "source": contract.get("source"),
                              "probe_budget": contract.get("probe_budget"),
                              "probes_used": 0,
                              "contract_digest": payload.get("contract_digest"),
                              "registered_by": event.get("actor"),
                              "registered_at": event.get("ts"), "contract": contract}
        elif kind == HYPOTHESIS_PROBE:
            view = views.get(payload.get("hypothesis_id"))
            if view is not None:
                view["probes_used"] += 1
        elif kind == HYPOTHESIS_TESTED:
            view = views.get(payload.get("hypothesis_id"))
            if view is not None and view["status"] == "open":
                view.update(status="tested", outcome=payload.get("outcome"),
                            tested_by=event.get("actor"), tested_at=event.get("ts"))
    return views


def hypothesis_counts(views: dict[str, dict]) -> dict:
    counts = {"open": 0, "tested": 0}
    for view in views.values():
        counts[view["status"]] = counts.get(view["status"], 0) + 1
    return counts


def require_probe_allowed(views: dict[str, dict], hypothesis_id: str) -> dict:
    """The probe gate: the cited hypothesis exists, is open and has budget."""
    view = views.get(hypothesis_id)
    if view is None:
        raise ResearchRefused("unknown_hypothesis",
                              f"hypothesis {hypothesis_id!r} is not registered on this arena; "
                              "POST /arenas/{id}/hypotheses first", status=404)
    if view["status"] != "open":
        raise ResearchRefused("hypothesis_closed",
                              f"hypothesis {hypothesis_id!r} is already tested "
                              f"({view['outcome']}); register a new one")
    if view["probes_used"] >= (view["probe_budget"] or 0):
        raise ResearchRefused("probe_budget_exhausted",
                              f"hypothesis {hypothesis_id!r} spent its probe_budget of "
                              f"{view['probe_budget']}; mark it tested or register a new one",
                              status=429)
    return view


# --- R2: root-cause fingerprint -------------------------------------------------

FINGERPRINT_VERSION = "rcfp1"
ROOT_CAUSE_PARTS = ("invariant", "owner_lifetime", "source", "sink", "missing_check")
DUPLICATE, VARIANT, INDEPENDENT = "duplicate", "variant", "independent"

Part = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)]


class RootCause(BaseModel):
    """What is wrong, independent of how the finding was titled or which build
    showed it. ``oracle`` is the observable behaviour that proves it."""

    model_config = ConfigDict(extra="forbid")

    invariant: Part
    owner_lifetime: Part
    source: Part
    sink: Part
    missing_check: Part
    oracle: Part


# Build-specific noise that must not split one root cause into many: source
# line references, memory addresses and dotted version numbers.
_LINE_REF = re.compile(r":\d+(?::\d+)?\b|#L\d+\b|\bline\s+\d+\b", re.IGNORECASE)
_HEX_ADDR = re.compile(r"\b0x[0-9a-fA-F]+\b")
_VERSION = re.compile(r"\bv?\d+(?:\.\d+)+(?:[-+][0-9A-Za-z.]+)?\b")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_WORD = re.compile(r"[\W_]+")


def normalise_part(text: str) -> str:
    """Canonical form of one root-cause part: NFKC, build noise removed,
    camelCase/snake_case/kebab-case split into words, case-folded, punctuation
    collapsed. ``readResource``, ``read_resource`` and ``Read-Resource`` agree."""
    text = unicodedata.normalize("NFKC", text)
    for noise in (_LINE_REF, _HEX_ADDR, _VERSION):
        text = noise.sub(" ", text)
    text = _CAMEL.sub(" ", text).casefold()
    return " ".join(_NON_WORD.sub(" ", text).split())


def fingerprint(root_cause: dict) -> dict:
    """Normalise, then hash. The human-readable parts are kept alongside."""
    normalised = {name: normalise_part(root_cause[name]) for name in ROOT_CAUSE_PARTS}
    # Hash the token stream without separators: whether a writer split
    # ``cmsobject`` into words or not must not change the root cause.
    key = "\x1f".join(normalised[name].replace(" ", "") for name in ROOT_CAUSE_PARTS)
    oracle = normalise_part(root_cause["oracle"])
    return {
        "fingerprint": f"{FINGERPRINT_VERSION}:" + hashlib.sha256(key.encode()).hexdigest(),
        "oracle_digest": "sha256:" + hashlib.sha256(oracle.replace(" ", "").encode()).hexdigest(),
        "normalised": {**normalised, "oracle": oracle},
        "parts": {name: root_cause[name] for name in (*ROOT_CAUSE_PARTS, "oracle")},
    }


def lineage_matches(finding_events: list[dict], lineage: str, fp: str,
                    exclude_finding_id: str | None = None) -> list[dict]:
    """Earlier findings of ``lineage`` with fingerprint ``fp``, oldest first."""
    matches = []
    for event in reversed(finding_events):
        payload = event.get("payload") or {}
        root = payload.get("root_cause") or {}
        if (root.get("lineage") == lineage and root.get("fingerprint") == fp
                and payload.get("finding_id") != exclude_finding_id):
            matches.append({"finding_id": payload.get("finding_id"),
                            "arena_id": event.get("lab_id"),
                            "oracle_digest": root.get("oracle_digest"),
                            "reported_at": event.get("ts")})
    return matches


def classify(matches: list[dict], oracle_digest: str) -> dict:
    """``duplicate``: same root cause and same behaviour oracle; ``variant``:
    same root cause, different oracle; ``independent``: no earlier match. The
    related finding is the oldest match of the winning relation."""
    same_oracle = [m for m in matches if m["oracle_digest"] == oracle_digest]
    if same_oracle:
        return {"relation": DUPLICATE, "related_finding_id": same_oracle[0]["finding_id"]}
    if matches:
        return {"relation": VARIANT, "related_finding_id": matches[0]["finding_id"]}
    return {"relation": INDEPENDENT, "related_finding_id": None}


def match_view(match: dict, oracle_digest: str) -> dict:
    return {"finding_id": match["finding_id"], "arena_id": match["arena_id"],
            "reported_at": match["reported_at"],
            "relation": DUPLICATE if match["oracle_digest"] == oracle_digest else VARIANT}


# --- R3: causality gate -----------------------------------------------------------

CAUSALITY_PARTS = ("trace", "fixed_build_control", "toggle")

Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]


class EvidenceRef(BaseModel):
    """A causality claim backed by an immutable record: an HTTP transaction,
    evidence artifact or validation observation of ``arena_id`` (default: the
    finding's own arena). A description without a resolvable digest is not
    evidence."""

    model_config = ConfigDict(extra="forbid")

    summary: Text
    evidence_digest: Digest
    arena_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]{1,64}$")


class TraceClaim(EvidenceRef):
    """Instrumented path proving the claimed source reaches the claimed sink."""


class FixedBuildControl(EvidenceRef):
    """The same trigger failing on the fixed build, or — where no fix exists —
    a documented feature/guard toggle that removes the effect."""

    kind: Literal["fixed_build", "guard_toggle"]
    build: Part = Field(description="fixed commit/version, or the guard's name")


class ToggleClaim(EvidenceRef):
    """The single control that, when flipped, removes the effect."""

    control: Part


class Causality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace: TraceClaim | None = None
    fixed_build_control: FixedBuildControl | None = None
    toggle: ToggleClaim | None = None


def causality_refs(causality: dict | None) -> list[tuple[str, dict]]:
    return [(name, (causality or {})[name]) for name in CAUSALITY_PARTS
            if (causality or {}).get(name)]


def causality_missing(*claims: dict | None) -> list[str]:
    """Parts absent from every supplied claim set (finding + verification)."""
    return [name for name in CAUSALITY_PARTS
            if not any((claim or {}).get(name) for claim in claims)]


def downgrade(validation: dict | None, reason_code: str, **extra) -> dict:
    """An automatic confirmation the integrity layer will not accept."""
    return {**(validation or {}), "confirmed": False, "verdict": "unverified",
            "reason_code": reason_code, **extra}

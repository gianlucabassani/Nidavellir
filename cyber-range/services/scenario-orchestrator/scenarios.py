"""
Scenario registry (ROADMAP audit #4 / Phase 1; import seam P1-7).

Single source of truth for which scenarios exist. Scenarios live in TWO
directories, discovered together:

  * ``config.TEMPLATES_DIR`` — the **built-in** packs baked into the image
    (read-only);
  * ``config.SCENARIOS_DIR`` — operator-**imported** packs, persisted under the
    writable DATA_DIR volume (shared with the worker, survives restarts).

The API validates deploy requests against this registry and serves it via GET
/scenarios so clients (WebUI, Agent Gateway) never hardcode scenario lists.
``save_scenario`` / ``delete_scenario`` back the import endpoints (P1-7).

Scenario ids are the file names (without .yaml) and must match SCENARIO_ID_RE —
this is also the path-traversal guard for everything that turns a scenario id
into a filesystem path. An imported id may never shadow a built-in one.
"""
import logging
import re

import yaml
from pydantic import ValidationError

from config import SCENARIOS_DIR, TEMPLATES_DIR
from scenario_spec import ScenarioSpec

logger = logging.getLogger(__name__)

# Lowercase slug, no dots/slashes: doubles as the path-traversal guard.
SCENARIO_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

# Provenance tags surfaced in the registry (and used by the UI to gate delete).
BUILTIN = "builtin"
IMPORTED = "imported"


def is_valid_scenario_id(scenario_id: str) -> bool:
    return bool(SCENARIO_ID_RE.match(scenario_id))


def _sources() -> list[tuple]:
    """Scenario directories in precedence order: built-in first (an imported
    pack can never shadow a built-in id)."""
    out = [(TEMPLATES_DIR, BUILTIN)]
    if SCENARIOS_DIR != TEMPLATES_DIR:
        out.append((SCENARIOS_DIR, IMPORTED))
    return out


def is_builtin(scenario_id: str) -> bool:
    """True if a read-only built-in template owns this id."""
    return is_valid_scenario_id(scenario_id) and (
        TEMPLATES_DIR / f"{scenario_id}.yaml"
    ).exists()


def _scenario_file(scenario_id: str):
    """Resolve a scenario id to its YAML file across both sources, or None.

    The id check doubles as the path-traversal guard: this is the single place a
    scenario id becomes a filesystem path."""
    if not is_valid_scenario_id(scenario_id):
        logger.error("Rejected invalid scenario id: %r", scenario_id)
        return None
    for base, _ in _sources():
        candidate = base / f"{scenario_id}.yaml"
        if candidate.exists():
            return candidate
    return None


def list_scenarios() -> list[dict]:
    """All deployable scenarios with display metadata, sorted by id.

    Scans the built-in templates and the imported packs together. Display fields
    are read from the validated v3 spec when the file validates; otherwise we
    fall back to the raw dict (and log a warning) so a quirky pack still appears
    in the registry rather than vanishing. Each entry carries a ``source``
    (``builtin`` | ``imported``)."""
    scenarios = []
    seen: set[str] = set()
    for base, source in _sources():
        if not base.exists():
            continue
        for path in sorted(base.glob("*.yaml")):
            scenario_id = path.stem
            if not is_valid_scenario_id(scenario_id):
                logger.warning("Skipping scenario with invalid id: %s", path.name)
                continue
            if scenario_id in seen:
                logger.warning(
                    "Imported scenario %s shadows a built-in id; ignoring import",
                    scenario_id,
                )
                continue
            try:
                data = yaml.safe_load(path.read_text()) or {}
            except yaml.YAMLError as e:
                logger.error("Skipping unparseable scenario %s: %s", path.name, e)
                continue
            seen.add(scenario_id)
            entry = _summarize(scenario_id, data)
            entry["source"] = source
            scenarios.append(entry)
    return sorted(scenarios, key=lambda s: s["id"])


def _summarize(scenario_id: str, data: dict) -> dict:
    """One scenario's registry entry, preferring the validated v3 spec."""
    try:
        spec = ScenarioSpec.from_raw(data, scenario_id=scenario_id)
    except ValidationError as e:
        logger.warning(
            "Scenario %s does not validate against schema v3, using raw "
            "metadata: %s",
            scenario_id,
            e.errors(include_url=False),
        )
        metadata = data.get("metadata") or {}
        return {
            "id": scenario_id,
            "name": data.get("name", scenario_id),
            "title": data.get("title"),
            # Collapse the multi-line YAML description to one line.
            "description": " ".join(str(data.get("description", "")).split()),
            "difficulty": data.get("difficulty", "unknown"),
            "tags": metadata.get("tags", []),
            "provider_class": (data.get("requires") or {}).get("provider_class", "any"),
            "nodes": len(data.get("nodes") or data.get("vms") or []),
            "valid": False,
        }
    return {
        "id": scenario_id,
        "name": spec.name,
        "title": spec.title,
        "description": " ".join(str(spec.description or "").split()),
        "difficulty": spec.difficulty,
        "tags": spec.tags,
        # What kind of infrastructure the scenario needs: vm | container | any.
        "provider_class": spec.requires.provider_class.value,
        "nodes": len(spec.nodes),
        "valid": True,
    }


def scenario_ids() -> set[str]:
    return {s["id"] for s in list_scenarios()}


def load_scenario(scenario_id: str) -> dict | None:
    """Load a scenario's full YAML config (built-in or imported), or None if
    invalid/missing."""
    scenario_file = _scenario_file(scenario_id)
    if scenario_file is None:
        logger.error("Scenario file not found: %s", scenario_id)
        return None

    try:
        return yaml.safe_load(scenario_file.read_text())
    except yaml.YAMLError as e:
        logger.error("Failed to load scenario %s: %s", scenario_id, e)
        return None


def save_scenario(scenario_id: str, raw: dict, *, overwrite: bool = False) -> dict:
    """Validate and persist an operator-imported scenario pack (P1-7).

    ``raw`` is the parsed spec (from JSON or YAML); it is validated as a v3
    ``ScenarioSpec`` (raising ``pydantic.ValidationError`` — the caller maps it
    to 422) and written verbatim to ``SCENARIOS_DIR/<id>.yaml`` so the author's
    metadata/comments-as-data round-trip. Returns the registry summary.

    Raises ``ValueError`` for a bad id or a built-in collision, and
    ``FileExistsError`` if the imported id already exists and ``overwrite`` is
    not set."""
    if not is_valid_scenario_id(scenario_id):
        raise ValueError(
            "invalid scenario id (lowercase letters, digits, '-' and '_'; max 64)"
        )
    if is_builtin(scenario_id):
        raise ValueError(
            f"'{scenario_id}' is a built-in scenario id — choose another id"
        )

    # Validate before touching disk (raises ValidationError → 422 upstream).
    ScenarioSpec.from_raw(raw, scenario_id=scenario_id)

    SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    target = SCENARIOS_DIR / f"{scenario_id}.yaml"
    if target.exists() and not overwrite:
        raise FileExistsError(
            f"scenario '{scenario_id}' already exists — pass overwrite=true to replace"
        )
    target.write_text(yaml.safe_dump(raw, sort_keys=False, default_flow_style=False))
    entry = _summarize(scenario_id, raw)
    entry["source"] = IMPORTED
    return entry


def delete_scenario(scenario_id: str) -> bool:
    """Delete an imported scenario pack. Returns True if removed, False if it
    didn't exist. Raises ``ValueError`` for an invalid id or a built-in (which
    is read-only)."""
    if not is_valid_scenario_id(scenario_id):
        raise ValueError("invalid scenario id")
    if is_builtin(scenario_id):
        raise ValueError(
            f"'{scenario_id}' is a built-in scenario and cannot be deleted"
        )
    target = SCENARIOS_DIR / f"{scenario_id}.yaml"
    if not target.exists():
        return False
    target.unlink()
    return True


def load_scenario_spec(scenario_id: str) -> ScenarioSpec | None:
    """Load and validate a scenario as a v3 ``ScenarioSpec``, or None if the
    scenario is missing/unparseable/invalid.

    Accepts both v3 (``nodes[]``/``segments[]``) and legacy (``vms[]``)
    templates via ``ScenarioSpec.from_raw``. Soft advisories are logged but do
    not fail the load; structural errors return None with a logged reason.
    """
    raw = load_scenario(scenario_id)
    if raw is None:
        return None
    try:
        spec = ScenarioSpec.from_raw(raw, scenario_id=scenario_id)
    except ValidationError as e:
        logger.error(
            "Scenario %s failed v3 validation: %s",
            scenario_id,
            e.errors(include_url=False),
        )
        return None
    for warning in spec.warnings():
        logger.warning("Scenario %s: %s", scenario_id, warning)
    return spec


def scenario_manifest(scenario_id: str) -> list[dict] | None:
    """The KNOWN-vulnerability manifest (ground truth) for a scenario, or None if
    the scenario is unknown. **Operator-only** — never expose this to an agent;
    the benchmark depends on the agent discovering these unaided."""
    spec = load_scenario_spec(scenario_id)
    if spec is None:
        return None
    return [v.model_dump() for v in spec.vulnerabilities]

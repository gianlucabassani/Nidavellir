"""
Scenario registry (ROADMAP audit #4 / Phase 1).

Single source of truth for which scenarios exist: the YAML files in
config.TEMPLATES_DIR. The API validates deploy requests against this registry
and serves it via GET /scenarios so clients (WebUI, future Agent Gateway)
never hardcode scenario lists.

Scenario ids are the template filenames (without .yaml) and must match
SCENARIO_ID_RE — this is also the path-traversal guard for everything that
turns a scenario id into a filesystem path.
"""
import logging
import re

import yaml
from pydantic import ValidationError

from config import TEMPLATES_DIR
from scenario_spec import ScenarioSpec

logger = logging.getLogger(__name__)

# Lowercase slug, no dots/slashes: doubles as the path-traversal guard.
SCENARIO_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def is_valid_scenario_id(scenario_id: str) -> bool:
    return bool(SCENARIO_ID_RE.match(scenario_id))


def list_scenarios() -> list[dict]:
    """All deployable scenarios with display metadata, sorted by id.

    Display fields are read from the validated v3 spec when the template
    validates; otherwise we fall back to the raw dict (and log a warning) so a
    quirky template still appears in the registry rather than vanishing.
    """
    scenarios = []
    for path in sorted(TEMPLATES_DIR.glob("*.yaml")):
        scenario_id = path.stem
        if not is_valid_scenario_id(scenario_id):
            logger.warning("Skipping template with invalid id: %s", path.name)
            continue
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError as e:
            logger.error("Skipping unparseable template %s: %s", path.name, e)
            continue
        scenarios.append(_summarize(scenario_id, data))
    return scenarios


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
    """Load a scenario's full YAML config, or None if invalid/missing.

    The id check doubles as the path-traversal guard: this function is the
    single place a scenario id becomes a filesystem path.
    """
    if not is_valid_scenario_id(scenario_id):
        logger.error("Rejected invalid scenario id: %r", scenario_id)
        return None

    scenario_file = TEMPLATES_DIR / f"{scenario_id}.yaml"
    if not scenario_file.exists():
        logger.error("Scenario file not found: %s", scenario_file)
        return None

    try:
        return yaml.safe_load(scenario_file.read_text())
    except yaml.YAMLError as e:
        logger.error("Failed to load scenario %s: %s", scenario_id, e)
        return None


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

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

from config import TEMPLATES_DIR

logger = logging.getLogger(__name__)

# Lowercase slug, no dots/slashes: doubles as the path-traversal guard.
SCENARIO_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def is_valid_scenario_id(scenario_id: str) -> bool:
    return bool(SCENARIO_ID_RE.match(scenario_id))


def list_scenarios() -> list[dict]:
    """All deployable scenarios with display metadata, sorted by id."""
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
        metadata = data.get("metadata") or {}
        scenarios.append(
            {
                "id": scenario_id,
                "name": data.get("name", scenario_id),
                # Collapse the multi-line YAML description to one line.
                "description": " ".join(str(data.get("description", "")).split()),
                "difficulty": data.get("difficulty", "unknown"),
                "tags": metadata.get("tags", []),
                # What kind of infrastructure the scenario needs: vm |
                # container | any. Providers check this before deploying.
                "provider_class": (data.get("requires") or {}).get("provider_class", "any"),
            }
        )
    return scenarios


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

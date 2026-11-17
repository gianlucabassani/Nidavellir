"""
Lab lifecycle state machine (ADR-0004).

One legal-transition graph, enforced at the persistence layer: nothing else
in the codebase writes `deployments.status` except through
`Database.update_deployment`, which calls `validate_transition`.

    pending ──▶ deploying ──▶ active
       │            │            │
       │            ▼            ▼
       ├──────▶  failed ──▶ destroying ──▶ destroyed   (terminal)
       │                        ▲ │
       └────────────────────────┘ ▼
                          error_destroying ──▶ destroying   (retry)
"""
from enum import StrEnum


class LabStatus(StrEnum):
    PENDING = "pending"
    DEPLOYING = "deploying"
    ACTIVE = "active"
    FAILED = "failed"
    DESTROYING = "destroying"
    DESTROYED = "destroyed"
    ERROR_DESTROYING = "error_destroying"


class IllegalTransition(ValueError):
    """Raised on a status write that the lifecycle graph does not allow."""


# Destroy may be requested from any live state (the UI offers it everywhere,
# incl. labs stuck in pending whose worker task was lost).
_ALLOWED: dict[str, set[str]] = {
    LabStatus.PENDING: {LabStatus.DEPLOYING, LabStatus.FAILED, LabStatus.DESTROYING},
    LabStatus.DEPLOYING: {LabStatus.ACTIVE, LabStatus.FAILED, LabStatus.DESTROYING},
    LabStatus.ACTIVE: {LabStatus.FAILED, LabStatus.DESTROYING},
    LabStatus.FAILED: {LabStatus.DESTROYING},
    LabStatus.DESTROYING: {LabStatus.DESTROYED, LabStatus.ERROR_DESTROYING},
    LabStatus.ERROR_DESTROYING: {LabStatus.DESTROYING},
    LabStatus.DESTROYED: set(),  # terminal: record may only be deleted
}


def validate_transition(current: str | None, new: str) -> None:
    """Raise IllegalTransition unless `current -> new` is in the graph.

    Re-asserting the current state is allowed (idempotent task retries);
    `current=None` covers freshly-created rows being set to pending.
    """
    if new not in set(LabStatus):
        raise IllegalTransition(f"unknown lab status '{new}'")
    if current == new:
        return
    if current is None:
        if new == LabStatus.PENDING:
            return
        raise IllegalTransition(f"a new lab starts at 'pending', not '{new}'")
    if new not in _ALLOWED.get(current, set()):
        raise IllegalTransition(
            f"cannot move lab from '{current}' to '{new}'"
        )

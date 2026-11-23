"""
PF-01 U3 (review 2026-11-16): no Celery ``visibility_timeout`` was configured.

Lifecycle tasks are ``acks_late``. With the Redis broker an unacknowledged task is
redelivered after the visibility timeout (default 3600 s) even while it is still
running, and a prefetched task ages while it waits behind a long one. The
evaluation fallback limit (3660 s) already exceeded the default. The fix sets the
timeout above every bounded task and reserves only running tasks; an evaluation
longer than the timeout is protected by its queued->running claim.
"""
import config
import tasks


def _acks_late_tasks():
    return {name: task for name, task in tasks.app.tasks.items()
            if not name.startswith("celery.") and getattr(task, "acks_late", False)}


def test_visibility_timeout_exceeds_every_bounded_acks_late_task():
    timeout = tasks.app.conf.broker_transport_options["visibility_timeout"]
    assert timeout == config.CELERY_VISIBILITY_TIMEOUT_SECONDS
    limits = {name: task.time_limit for name, task in _acks_late_tasks().items()}
    assert limits, "expected acks_late lifecycle tasks"
    assert all(limit for limit in limits.values()), f"unbounded acks_late task: {limits}"
    assert timeout > max(limits.values()), limits
    # The default this replaces was shorter than the evaluation fallback limit.
    assert limits["run_evaluation"] > 3600


def test_a_worker_reserves_only_what_it_runs():
    assert tasks.app.conf.worker_prefetch_multiplier == 1


def test_result_backend_uses_the_same_timeout():
    assert tasks.app.conf.result_backend_transport_options["visibility_timeout"] == \
        config.CELERY_VISIBILITY_TIMEOUT_SECONDS

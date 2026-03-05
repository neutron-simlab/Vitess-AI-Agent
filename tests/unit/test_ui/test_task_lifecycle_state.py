import pytest

from app.ui_components import apply_task_lifecycle_event, get_task_lifecycle_counts


@pytest.mark.unit
def test_apply_task_lifecycle_event_creates_task_entry() -> None:
    tasks = {}
    event = {
        "task_id": "task-1",
        "run_id": "run-1",
        "sequence": 1,
        "phase": "pending",
        "status": "pending",
        "subagent_type": "researcher",
        "description": "Research latest AI safety developments",
        "timestamp": "2026-01-01T00:00:00+00:00",
    }

    updated = apply_task_lifecycle_event(tasks, event)

    assert "task-1" in updated
    assert updated["task-1"]["status"] == "pending"
    assert updated["task-1"]["subagent_type"] == "researcher"


@pytest.mark.unit
def test_apply_task_lifecycle_event_updates_existing_task() -> None:
    tasks = {
        "task-1": {
            "task_id": "task-1",
            "status": "pending",
            "subagent_type": "researcher",
            "description": "Research",
        }
    }
    running_event = {
        "task_id": "task-1",
        "phase": "running",
        "status": "running",
        "pregel_id": "pregel-1",
        "sequence": 2,
    }
    complete_event = {
        "task_id": "task-1",
        "phase": "complete",
        "status": "complete",
        "result_preview": "Done",
        "sequence": 3,
    }

    updated_running = apply_task_lifecycle_event(tasks, running_event)
    updated_complete = apply_task_lifecycle_event(updated_running, complete_event)

    assert updated_running["task-1"]["status"] == "running"
    assert updated_running["task-1"]["pregel_id"] == "pregel-1"
    assert updated_complete["task-1"]["status"] == "complete"
    assert updated_complete["task-1"]["result_preview"] == "Done"
    assert updated_complete["task-1"]["subagent_type"] == "researcher"


@pytest.mark.unit
def test_get_task_lifecycle_counts() -> None:
    tasks = {
        "a": {"status": "pending"},
        "b": {"status": "running"},
        "c": {"status": "complete"},
        "d": {"status": "complete"},
    }

    counts = get_task_lifecycle_counts(tasks)

    assert counts == {"pending": 1, "running": 1, "complete": 2}

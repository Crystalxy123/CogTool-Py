"""Independent synthetic scheduler/preparation consequences of pinned source.

Times use D=1 px and width=10 px: cursor preparation4 ms, initiation50,
output150 and release200 ms relative to perform. Punch preparation3 ms;
the following identical punch prepares0 ms, outputs60 and releases150 ms.
The generator supplies input steps only; no prediction generates expectations.
"""
from copy import deepcopy

import pytest

from cogtool_py.generator import generate
from cogtool_py.models import (Demonstration, DemonstrationStep, Design, Frame,
    InitialState, ModelError, MOTOR_ENGINE, ParameterSet, Project, Task, Widget)
from cogtool_py.motor_subset import Clock, MotorModule

pytestmark = pytest.mark.independent


def module_and_steps():
    parameters = ParameterSet.parse({name: {"value": .2, "unit": "s", "source": "synthetic unused baseline parameter"}
                                    for name in ("click_s", "key_s", "homing_s")}).with_motor_defaults()
    parent = Widget("parent", "parent", "", "context_menu", -4, -5, 10, 10)
    item = Widget("item", "item", "", "menu_item", 8, -5, 10, 10, "parent")
    task = Task("probe", "probe", Demonstration(InitialState("f", (0, 0), "right", "mouse", None),
                (DemonstrationStep("menu_select", target="item"),)))
    project = Project(2, "probe", "probe", MOTOR_ENGINE, parameters,
                      Design("d", "d", "px", (Frame("f", "f", (parent, item)),), ()), (task,))
    steps = generate(project, task).steps
    return MotorModule(project, task), steps[0], steps[1]


def test_cancel_removes_deadline_without_advancing_time_or_changing_queue_shape():
    clock, calls = Clock(), []
    late = clock.schedule_event(.5, lambda: calls.append("cancelled"))
    early = clock.schedule_event(.001, lambda: calls.append("retained"))
    assert all(len(entry) == 4 for entry in clock.queue)
    assert late.when_ms == 500 and late.order == 0
    assert clock.cancel(late) is True
    assert late.cancelled is True and late.executed is False
    assert clock.now == 0 and len(clock.queue) == 1
    assert clock.queue[0][0] == 1
    clock.drain()
    assert calls == ["retained"] and clock.now == 1
    assert early.executed is True and early.cancelled is False
    assert clock.cancel(late) is False
    assert clock.cancel(early) is False


def test_cancellation_and_legacy_schedule_preserve_priority_then_fifo():
    clock, calls = Clock(), []
    assert clock.schedule(.001, lambda: calls.append("legacy-first")) == 1
    cancelled = clock.schedule_event(.001, lambda: calls.append("removed-middle"))
    clock.schedule_event(.001, lambda: calls.append("new-third"))
    clock.schedule_event(.001, lambda: calls.append("max"), priority=":max")
    clock.schedule(.001, lambda: calls.append("min"), priority=":min")
    assert clock.cancel(cancelled)
    clock.drain()
    assert calls == ["max", "legacy-first", "new-third", "min"]
    assert clock.order == 5


def test_same_time_callback_can_cancel_pending_peer_but_not_itself():
    clock, observed = Clock(), []
    pending = clock.schedule_event(.01, lambda: observed.append("stale callback"))

    def cancel_peer():
        observed.append((clock.cancel(pending), clock.cancel(canceller)))

    canceller = clock.schedule_event(.01, cancel_peer, priority=10)
    clock.drain()
    assert observed == [(True, False)]
    assert clock.now == 10 and pending.cancelled and canceller.executed
    assert clock.queue == []


def test_foreign_clock_handle_cannot_remove_same_order_local_event():
    one, two = Clock(), Clock()
    foreign = one.schedule_event(.01, lambda: None)
    local = two.schedule_event(.02, lambda: None)
    assert foreign.order == local.order == 0
    assert two.cancel(foreign) is False
    assert len(two.queue) == 1 and not local.cancelled
    with pytest.raises(ModelError, match="ScheduledEvent"):
        two.cancel(0)


def test_prepare_only_does_not_execute_or_open_menu_and_click_retains_zero_prep_event():
    module, _, click = module_and_steps()
    callbacks = []
    handle = module.prepare(click, ("control-prepare",),
                            on_complete=lambda m, h: callbacks.append((m.clock.now, h["completed"])))
    assert module.clock.now == 0 and not handle["completed"]
    assert len(module.events) == 1 and module.state["open_menu"] is None
    module.clock.drain()
    assert callbacks == [(3, True)]
    assert module.active_request is None
    assert module.state["motor_preparation"] == "free"
    assert module.state["motor_processor"] == "busy"  # no earlier positive init-stamp
    assert module.state["motor_execution"] == "free"
    assert module.state["last_click"] is None and module.state["open_menu"] is None
    assert module.events[0]["details"]["exec_immediate"] is False
    assert module.events[0]["dependencies"] == ["control-prepare"]
    request = module.request(click, handle["completion_event_ids"])
    assert not request["completed"]
    module.clock.drain()
    assert [(e["event_type"], e["start_s"], e["end_s"]) for e in module.events] == [
        ("motor_preparation", 0, .003), ("motor_preparation", .003, .003),
        ("motor_initiation", .003, .053), ("click_output", .003, .063), ("click_finish", .003, .153)]
    assert request["completed"] and module.state["open_menu"] == "parent"
    changes = [e for e in module.state_changes if e["before"]["open_menu"] != e["after"]["open_menu"]]
    assert [(e["trigger"], e["time_s"]) for e in changes] == [("click_output", .063)]


@pytest.mark.parametrize("prepare_s,done_ms,processor_after", [(.01, 13, "busy"), (.1, 103, "free")])
def test_punch_preparation_overlaps_cursor_execution_with_source_processor_release(prepare_s, done_ms, processor_after):
    module, point, click = module_and_steps()
    original = module.request(point)
    prepared, observed = [], []

    def prepare():
        assert module.state["motor_execution"] == "busy"
        prepared.append(module.prepare(click, on_complete=lambda m, h:
            observed.append((m.clock.now, m.state["motor_processor"], m.state["motor_execution"], h["completed"])) ))

    module.clock.schedule(prepare_s, prepare)
    module.clock.drain()
    assert observed == [(done_ms, processor_after, "busy", True)]
    assert original["completed"] and prepared[0]["completed"]
    assert module.clock.now == 204 and module.state["mouse"] == [1, 0]
    assert module.state["last_prepared"]["style"] == "punch"
    assert not [e for e in module.events if e["event_type"] == "click_output"]
    assert [(e["event_type"], e["end_s"]) for e in module.events[:4]] == [
        ("motor_preparation", .004), ("motor_initiation", .054), ("cursor_move", .154), ("cursor_finish", .204)]
    module.request(click)
    module.clock.drain()
    assert module.events[5]["event_type"] == "motor_preparation"
    assert module.events[5]["duration_s"] == 0
    assert [e["end_s"] for e in module.events if e["event_type"] == "click_output"] == [.264]
    assert module.clock.now == 354


def test_prepare_rejects_unsupported_style_without_mutating_state():
    module, point, _ = module_and_steps()
    before = deepcopy(module.state)
    with pytest.raises(ModelError, match="only click/right_click"):
        module.prepare(point)
    assert module.state == before and module.events == [] and module.clock.queue == []


def test_busy_preparation_rejects_replacement_and_click_execution():
    module, _, click = module_and_steps()
    module.prepare(click)
    before = deepcopy(module.state)
    with pytest.raises(ModelError, match="already being prepared"):
        module.prepare(click)
    with pytest.raises(ModelError, match="already being prepared"):
        module.request(click)
    assert module.state == before and len(module.events) == 1 and len(module.clock.queue) == 1


def test_request_still_rejects_general_execution_queue_instead_of_blocking_or_faking_output():
    module, point, click = module_and_steps()
    module.request(point)
    module.clock.step()  # cursor preparation complete, execution remains busy
    before = deepcopy(module.state)
    with pytest.raises(ModelError, match="execution queues are unsupported"):
        module.request(click)
    assert module.state == before and len(module.events) == 4

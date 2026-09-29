"""Independent new two-menu scene; source-derived scope, never NP-B2 times.

The first execution of these tests is deliberately retained against the frozen
core, which rejects the second menu. No skip, xfail, or validation bypass hides
that first failure. The proposed vNext must pass through public validation.
"""
from dataclasses import replace

import pytest

from cogtool_py.control_models import ControlConfig
from cogtool_py.engine import predict
from cogtool_py.models import (CONTROL_ENGINE, MOTOR_ENGINE, Demonstration,
    DemonstrationStep, Design, Frame, InitialState, ModelError, ParameterSet,
    Project, Task, Transition, Widget)

pytestmark = pytest.mark.independent


def scene(*, engine=CONTROL_ENGINE, scope="integrated_task", same_parent=False):
    parameters = ParameterSet.parse({name: {"value": value, "unit": "s", "source": "independent two-menu fixture"}
                                    for name, value in {"click_s": .2, "key_s": .1, "homing_s": .4}.items()})
    control = None
    if engine == CONTROL_ENGINE:
        parameters = parameters.with_vision_defaults() if scope == "integrated_task" else parameters.with_control_defaults()
        control = ControlConfig("source_2014_defaults", "Independent four-center synthetic geometry under normal source initialization",
                                auto_stuffing=True, execution_scope=scope)
    elif engine == MOTOR_ENGINE:
        parameters = parameters.with_motor_defaults()
    widgets = (
        Widget("menu_a", "menu A", "A", "context_menu", -4, -5, 10, 10),
        Widget("item_a", "item A", "choice A", "menu_item", 6, -5, 10, 10, parent="menu_a"),
        Widget("menu_b", "menu B", "B", "context_menu", 16, -5, 10, 10),
        Widget("item_b", "item B", "choice B", "menu_item", 26, -5, 10, 10,
               parent="menu_a" if same_parent else "menu_b"),
    )
    transitions = (Transition("select_a", "frame", "item_a", "frame", 0),
                   Transition("select_b", "frame", "item_b", "frame", 0))
    task = Task("two_choices", "Choose from two distinct contexts", Demonstration(
        InitialState("frame", (0, 0), "right", "mouse", None),
        (DemonstrationStep("menu_select", "item_a", transition="select_a"),
         DemonstrationStep("menu_select", "item_b", transition="select_b"))))
    return Project(2, "independent-two-contexts", "Independent two-context scene", engine,
                   parameters, Design("design", "Independent", "px", (Frame("frame", "Frame", widgets),), transitions),
                   (task,), control)


def test_distinct_contexts_expand_once_each_with_one_start_and_stop():
    result = predict(scene()).to_dict()
    expected = [("point", "menu_a"), ("right_click", "menu_a"), ("think", None),
                ("point", "item_a"), ("click", "item_a"),
                ("point", "menu_b"), ("right_click", "menu_b"), ("think", None),
                ("point", "item_b"), ("click", "item_b")]
    assert [(s["op"], s["target"]) for s in result["steps"] if s["op"] != "transition"] == expected
    assert [s["demo_index"] for s in result["steps"] if s["op"] != "transition"] == [0]*5 + [1]*5
    assert sum(s["op"] == "transition" for s in result["steps"]) == 2
    assert result["completion_status"] == "complete"
    fired = [e["rule"] for e in result["events"] if e["event_type"] == "production_fired"]
    assert fired.count("set-start-frame") == fired.count("stop") == 1
    assert fired.count("think") == 2
    compiled = [e for e in result["events"] if e["event_type"] == "compiled_productions"]
    assert len(compiled) == 1 and compiled[0]["details"]["script_generation_count"] == 1
    assert [e["target"] for e in result["events"] if e["event_type"] == "menu_open"] == ["menu_a", "menu_b"]
    assert [e["target"] for e in result["events"] if e["event_type"] == "menu_selection"] == ["item_a", "item_b"]
    # Each generated command has exactly one output, rather than replaying the
    # first query or assuming two independent task totals can be added.
    outputs = [e for e in result["motor_events"] if e["event_type"] in {"cursor_move", "cursor_noop", "click_output"}]
    assert [(e["op"], e["target"]) for e in outputs] == [row for row in expected if row[0] != "think"]
    assert len({e["step_index"] for e in outputs}) == len(outputs)


def test_second_query_carries_mouse_eye_and_one_shared_module_queue(monkeypatch):
    from cogtool_py.motor_subset import MotorModule
    from cogtool_py.vision import VisionModule
    clocks = {"motor": [], "vision": []}
    motor_init, vision_init = MotorModule.__init__, VisionModule.__init__

    def observe_motor(self, project, task, clock=None):
        motor_init(self, project, task, clock)
        clocks["motor"].append(self.clock)

    def observe_vision(self, parameters, clock=None, **kwargs):
        vision_init(self, parameters, clock, **kwargs)
        clocks["vision"].append(self.clock)

    monkeypatch.setattr(MotorModule, "__init__", observe_motor)
    monkeypatch.setattr(VisionModule, "__init__", observe_vision)
    result = predict(scene()).to_dict()
    assert len(clocks["motor"]) == len(clocks["vision"]) == 1
    assert clocks["motor"][0] is clocks["vision"][0]
    cursor_outputs = [e for e in result["motor_events"] if e["event_type"] == "cursor_move"]
    assert [e["target"] for e in cursor_outputs] == ["menu_a", "item_a", "menu_b", "item_b"]
    assert cursor_outputs[2]["state_before"]["mouse"] == cursor_outputs[1]["state_after"]["mouse"] == [11, 0]
    assert cursor_outputs[2]["start_s"] >= cursor_outputs[1]["end_s"]
    vision_requests = [e for e in result["vision_events"] if e["event_type"] == "visual_attention_request"]
    assert [e["target"] for e in vision_requests] == ["menu_a", "item_a", "menu_b", "item_b"]
    assert vision_requests[0]["state_before"]["eye_location"] == [0, 0]
    assert vision_requests[2]["state_before"]["eye_location"] == [11, 0]
    assert len({e["request_id"] for e in vision_requests}) == 4
    # Normal wrapper initialization is once, not once per menu selection.
    startup = [e for e in result["vision_events"] if e["event_type"] == "visual_clear_request" and e["start_s"] == 0]
    assert len(startup) == 1
    assert result["simulation_end_time_s"] == clocks["motor"][0].now / 1000
    assert result["termination_reason"] == "event_queue_exhausted_after_stop"


def test_same_parent_repetition_remains_unsupported():
    with pytest.raises(ModelError, match="repeated|same|parent"):
        predict(scene(same_parent=True))


@pytest.mark.parametrize("engine,scope", [("klm_baseline", "integrated_task"),
                                        (MOTOR_ENGINE, "integrated_task"),
                                        (CONTROL_ENGINE, "prefix_only")])
def test_other_engines_and_preserved_prefix_keep_multiple_menu_boundary(engine, scope):
    with pytest.raises(ModelError, match="repeated|multiple|menu"):
        predict(scene(engine=engine, scope=scope))


def test_nonconsecutive_menu_sequence_is_outside_proposed_narrow_scope():
    project = scene()
    task = project.tasks[0]
    steps = (task.demonstration.steps[0], DemonstrationStep("think", duration_s=.1), task.demonstration.steps[1])
    project = replace(project, tasks=(replace(task, demonstration=replace(task.demonstration, steps=steps)),))
    with pytest.raises(ModelError, match="repeated|continuous|consecutive|menu"):
        predict(project)


def test_nonzero_menu_transition_delay_remains_outside_proposed_narrow_scope():
    project = scene()
    transitions = (replace(project.design.transitions[0], delay_s=.1), project.design.transitions[1])
    project = replace(project, design=replace(project.design, transitions=transitions))
    # Frozen core rejects repeated menu; vNext must reject it on the narrower
    # transition precondition rather than silently executing a serial wait.
    try:
        result = predict(project).to_dict()
    except ModelError as exc:
        assert any(token in str(exc) for token in ("repeated", "delay", "menu", "transition"))
    else:
        assert result["completion_status"] != "complete"
        assert result["predicted_time_s"] is None

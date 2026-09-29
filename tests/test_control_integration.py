"""Independent integrated-control consequences of fixed 2014 source rules.

Scenes below are artificial and use real VisionModule events; no archived NP-B1
timings or mocked module completions supply expectations. Formula assertions
use the published source constants, not values returned by another predictor.
"""
from dataclasses import replace

import pytest

from cogtool_py.control_models import ControlConfig, SyntheticUpdate
from cogtool_py.engine import predict
from cogtool_py.io import input_hash, load_project, save_project
from cogtool_py.models import (CONTROL_ENGINE, VISION_DEFAULTS, Demonstration, DemonstrationStep,
    Design, Frame, InitialState, ModelError, ParameterSet, Project, Task,
    Transition, Widget)

pytestmark = pytest.mark.independent
PROVENANCE = "Independent static synthetic scene using fixed 2014 normal source rules"


def integration_scene(kind="menu", *, self_loop=False, max_time_s=10, max_events=1000):
    if kind == "menu":
        widgets = (Widget("parent", "parent", "menu", "context_menu", -4, -5, 10, 10),
                   Widget("item", "item", "item", "menu_item", 8, -5, 10, 10, "parent"))
        steps = (DemonstrationStep("menu_select", target="item", transition="stay" if self_loop else None),)
    else:
        widgets = (Widget("target", "target", "target", "button", -4, -5, 10, 10),)
        steps = (DemonstrationStep("point", target="target"),)
    parameters = ParameterSet.parse({name: {"value": value, "unit": "s", "source": PROVENANCE}
        for name, value in {"click_s": .2, "key_s": .1, "homing_s": .4}.items()}).with_vision_defaults()
    transitions = (Transition("stay", "f", "item", "f", 0),) if self_loop else ()
    config = replace(ControlConfig.source_2014(provenance=PROVENANCE), execution_scope="integrated_task",
                     max_time_s=max_time_s, max_events=max_events)
    return Project(2, "integrated-" + kind, "独立视觉控制场景", CONTROL_ENGINE, parameters,
                   Design("d", "Design", "px", (Frame("f", "Frame", widgets),), transitions),
                   (Task("t", "Task", Demonstration(InitialState("f", (0, 0), "right", "mouse", None), steps)),), config)


def rules(result, event_type="production_fired", rule=None):
    found = [e for e in result["events"] if e["event_type"] == event_type]
    return found if rule is None else [e for e in found if e["rule"].lower() == rule.lower()]


def completed_motor(result, kind):
    return [e for e in result["motor_events"] if e["event_type"] == kind and e["state_after"] is not None]


def completed_vision(result, kind=None):
    return [e for e in result["vision_events"] if e["status"] == "executed" and
            (kind is None or e["event_type"] == kind)]


@pytest.fixture(scope="module")
def menu_result():
    return predict(integration_scene()).to_dict()


def test_menu_production_ids_and_state_advances_follow_writer_templates(menu_result):
    assert [(r["production_id"], r["state_from"], r["state_to"])
            for r in menu_result["compiled_productions"]] == [
        ("find-3", 2, 3), ("look-at-4", 2, 4), ("look-at-5", 3, 4),
        ("find-location-6", 4, 4), ("move-mouse-7", 4, 5),
        ("prepare-click-8", 5, 6), ("click-mouse-9", 6, 7),
        ("think-10", 7, 8), ("find-11", 8, 9), ("look-at-12", 8, 10),
        ("look-at-13", 9, 10), ("find-location-14", 10, 10),
        ("move-mouse-15", 10, 11), ("prepare-click-16", 11, 12),
        ("click-mouse-17", 12, 13), ("stop-18", 13, "stop"),
    ]


def test_real_vision_point_runs_to_queue_end_after_early_stop():
    result = predict(integration_scene("point")).to_dict()
    assert result["completion_status"] == "complete"
    assert result["engine"]["version"] == "0.6.0"
    assert result["termination_reason"] == "event_queue_exhausted_after_stop"
    assert completed_vision(result, "visual_attention_request")
    assert completed_vision(result, "visual_encoding_complete")
    assert completed_vision(result, "visual_buffer_write")
    assert not [e for e in result["events"] if e.get("origin") == "synthetic_controller_only"]
    assert result["first_mouse_request_time_s"] == .15
    # Empty startup display clears vision for50ms, allowing FIND but not LOOK.
    # Unique leftmost target (1,0), width10. FIND/LOOK/MOVE each DAT50; cursor
    # prepares four features at1ms; Fitts floor100 + initiation50 + burst50.
    assert result["last_device_output_time_s"] == pytest.approx(.304, abs=1e-12)
    assert result["last_manual_release_time_s"] == pytest.approx(.354, abs=1e-12)
    assert result["model_stop_time_s"] == .15
    assert result["task_stop_time_s"] == result["model_stop_time_s"]
    assert result["model_stop_time_s"] < result["last_device_output_time_s"] < result["last_manual_release_time_s"]
    assert result["reported_task_time_s"] == result["simulation_end_time_s"] == .354
    assert result["original_rerun_s"] is None


def test_empty_startup_display_calls_real_clear_before_start_and_conflict():
    # Wrapper1152 calls proc-display before run1155. Device188-196 and
    # vision624-646 synchronously reach CogTool891-896 with curframe=NIL.
    # PM284-292 queues literal50ms preparation release without a device lock.
    result = predict(integration_scene("point")).to_dict()
    startup = next(e for e in result["events"] if e["event_type"] == "startup_empty_proc_display")
    assert startup["start_s"] == 0
    assert startup["state_after"]["current_frame"] is None
    assert startup["state_after"]["scene_locations"] == []
    clear = completed_vision(result, "visual_clear_request")[0]
    released = completed_vision(result, "visual_clear_complete")[0]
    assert clear["start_s"] == 0 and clear["request_id"] is None
    assert clear["state_after"]["visual_preparation"] == "busy"
    assert released["end_s"] == .05
    selected = rules(result, "production_selected")
    assert [(e["rule"], e["start_s"]) for e in selected[:4]] == [
        ("set-start-frame", 0), ("find", 0), ("look-at", .05), ("move-mouse", .1)]
    first_find = selected[1]
    assert first_find["state_after"]["visual_location"]["target"] == "target"
    assert first_find["state_after"]["visual_preparation"] == "busy"
    assert first_find["state_after"]["device_locked"] is False
    assert [(e["rule"], e["start_s"]) for e in rules(result)[:4]] == [
        ("set-start-frame", 0), ("find", .05), ("look-at", .1), ("move-mouse", .15)]
    clear_update = next(e for e in result["events"] if e["event_type"] == "visual_state_update"
        and e["details"]["vision_change"]["trigger"] == "visual_clear_complete")
    find_fired = rules(result, rule="find")[0]
    # Both priority0 at50ms; startup clear entered the queue before FINDfire.
    assert clear_update["start_s"] == find_fired["start_s"] == .05
    assert clear_update["index"] < find_fired["index"]


def test_explicit_synthetic_initial_phase_does_not_repeat_wrapper_startup():
    source = integration_scene("point")
    synthetic = replace(source, control=replace(source.control,
        profile="synthetic_controller_only", auto_stuffing=False,
        provenance="Prescribed post-initialization controller scene; not a normal source run",
        visual_location="target"))
    result = predict(synthetic).to_dict()
    assert result["completion_status"] == "complete"
    assert not [e for e in result["events"] if e["event_type"] == "startup_empty_proc_display"]
    assert [(e["rule"], e["start_s"]) for e in rules(result)[:2]] == [("look-at", .05), ("move-mouse", .1)]


def test_first_right_click_opens_menu_only_at_device_output(menu_result):
    result = menu_result
    clicks = completed_motor(result, "click_output")
    assert [(e["op"], e["target"]) for e in clicks] == [("right_click", "parent"), ("click", "item")]
    openings = [e for e in result["motor_state_changes"]
                if e["before"]["open_menu"] != "parent" and e["after"]["open_menu"] == "parent"]
    assert len(openings) == 1
    assert openings[0]["trigger"] == "click_output"
    assert openings[0]["time_s"] == clicks[0]["end_s"]
    assert result["first_right_click_output_time_s"] == clicks[0]["end_s"]
    assert result["menu_selection_time_s"] == clicks[1]["end_s"]
    assert clicks[0]["state_before"]["open_menu"] is None


def test_prepare_click_really_overlaps_point_then_retains_zero_prep_event(menu_result):
    result = menu_result
    prepared = rules(result, rule="prepare-click")
    cursors = completed_motor(result, "cursor_finish")
    clicks = rules(result, rule="click-mouse")
    assert len(prepared) == len(cursors) == len(clicks) == 2
    for prepare, cursor, click in zip(prepared, cursors, clicks):
        assert prepare["state_after"]["manual"]["motor_execution"] == "busy"
        assert prepare["start_s"] < cursor["end_s"] <= click["start_s"]
    punch_preps = [e for e in completed_motor(result, "motor_preparation") if e["op"] in {"click", "right_click"}]
    assert len(punch_preps) == 4
    assert [e["duration_s"] for e in punch_preps] == pytest.approx([.003, 0, .003, 0], abs=1e-12)
    assert [e["details"].get("exec_immediate") for e in punch_preps[::2]] == [False, False]


def test_think_uses_one_source_duration_and_waits_for_manual_free(menu_result):
    selected = rules(menu_result, "production_selected", "think")
    fired = rules(menu_result, rule="think")
    assert len(selected) == len(fired) == 1
    assert selected[0]["state_after"]["manual_state"] == "free"
    first_release = completed_motor(menu_result, "click_finish")[0]["end_s"]
    assert selected[0]["start_s"] >= first_release
    assert fired[0]["start_s"] - selected[0]["start_s"] == pytest.approx(1.2, abs=1e-12)
    assert fired[0]["details"]["lhs_rechecked"] is False
    assert len(completed_vision(menu_result, "visual_attention_request")) == 2
    assert len(completed_vision(menu_result, "visual_encoding_complete")) == 2


def test_zero_delay_self_loop_has_no_extra_rule_or_scene_reset(menu_result):
    loop = predict(integration_scene(self_loop=True)).to_dict()
    assert loop["completion_status"] == menu_result["completion_status"] == "complete"
    assert [e["rule"] for e in rules(loop)] == [e["rule"] for e in rules(menu_result)]
    assert [e["start_s"] for e in rules(loop)] == [e["start_s"] for e in rules(menu_result)]
    assert len([e for e in loop["events"] if e["event_type"] == "proc_display"]) == 1
    assert not [e for e in rules(loop) if e["rule"] in {"transition", "wait"}]
    assert loop["reported_task_time_s"] == menu_result["reported_task_time_s"]


def test_complete_menu_has_distinct_stop_output_release_and_exhaustion(menu_result):
    result = menu_result
    assert result["completion_status"] == "complete"
    assert result["termination_reason"] == "event_queue_exhausted_after_stop"
    assert len(rules(result, rule="stop")) == 1
    stop = rules(result, rule="stop")[0]
    assert stop["state_after"]["manual_state"] == "busy"
    assert result["model_stop_time_s"] == stop["start_s"]
    assert result["model_stop_time_s"] < result["last_device_output_time_s"] < result["last_manual_release_time_s"]
    executed_times = [e["end_s"] for e in result["motor_events"] if e["state_after"] is not None]
    executed_times += [e["end_s"] for e in completed_vision(result)]
    assert result["simulation_end_time_s"] == max(result["model_stop_time_s"], *executed_times)
    assert result["reported_task_time_s"] == result["simulation_end_time_s"]
    assert not [e for e in result["vision_events"] if e["status"] == "pending"]


@pytest.mark.parametrize("limit", [{"max_time_s": .2}, {"max_events": 1}])
def test_limits_keep_complete_task_prediction_null(limit):
    result = predict(integration_scene(**limit)).to_dict()
    assert result["completion_status"] in {"time_limit", "event_limit"}
    assert result["reported_task_time_s"] is None
    assert result["predicted_time_s"] is None
    assert result["termination_reason"] != "event_queue_exhausted_after_stop"


def test_integrated_scope_refuses_synthetic_completion_events():
    project = integration_scene()
    prescribed = replace(project.control, profile="synthetic_controller_only", auto_stuffing=False,
                         updates=(SyntheticUpdate(.01, "visual_free", "parent"),))
    with pytest.raises(ModelError, match="actual module events"):
        predict(replace(project, control=prescribed))


@pytest.mark.parametrize("rule_name", ["prepare-click", "click-mouse"])
def test_click_name_query_inherits_wrapper_visibility_gate(rule_name):
    # Evaluate an explicit LHS state; no module completion or event is mocked.
    # Java omits status-visible, but frame-module-query 758-760 requires
    # visible-p OR system-wait-blocks-only-vision (the latter defaults nil).
    from cogtool_py.generator import generate
    from cogtool_py.task_control import IntegratedController

    project = integration_scene()
    task = project.tasks[0]
    controller = IntegratedController(project, task, generate(project, task))
    candidate = next(rule for rule in controller.rules if rule["name"] == rule_name)
    controller.state.update(current_frame="f", frame_visible=False, goal_state=candidate["state_from"])
    assert not any(rule["name"] == rule_name for rule in controller.candidates())
    controller.state["frame_visible"] = True
    assert any(rule["name"] == rule_name for rule in controller.candidates())
    controller.state["current_frame"] = "another-frame"
    assert not any(rule["name"] == rule_name for rule in controller.candidates())


def test_scope_and_effective_visual_parameters_survive_save_reload(tmp_path):
    project = integration_scene()
    path = tmp_path / "integrated.json"
    save_project(project, path)
    restored = load_project(path)
    assert restored == project and input_hash(restored) == input_hash(project)
    assert restored.control.execution_scope == "integrated_task"
    assert restored.parameters.value("visual_encoding_factor_s") == .006
    # Omitted new scope retains the previously released prefix input identity.
    prefix = replace(project, control=replace(project.control, execution_scope="prefix_only"),
                     parameters=ParameterSet({key: value for key, value in project.parameters.entries.items()
                                              if key not in VISION_DEFAULTS}))
    assert "execution_scope" not in prefix.control.to_dict()
    assert input_hash(prefix) != input_hash(project)

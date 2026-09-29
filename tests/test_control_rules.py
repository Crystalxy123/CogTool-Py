"""Independent consequences of the pinned 2014 production rules.

These constants come from docs/control_prefix_procedural_zh.md, not historical
trace times or the controller under test. All artificial updates are explicitly
controller-only inputs. Set COGTOOL_CONTROL_MATRIX_OUT to a new directory to
retain the two small scenes and every A--J input/result/assertion outcome.
"""
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path

import pytest

from cogtool_py.control_models import ControlConfig, SyntheticUpdate
from cogtool_py.engine import predict
from cogtool_py.models import (CONTROL_ENGINE, Demonstration, DemonstrationStep,
                               Design, Frame, InitialState, ParameterSet, Project,
                               Task, Widget)


pytestmark = pytest.mark.independent
PROVENANCE = "Independent 2014 source-rule controller test; prescribed state is not EMMA evidence"


def config(**values):
    return ControlConfig("synthetic_controller_only", PROVENANCE, **values)


def small_scene(scene="two_buttons", control=None):
    """Two standalone geometries; target movement has the .100 s Fitts floor.

    In scene 1 target is leftmost (center 1,0), and in scene 2 the distractor is
    leftmost (center -20,0), with target center 11,0. Normal initialization must
    therefore choose different first target rules without rewriting any trace.
    """
    if scene == "two_buttons":
        widgets = (Widget("target", "target", "目标", "button", -4, -5, 10, 10),
                   Widget("other", "other", "干扰项", "button", 16, -5, 10, 10))
    elif scene == "left_distractor":
        widgets = (Widget("target", "target", "目标", "button", 1, -10, 20, 20),
                   Widget("other", "other", "左侧干扰项", "button", -25, -5, 10, 10))
    else:
        raise AssertionError(f"unknown independent scene {scene}")
    p = ParameterSet.parse({name: {"value": value, "unit": "s", "source": PROVENANCE}
                            for name, value in {"click_s": .2, "key_s": .1, "homing_s": .4}.items()})
    return Project(2, "control-" + scene, "独立控制规则场景", CONTROL_ENGINE,
                   p.with_control_defaults(), Design("d", "Design", "px", (Frame("f", "Frame", widgets),), ()),
                   (Task("t", "Point target", Demonstration(InitialState("f", (0, 0), "right", "mouse", None),
                         (DemonstrationStep("point", target="target"),))),), control or config())


@dataclass(frozen=True)
class RuleCase:
    id: str
    why: str
    control: ControlConfig
    rules: tuple[str, ...]
    fired_s: tuple[float, ...]
    mouse_s: float | None
    completion: str = "partial"
    scene: str = "two_buttons"


CASES = (
    RuleCase("A_empty", "Empty location requires FIND then after-find LOOK", config(),
             ("find", "look-at", "move-mouse"), (.05, .1, .15), .15),
    RuleCase("B_matching", "U0 direct LOOK beats matching U-1 FIND", config(visual_location="target"),
             ("look-at", "move-mouse"), (.05, .1), .1),
    RuleCase("C_other", "Another location does not satisfy target value", config(visual_location="other"),
             ("find", "look-at", "move-mouse"), (.05, .1, .15), .15),
    RuleCase("D_stuffed", "Requested provenance is not an implicit LHS condition",
             config(visual_location="target", location_requested=False), ("look-at", "move-mouse"), (.05, .1), .1),
    RuleCase("D_requested", "Same content requested has the same rule path",
             config(visual_location="target", location_requested=True), ("look-at", "move-mouse"), (.05, .1), .1),
    RuleCase("E_busy", "Busy visual blocks LOOK but FIND remains enabled at initial state",
             config(visual_location="target", visual_processor="busy"), ("find",), (.05,), None, "waiting"),
    RuleCase("E_busy_then_free", "Only the explicit synthetic completion unblocks after-find LOOK",
             config(visual_location="target", visual_processor="busy", updates=(SyntheticUpdate(.2, "visual_free", "target"),)),
             ("find", "look-at", "move-mouse"), (.05, .25, .3), .3),
    RuleCase("F_hidden_frame", "Invisible frame prevents all target productions", config(frame_visible=False),
             (), (), None, "deadlock"),
    RuleCase("F_missing_target", "FIND failure does not invent a location or finish task", config(visible_targets=("other",)),
             ("find",), (.05,), None, "deadlock"),
    RuleCase("F_stale_attention", "Selected LOOK still fires, then stale-target EMMA is unsupported",
             config(visual_location="target", updates=(SyntheticUpdate(.025, "scene_remove", "target"),)),
             ("look-at",), (.05,), None, "unsupported"),
    RuleCase("G_utility", "Both initial FIND and LOOK match; higher utility wins", config(visual_location="target"),
             ("look-at", "move-mouse"), (.05, .1), .1),
    RuleCase("G_equal_utility", "Later MOVE beats equal-U suppression after pending fallback finishes",
             config(visual_location="target", updates=(SyntheticUpdate(0, "manual_busy"),
                    SyntheticUpdate(.06, "visual_free", "target"), SyntheticUpdate(.06, "manual_free"))),
             ("look-at", "find-location", "move-mouse"), (.05, .1, .15), .15),
    RuleCase("H_same_time_write", "priority10 buffer write precedes conflict:min", config(visual_location="other",
             updates=(SyntheticUpdate(0, "location_set", "target", True),)),
             ("look-at", "move-mouse"), (.05, .1), .1),
    RuleCase("H_equal_priority_fifo", "Two priority10 writes retain input insertion order", config(
             updates=(SyntheticUpdate(0, "location_set", "target"), SyntheticUpdate(0, "location_set", "other"))),
             ("find", "look-at", "move-mouse"), (.05, .1, .15), .15),
    RuleCase("I_look_binding", "Buffer replacement does not cancel LOOK or replace its captured identity",
             config(visual_location="target", updates=(SyntheticUpdate(.025, "location_set", "other", True),)),
             ("look-at", "find-location", "move-mouse"), (.05, .1, .15), .15),
    RuleCase("I_move_binding", "Pending MOVE retains old bound target and leaves current buffer alone",
             config(visual_location="target", updates=(SyntheticUpdate(.075, "location_set", "other", True),)),
             ("look-at", "move-mouse"), (.05, .1), .1),
    RuleCase("I_frame_changes", "Pending LOOK is not cancelled by a newly false frame query",
             config(visual_location="target", updates=(SyntheticUpdate(.025, "frame_hide"),)),
             ("look-at",), (.05,), None, "waiting"),
    RuleCase("J_no_duplicate", "Repeated updates during pending MOVE do not start more dispatches",
             config(visual_location="target", updates=(SyntheticUpdate(.07, "location_set", "target"),
                    SyntheticUpdate(.08, "location_set", "target", True), SyntheticUpdate(.09, "visual_busy"))),
             ("look-at", "move-mouse"), (.05, .1), .1),
    RuleCase("S1_source_target_leftmost", "Normal scene1 stuffs target after zero-AT START",
             ControlConfig.source_2014(provenance="Independent small static scene1; source default initialization"),
             ("set-start-frame", "look-at", "move-mouse"), (0, .05, .1), .1),
    RuleCase("S2_source_distractor_leftmost", "Normal scene2 stuffs distractor so FIND is needed",
             ControlConfig.source_2014(provenance="Independent small static scene2; source default initialization"),
             ("set-start-frame", "find", "look-at", "move-mouse"), (0, .05, .1, .15), .15, scene="left_distractor"),
)


def event_list(result, kind):
    return [event for event in result["events"] if event["event_type"] == kind]


def assert_case(case, result):
    selected = event_list(result, "production_selected")
    fired = event_list(result, "production_fired")
    assert tuple(e["rule"] for e in selected) == case.rules
    assert tuple(e["rule"] for e in fired) == case.rules
    assert [e["start_s"] for e in fired] == pytest.approx(case.fired_s, abs=1e-12)
    # Every rule in this matrix except START has its own .050 action time.
    for before, after in zip(selected, fired):
        delay = 0 if before["rule"] == "set-start-frame" else .05
        assert after["start_s"] - before["start_s"] == pytest.approx(delay, abs=1e-12)
        assert after["details"]["lhs_rechecked"] is False
    assert result["first_mouse_request_time_s"] == case.mouse_s
    assert result["completion_status"] == case.completion
    assert result["first_selected_rule"] == (case.rules[0] if case.rules else None)
    target_rules = [x for x in case.rules if x != "set-start-frame"]
    assert result["first_target_rule"] == (target_rules[0] if target_rules else None)
    assert len(event_list(result, "mouse_request")) == (1 if case.mouse_s is not None else 0)
    assert result["reported_task_time_s"] is None
    assert result["predicted_time_s"] is None
    assert result["task_stop_time_s"] is None
    assert result["remaining_unsupported_mechanisms"]
    assert event_list(result, "prefix_boundary")[-1]["details"]["full_task_completed"] is False
    assert result["initial_state_profile"] == case.control.profile
    assert result["initial_state_provenance"] == case.control.provenance
    initial = event_list(result, "initial_state")[0]["state_after"]
    assert (initial["visual_location"]["target"] if initial["visual_location"] else None) == case.control.visual_location
    assert initial["location_requested"] is case.control.location_requested
    assert initial["visual_content"] == case.control.visual_content
    assert initial["visual_processor"] == case.control.visual_processor
    if case.mouse_s is not None:
        # Both scenes have D/W small enough for the .100 s minimum.
        # Fresh cursor: prep4ms; output=I50+F100; release=I50+F100+B50.
        assert result["last_device_output_time_s"] == pytest.approx(case.mouse_s + .154, abs=1e-12)
        assert result["last_manual_release_time_s"] == pytest.approx(case.mouse_s + .204, abs=1e-12)
        assert result["final_state"]["goal_state"] == "after_first_mouse_request"
        assert result["final_state"]["manual_state"] == "free"


@pytest.fixture(scope="module")
def matrix_archive():
    configured = os.environ.get("COGTOOL_CONTROL_MATRIX_OUT")
    out = Path(configured) if configured else None
    rows = []
    if out is not None:
        out.mkdir(parents=True, exist_ok=False)
        (out / "scenes").mkdir()
        for scene in ("two_buttons", "left_distractor"):
            (out / "scenes" / (scene + ".json")).write_text(
                json.dumps(small_scene(scene).to_dict(), ensure_ascii=False, indent=2) + "\n")
    yield out, rows
    if out is not None:
        (out / "matrix.json").write_text(json.dumps({
            "evidence_type": "independent synthetic rule assertions, not upstream accuracy validation",
            "source_commit": "a91d91e8dcf95d762b6e08020029a36ea079bbba",
            "specification": "docs/control_prefix_procedural_zh.md",
            "cases": rows, "case_count": len(rows), "passed": sum(x["outcome"] == "passed" for x in rows),
        }, ensure_ascii=False, indent=2) + "\n")


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_independent_control_matrix(case, matrix_archive):
    out, rows = matrix_archive
    project = small_scene(case.scene, case.control)
    row = {"id": case.id, "why": case.why,
           "expected": {"rules": case.rules, "fired_s": case.fired_s,
                        "mouse_request_s": case.mouse_s, "completion": case.completion}}
    try:
        result = predict(project).to_dict()
        if out is not None:
            folder = out / case.id
            folder.mkdir()
            (folder / "input.json").write_text(json.dumps(project.to_dict(), ensure_ascii=False, indent=2) + "\n")
            (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        row["actual"] = {"rules": [e["rule"] for e in event_list(result, "production_fired")],
                         "fired_s": [e["start_s"] for e in event_list(result, "production_fired")],
                         "mouse_request_s": result["first_mouse_request_time_s"],
                         "completion": result["completion_status"]}
        assert_case(case, result)
        row["outcome"] = "passed"
    except Exception as error:
        row.update(outcome="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        rows.append(row)


def test_requested_changes_provenance_but_not_guards_or_timing():
    results = [predict(small_scene(control=config(visual_location="target", location_requested=v))).to_dict()
               for v in (False, True)]
    assert [event_list(r, "initial_state")[0]["state_after"]["location_requested"] for r in results] == [False, True]
    for kind in ("conflict_resolution", "production_selected", "production_fired", "mouse_request"):
        paths = [[(e["rule"], e["start_s"], e["details"].get("candidates")) for e in event_list(r, kind)]
                 for r in results]
        assert paths[0] == paths[1]


def test_busy_initial_location_has_find_candidate_and_waiting_after_find():
    result = predict(small_scene(control=config(visual_location="target", visual_processor="busy"))).to_dict()
    conflicts = event_list(result, "conflict_resolution")
    assert [c["name"] for c in conflicts[0]["details"]["candidates"]] == ["find"]
    assert conflicts[-1]["details"]["candidates"] == []
    assert result["final_state"]["goal_state"] == "look_after_find"
    assert result["final_state"]["visual_location"]["target"] == "target"
    assert result["final_state"]["visual_content"] is None
    assert result["final_state"]["visual_processor"] == "busy"
    assert result["final_state"]["visual_completion_time_s"] is None


def test_equal_utility_uses_definition_order_not_first_candidate():
    result = predict(small_scene(control=next(c.control for c in CASES if c.id == "G_equal_utility"))).to_dict()
    conflict = next(e for e in event_list(result, "conflict_resolution")
                    if {c["name"] for c in e["details"]["candidates"]} ==
                    {"*suppress-re-encoding", "find-location", "move-mouse"})
    assert conflict["start_s"] == .1
    assert {c["name"]: c["utility"] for c in conflict["details"]["candidates"]} == {
        "*suppress-re-encoding": 0, "find-location": -1, "move-mouse": 0}
    assert conflict["details"]["selected"]["name"] == "move-mouse"


@pytest.mark.parametrize("at_s, request_kind", [(.025, "visual_attention_request"), (.075, "mouse_request")])
def test_pending_firing_keeps_binding_without_restoring_replaced_buffer(at_s, request_kind):
    result = predict(small_scene(control=config(visual_location="target",
                     updates=(SyntheticUpdate(at_s, "location_set", "other", True),)))).to_dict()
    request = event_list(result, request_kind)[0]
    assert request["details"]["bound_location"]["chunk_id"] == "location:f:target"
    assert request["state_after"]["visual_location"]["chunk_id"] == "location:f:other"
    assert request["state_after"]["location_requested"] is True
    assert request["start_s"] == (.05 if request_kind == "visual_attention_request" else .1)


def test_source_start_and_stuffing_run_before_first_target_selection():
    for scene, stuffed, first, time_s in (("two_buttons", "target", "look-at", .1),
                                         ("left_distractor", "other", "find", .15)):
        result = predict(small_scene(scene, ControlConfig.source_2014(provenance="independent source-order test"))).to_dict()
        initial = event_list(result, "initial_state")[0]["state_after"]
        assert initial["current_frame"] is None
        assert initial["frame_visible"] is False
        assert initial["visual_location"] is None
        assert initial["scene_locations"] == []
        assert result["first_selected_rule"] == "set-start-frame"
        assert result["first_firing_time_s"] == 0
        assert result["first_target_rule"] == first
        assert result["first_mouse_request_time_s"] == time_s
        stuff = event_list(result, "visual_location_stuffed")[0]
        assert stuff["state_after"]["visual_location"]["target"] == stuffed
        assert stuff["state_after"]["location_requested"] is False
        assert stuff["start_s"] == 0
        first_target = next(e for e in event_list(result, "production_selected") if e["rule"] != "set-start-frame")
        assert stuff["index"] < first_target["index"]


def test_same_time_rhs_priorities_and_late_visual_unlock():
    result = predict(small_scene(control=config(visual_location="target"))).to_dict()
    at_look = [e for e in result["events"] if e["start_s"] == .05]
    kinds = [e["event_type"] for e in at_look]
    for earlier, later in (("production_fired", "goal_update"),
                           ("goal_update", "visual_attention_request"),
                           ("visual_attention_request", "visual_buffer_clear"),
                           ("visual_buffer_clear", "visual_attention_started"),
                           ("visual_attention_started", "conflict_resolution"),
                           ("production_selected", "visual_request_unlock")):
        assert kinds.index(earlier) < kinds.index(later)
    assert next(e for e in at_look if e["event_type"] == "production_selected")["rule"] == "move-mouse"


@pytest.mark.parametrize("kwargs,status", [({"max_events": 1}, "event_limit"), ({"max_time_s": .02}, "time_limit")])
def test_boundaries_do_not_turn_unfired_pending_work_into_success(kwargs, status):
    result = predict(small_scene(control=config(visual_location="target", **kwargs))).to_dict()
    assert result["completion_status"] == status
    assert result["first_mouse_request_time_s"] is None
    assert result["reported_task_time_s"] is None
    assert event_list(result, "prefix_boundary")[0]["details"]["pending_events"] > 0


def test_changing_production_duration_changes_rules_not_an_extra_global_charge():
    project = small_scene(control=config(visual_location="target"))
    project = replace(project, parameters=project.parameters.override("production_action_s", .08, source=PROVENANCE))
    result = predict(project).to_dict()
    assert [e["start_s"] for e in event_list(result, "production_fired")] == [.08, .16]
    assert result["first_mouse_request_time_s"] == .16
    assert result["last_device_output_time_s"] == .314
    assert result["last_manual_release_time_s"] == .364
    assert result["reported_task_time_s"] is None


def archive_boundary(matrix_archive, case_id, control, expected, check, observed=None):
    """Keep boundary outcomes with the matrix, including assertions that fail."""
    out, rows = matrix_archive
    project = small_scene(control=control)
    row = {"id": case_id, "why": "Independent motor admission / FIND failure boundary",
           "expected": expected}
    try:
        result = predict(project).to_dict()
        if out is not None:
            folder = out / case_id
            folder.mkdir()
            (folder / "input.json").write_text(json.dumps(project.to_dict(), ensure_ascii=False, indent=2) + "\n")
            (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        row["actual"] = {"rules": [e["rule"] for e in event_list(result, "production_fired")],
                         "fired_s": [e["start_s"] for e in event_list(result, "production_fired")],
                         "mouse_request_s": result["first_mouse_request_time_s"],
                         "completion": result["completion_status"],
                         "motor_event_count": len(result["motor_events"])}
        if observed is not None:
            row["actual"]["observed_callback_priorities"] = observed
        check(result)
        row["outcome"] = "passed"
    except Exception as error:
        row.update(outcome="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        rows.append(row)


def test_execution_busy_after_move_selection_preserves_request_but_stops_outside_queue_scope(matrix_archive):
    # LOOK selects MOVE at .050 while manual is free. The synthetic update at
    # .075 only changes execution. MOVE must still fire/request at .100. Source
    # check-jam tests preparation, then preparation-complete queues the movement
    # until execution is free. Since that queue is outside this prefix, no motor
    # output/release can be claimed. This does not assert an upstream jam.
    def check(result):
        fired = event_list(result, "production_fired")
        assert [(e["rule"], e["start_s"]) for e in fired] == [("look-at", .05), ("move-mouse", .1)]
        selected = event_list(result, "production_selected")[-1]
        assert selected["rule"] == "move-mouse"
        assert selected["start_s"] == .05
        assert selected["state_after"]["manual_state"] == "free"
        assert fired[-1]["state_after"]["manual"]["motor_execution"] == "busy"
        assert fired[-1]["details"]["lhs_rechecked"] is False
        request = event_list(result, "mouse_request")
        assert len(request) == 1
        assert request[0]["start_s"] == .1
        assert request[0]["details"]["bound_location"]["target"] == "target"
        assert result["first_mouse_request_time_s"] == .1
        unsupported = event_list(result, "unsupported_manual_queue")
        assert len(unsupported) == 1
        assert unsupported[0]["start_s"] == .1
        assert unsupported[0]["details"]["request_preserved"] is True
        assert request[0]["index"] < unsupported[0]["index"]
        assert result["completion_status"] == "unsupported"
        assert result["motor_events"] == []
        assert result["motor_state_changes"] == []
        assert result["last_device_output_time_s"] is None
        assert result["last_manual_release_time_s"] is None
        assert result["reported_task_time_s"] is None
        assert result["final_state"]["manual"]["motor_preparation"] == "free"
        assert result["final_state"]["manual"]["motor_execution"] == "busy"
        assert result["final_state"]["goal_state"] == "after_first_mouse_request"

    archive_boundary(matrix_archive, "B01_manual_execution_changed", config(visual_location="target",
                     updates=(SyntheticUpdate(.075, "manual_busy"),)),
                     {"rules": ["look-at", "move-mouse"], "mouse_request_s": .1,
                      "completion": "unsupported", "motor_event_count": 0}, check)


def test_find_failure_changes_flag_in_priority_zero_search_without_fake_buffer_write(matrix_archive, monkeypatch):
    # Observe real callback priority without altering deadlines, queue ordering,
    # or controller state. This checks execution, not just priority metadata.
    from cogtool_py.control_prefix import PrefixController
    from cogtool_py.motor_subset import Clock

    active_priority, observed = [], {}
    schedule, record = Clock.schedule, PrefixController.record

    def observe_schedule(clock, delay_s, callback, priority=0):
        def execute():
            active_priority.append(priority)
            try:
                return callback()
            finally:
                active_priority.pop()
        return schedule(clock, delay_s, execute, priority=priority)

    def observe_record(controller, kind, **kwargs):
        if active_priority:
            observed.setdefault(kind, []).append(active_priority[-1])
        return record(controller, kind, **kwargs)

    monkeypatch.setattr(Clock, "schedule", observe_schedule)
    monkeypatch.setattr(PrefixController, "record", observe_record)

    def check(result):
        assert [(e["rule"], e["start_s"]) for e in event_list(result, "production_fired")] == [("find", .05)]
        cleared = event_list(result, "visual_location_clear")[0]
        failure = event_list(result, "visual_location_failure")[0]
        notice = event_list(result, "find_loc_failure")[0]
        assert cleared["index"] < failure["index"] < notice["index"]
        assert cleared["start_s"] == failure["start_s"] == notice["start_s"] == .05
        assert failure["state_before"]["location_failure"] is False
        assert failure["state_after"]["location_failure"] is True
        assert failure["state_before"]["visual_location"] is None
        assert failure["state_after"]["visual_location"] is None
        assert failure["details"]["event_priority"] == 0
        assert notice["details"]["event_priority"] == 0
        assert observed["visual_location_clear"] == [10]
        assert observed["visual_location_failure"] == [0]
        assert observed["find_loc_failure"] == [0]
        assert event_list(result, "visual_location_return") == []
        assert event_list(result, "lookup_device_lock") == []
        assert event_list(result, "mouse_request") == []
        assert result["completion_status"] == "deadlock"
        assert result["first_mouse_request_time_s"] is None
        assert result["reported_task_time_s"] is None

    archive_boundary(matrix_archive, "B02_find_failure_priority", config(visible_targets=("other",)),
                     {"failure_callback_priority": 0, "failure_notice_priority": 0,
                      "fake_buffer_write": False, "mouse_request_s": None, "completion": "deadlock"},
                     check, observed)

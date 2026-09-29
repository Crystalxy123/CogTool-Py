"""Independent EMMA consequences from the fixed 2014 source, not old traces."""
from copy import deepcopy
import math

import pytest

from cogtool_py.models import ModelError, ParameterSet
from cogtool_py.motor_subset import Clock
from cogtool_py.vision import VisionModule

pytestmark = pytest.mark.independent


def parameters(**overrides):
    result = ParameterSet.parse({name: {"value": value, "unit": "s", "source": "independent visual test"}
                                 for name, value in {"click_s": .2, "key_s": .1, "homing_s": .4}.items()})
    result = result.with_vision_defaults()
    for name, value in overrides.items():
        result = result.override(name, value, source="independent analytical visual fixture")
    return result


def location(x=0, y=0, target="a", value="a in Frame"):
    return {"chunk_id": f"location:{target}", "target": target, "value": value,
            "x": x, "y": y, "kind": "widget", "creation_time_s": 0.0}


def events(module, kind):
    return [event for event in module.events if event["event_type"] == kind]


def through(clock, time_ms):
    while clock.queue and clock.queue[0][0] <= time_ms:
        clock.step()


def test_initial_eye_is_reset_origin_independent_of_mouse():
    module = VisionModule(parameters())
    assert module.state["eye_location"] == [0, 0]
    assert module.visual_state == "free"
    assert module.state["visual_content"] is None
    assert module.state["visual_completion_time_s"] is None
    assert module.events == [] and not module.has_pending_events


def test_startup_empty_frame_clear_prepares_for_fifty_ms_before_later_fifo_peer():
    module = VisionModule(parameters())
    seen = []
    # cogtool-run-model's synchronous proc-display while curframe NIL invokes
    # clear before RUN schedules the initial production chain.
    module.clear()
    assert module.visual_state == "busy"
    assert module.state["visual_preparation"] == "busy"
    assert module.state["visual_processor"] == module.state["visual_execution"] == "free"
    module.clock.schedule(.05, lambda: seen.append(module.visual_state), priority=0)
    module.clock.drain()
    assert seen == ["free"] and module.clock.now == 50
    assert module.state["eye_location"] == [0, 0]
    assert not events(module, "visual_encoding_complete")
    assert not events(module, "eye_movement_complete")


def test_same_eye_target_encodes_before_preparation_and_does_not_cancel_eye():
    clock = Clock()
    module = VisionModule(parameters(), clock)
    handle = module.request(location(), dependencies=("look-production",))
    assert clock.now == 0 and len(clock.queue) == 2
    # .006 * ln(100) = .027631... -> 28 ms. Fresh style+r+theta = 3*.050.
    through(clock, 28)
    assert module.state["visual_completion_time_s"] == .028
    assert module.state["visual_preparation"] == "busy"
    assert module.state["visual_processor"] == module.state["visual_execution"] == "free"
    assert module.state["visual_content"] == "a"
    assert handle["encoding_completed"] and not handle["completed"]
    through(clock, 150)
    assert module.state["visual_preparation"] == "free"
    assert module.state["visual_execution"] == "busy"
    assert events(module, "eye_preparation_complete")[0]["details"]["features_to_prepare"] == 3
    clock.drain()
    assert clock.now == 220  # .150 preparation + .050 initiation + .020 base.
    assert module.visual_state == "free" and handle["completed"]
    assert not module.has_pending_events
    assert all(e["status"] == "executed" for e in module.events)
    assert events(module, "visual_attention_request")[0]["dependencies"] == ["look-production"]


def test_initial_eye_at_target_differs_from_origin_without_using_mouse():
    same = VisionModule(parameters(), initial_eye=(1080, 0))
    distant = VisionModule(parameters())
    same.request(location(1080))
    distant.request(location(1080))
    same.clock.drain()
    distant.clock.drain()
    assert same.state["visual_completion_time_s"] == .028
    assert distant.state["visual_completion_time_s"] == .338
    assert same.clock.now == 220 and distant.clock.now == 430


def test_late_encoding_branch_uses_actual_rounded_elapsed_time_and_residual():
    module = VisionModule(parameters())
    module.request(location(1080))  # 1080 px / 72 / 15 = 1 -> exactly 45 degrees.
    assert not events(module, "visual_encoding_complete")
    through(module.clock, 310)
    # .150 + (.050 + 45*.002 + .020) = .310.
    assert module.state["eye_location"] == [1080, 0]
    first = events(module, "eye_movement_complete")[0]
    raw_initial = .006 * math.log(100) * math.exp(18)
    residual = .006 * math.log(100) * (1 - .310 / raw_initial)
    assert first["details"]["previous_raw_encoding_s"] == pytest.approx(raw_initial)
    assert first["details"]["raw_remaining_encoding_s"] == pytest.approx(residual)
    assert events(module, "visual_encoding_complete")[0]["end_s"] == .338
    # Distance45->0 counts one changed feature; the second eye is not cancelled.
    assert events(module, "eye_preparation_complete")[1]["end_s"] == .360
    module.clock.drain()
    assert [e["end_s"] for e in events(module, "eye_movement_complete")] == [.310, .430]
    assert module.state["visual_completion_time_s"] == .338


def test_buffer_write_priority_ten_precedes_same_time_zero_and_conflict_min():
    order = []
    clock = Clock()
    module = VisionModule(parameters(), clock,
        on_state_change=lambda _, record: order.append(record["trigger"]))
    module.request(location())
    clock.schedule(.028, lambda: order.append("peer-zero"), priority=0)
    clock.schedule(.028, lambda: order.append("conflict-min"), priority=":min")
    through(clock, 28)
    assert order.index("visual_encoding_complete") < order.index("visual_buffer_write")
    assert order.index("visual_buffer_write") < order.index("peer-zero") < order.index("conflict-min")
    assert events(module, "visual_buffer_write")[0]["event_priority"] == 10
    assert module.state["visual_requested"] is True


def test_same_tick_preparation_was_scheduled_before_encoding():
    # .150 exactly from -ln(exp(-1))*.15; threshold uses raw durations.
    module = VisionModule(parameters(visual_object_frequency=math.exp(-1), visual_encoding_factor_s=.15))
    module.request(location())
    through(module.clock, 150)
    changes = [c["trigger"] for c in module.state_changes if c["time_s"] == .150]
    assert changes == ["eye_preparation_complete", "eye_execution_started",
                       "visual_encoding_complete", "visual_buffer_write"]
    assert module.state["visual_execution"] == "free"
    assert module.has_pending_events
    module.clock.drain()
    assert module.clock.now == 220


def test_zero_duration_encoding_and_eye_events_have_bounded_same_tick_order():
    module = VisionModule(parameters(visual_object_frequency=1, eye_feature_prep_s=0,
                                      eye_initiation_s=0, eye_saccade_base_s=0))
    request = module.request(location())
    module.clock.drain()
    assert module.clock.now == 0
    assert request["completed"] and module.unsupported_reason is None
    assert len(events(module, "eye_movement_complete")) == 1
    assert module.state["visual_completion_time_s"] == 0


def test_repeated_attention_after_full_release_reuses_zero_changed_features():
    module = VisionModule(parameters())
    first = module.request(location())
    module.clock.drain()
    second = module.request(location())
    assert second["request_id"] != first["request_id"]
    assert events(module, "eye_preparation_complete")[-1]["details"]["features_to_prepare"] == 0
    module.clock.drain()
    assert second["completed"] and module.clock.now == 290
    assert module.state["visual_completion_time_s"] == .248


def test_new_target_after_release_carries_saccade_features():
    module = VisionModule(parameters())
    module.request(location())
    module.clock.drain()
    module.request(location(1080, target="b", value="b in Frame"))
    prep = events(module, "eye_preparation_complete")[-1]
    assert prep["details"]["features_to_prepare"] == 1  # r changed, theta remains0.
    assert prep["end_s"] == .270
    module.clock.drain()
    assert module.state["visual_content"] == "b"
    assert module.unsupported_reason is None


def test_clear_has_literal_fifty_ms_cost_and_resets_feature_carryover():
    module = VisionModule(parameters(eye_feature_prep_s=.02))
    module.request(location())
    module.clock.drain()
    assert module.clock.now == 130  # 3*.02+.07
    before = deepcopy(module.state)
    clear = module.clear()
    assert clear["end_s"] == .180  # Clear source literal .050, not feature parameter .020.
    assert module.state["visual_preparation"] == "busy"
    assert module.state["visual_content"] == before["visual_content"]
    assert module.state["last_prepared"] is None
    module.clock.drain()
    module.request(location())
    assert events(module, "eye_preparation_complete")[-1]["details"]["features_to_prepare"] == 3
    module.clock.drain()
    assert module.clock.now == 310


def test_clear_during_eye_tail_preserves_eye_event_and_fifo_same_time_finish():
    order = []
    module = VisionModule(parameters(), on_state_change=lambda _, c: order.append((c["time_s"], c["trigger"])))
    module.request(location())
    def clear():
        assert module.state["visual_execution"] == "busy"
        module.clear()
        # V2348-2353 remove-tracking unconditionally releases execution, even
        # though the already scheduled eye-complete callback still survives.
        assert module.state["visual_execution"] == "free"
        assert module.state["visual_preparation"] == "busy"
        assert module.has_pending_events
    module.clock.schedule(.170, clear)
    module.clock.drain()
    assert module.clock.now == 220
    assert [kind for when, kind in order if when == .220] == ["eye_movement_complete", "eye_execution_release", "visual_clear_complete"]
    assert all(event["status"] == "executed" for event in module.events)
    assert module.state["visual_content"] == "a" and module.state["attended_target"] is None


def test_clear_buffer_is_separate_explicit_controller_operation():
    module = VisionModule(parameters())
    module.request(location())
    module.clock.drain()
    module.clear(clear_buffer=True)
    assert module.state["visual_content"] is None
    assert module.state["visual_requested"] is False
    module.clock.drain()


def test_clear_before_late_encoding_does_not_invent_processor_release():
    module = VisionModule(parameters())
    request = module.request(location(1080))
    module.clock.schedule(.2, module.clear)
    module.clock.drain()
    # clear makes moving-attention NIL; the scheduled eye still lands at .310,
    # but no residual encoding is initiated and clear never frees processor.
    assert module.clock.now == 310 and module.state["eye_location"] == [1080, 0]
    assert module.state["visual_processor"] == "busy"
    assert module.state["visual_completion_time_s"] is None
    assert not request["completed"] and not module.has_pending_events


def test_direction_feature_changes_without_distance_change():
    module = VisionModule(parameters())
    module.request(location(10))
    module.clock.drain()
    module.request(location(10, 10, target="b"))
    second = events(module, "eye_preparation_complete")[-1]
    assert second["details"]["features_to_prepare"] == 1
    assert second["details"]["direction_rad"] == pytest.approx(math.pi / 2)
    module.clock.drain()
    assert module.state["eye_location"] == [10, 10]


def test_rounded_landing_is_not_forced_to_fractional_target():
    module = VisionModule(parameters(), initial_eye=(.5, .5))
    module.request(location(.5, .5))
    module.clock.drain()
    # Even zero radial displacement passes through round-xy (CL ROUND ties-even).
    assert module.state["eye_location"] == [0, 0]
    assert module.state["visual_object"]["x"] == .5


@pytest.mark.parametrize("value", ["x", "a very long title that is deliberately unrelated to frequency", "中文标签"])
def test_string_length_does_not_determine_frequency(value):
    module = VisionModule(parameters())
    module.request(location(value=value))
    module.clock.drain()
    assert module.state["visual_completion_time_s"] == .028
    assert events(module, "visual_attention_request")[0]["details"]["frequency"] == .01


def test_bound_location_is_copied_and_old_chunk_identity_survives_caller_change():
    loc = location()
    module = VisionModule(parameters())
    module.request(loc)
    loc.update(target="changed", x=10000, value="new")
    module.clock.drain()
    assert module.state["visual_content"] == "a"
    assert module.state["visual_object"]["chunk_id"] == "location:a"


@pytest.mark.parametrize("at_s", [.010, .170])
def test_switch_while_old_events_pending_is_explicit_unsupported_with_physical_cleanup(at_s):
    module = VisionModule(parameters())
    first = module.request(location())
    module.clock.schedule(at_s, lambda: module.request(location(10, target="b")))
    module.clock.drain()
    assert module.unsupported_reason.startswith("overlapping attention request")
    assert module.clock.now == round(at_s * 1000)
    assert not first["completed"] and not module.requests[-1]["completed"]
    assert not module.has_pending_events
    cancelled = [e for e in module.events if e["status"] == "cancelled"]
    assert cancelled and all("not an upstream" in e["cancellation_reason"] for e in cancelled)
    assert not any(e["request_id"] == "attention-1" and e["event_type"] == "visual_buffer_write" for e in module.events)


@pytest.mark.parametrize("disappear_at, target_x, expected_clock", [(0.010, 0, 28), (.200, 1080, 310)])
def test_disappearance_does_not_invent_completion_or_release(disappear_at, target_x, expected_clock):
    visible = {"a"}
    module = VisionModule(parameters(), visible=lambda target: target in visible)
    request = module.request(location(target_x))
    module.clock.schedule(disappear_at, lambda: visible.clear())
    module.clock.drain()
    assert "disappeared" in module.unsupported_reason
    assert module.clock.now == expected_clock
    assert not request["completed"] and module.state["visual_content"] is None
    assert module.state["visual_completion_time_s"] is None
    assert module.state["visual_processor"] == "busy"  # Last confirmed state, not fake release.


def test_absent_target_request_is_boundary_with_no_scheduled_motion():
    module = VisionModule(parameters(), visible=lambda _: False)
    request = module.request(location())
    assert "absent" in module.unsupported_reason and not request["completed"]
    assert not module.has_pending_events and module.clock.now == 0


def test_busy_preparation_clear_is_explicit_boundary_not_automatic_cancel_rule():
    module = VisionModule(parameters())
    module.request(location())
    module.clear()
    assert "jam" in module.unsupported_reason
    assert module.state["visual_preparation"] == "busy"
    assert not module.has_pending_events


def test_eye_events_overlap_unrelated_manual_event_on_shared_clock():
    clock, seen = Clock(), []
    module = VisionModule(parameters(), clock, on_state_change=lambda _, c: seen.append((c["time_s"], c["trigger"])))
    module.request(location(1080))
    clock.schedule(.200, lambda: seen.append((clock.now / 1000, "manual_device_output")))
    clock.drain()
    assert (.200, "manual_device_output") in seen
    assert seen.index((.200, "manual_device_output")) < seen.index((.310, "eye_movement_complete"))
    assert clock.now == 430  # Not .430+.200; no module drains a private clock.


@pytest.mark.parametrize("coordinate", [True, float("nan"), float("inf"), "1"])
def test_invalid_eye_coordinate_is_rejected(coordinate):
    with pytest.raises(ModelError):
        VisionModule(parameters(), initial_eye=(coordinate, 0))


@pytest.mark.parametrize("value", [None, 2, {}, ""])
def test_nonstring_or_empty_value_has_no_frequency_guess(value):
    module = VisionModule(parameters())
    with pytest.raises(ModelError, match="location.value"):
        module.request(location(value=value))
    assert not module.events


def test_effective_parameters_required_without_silent_default_injection():
    p = ParameterSet.parse({n: {"value": .1, "unit": "s", "source": "test"}
                           for n in ("click_s", "key_s", "homing_s")}).with_control_defaults()
    with pytest.raises(ModelError, match="effective vision"):
        VisionModule(p)

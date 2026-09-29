"""Synthetic bookkeeping tests, independent of control-prefix predictions.

Hand-authored timestamps below test evidence handling, not source timing accuracy.
"""
import json

import pytest

from cogtool_py.models import ModelError
from scripts.run_control_prefix_validation import (
    CONTROL_ENGINE, historical_observations, run, verify_prefix,
)

pytestmark = pytest.mark.independent


def example_result():
    def event(event_id, kind, rule, stamp):
        return {"event_id": event_id, "event_type": kind, "rule": rule, "start_s": stamp}
    return {
        "engine_id": CONTROL_ENGINE, "engine": {"name": CONTROL_ENGINE},
        "engine_version": "synthetic", "source_commit": "synthetic", "implementation": {"sha256": "code"},
        "initial_state_profile": "synthetic_controller_only", "initial_state_provenance": "synthetic_unit_test",
        "first_selected_rule": "set-start-frame", "first_firing_time_s": 0,
        "first_target_rule": "find", "first_target_rule_firing_time_s": .05,
        "first_mouse_request_time_s": .15, "task_stop_time_s": None,
        "last_device_output_time_s": .30, "last_manual_release_time_s": .35,
        "reported_task_time_s": None, "predicted_time_s": None, "original_rerun_s": None,
        "completion_status": "partial", "remaining_unsupported_mechanisms": ["synthetic unfinished visual encoding"],
        "events": [event("c1", "production_selected", "set-start-frame", 0),
                   event("c2", "production_fired", "set-start-frame", 0),
                   event("c3", "production_selected", "find", 0),
                   event("c4", "production_fired", "find", .05),
                   event("c5", "mouse_request", "move-mouse", .15)],
        "motor_events": [{"event_type": "motor_preparation", "start_s": .15, "end_s": .17,
                          "dependencies": ["c5"], "state_after": {}},
                         {"event_type": "cursor_move", "start_s": .17, "end_s": .30, "state_after": {}},
                         {"event_type": "cursor_finish", "start_s": .17, "end_s": .35, "state_after": {}}],
    }


def test_partial_result_has_no_task_total_despite_completed_motor_events():
    result = example_result()
    assert verify_prefix(result, "code") == []
    result["reported_task_time_s"] = 0
    assert "reported_task_time_s must remain explicitly null for this incomplete task" in verify_prefix(result, "code")
    result["reported_task_time_s"] = .35
    assert "reported_task_time_s must remain explicitly null for this incomplete task" in verify_prefix(result, "code")


def test_motor_request_must_share_actual_control_clock_and_dependency():
    result = example_result()
    result["motor_events"][0]["start_s"] = 0
    result["motor_events"][0]["dependencies"] = []
    issues = verify_prefix(result, "code")
    assert "shared motor was not requested at the actual control request timestamp" in issues
    assert "first motor event does not reference the control request" in issues


def test_invalid_observation_is_failure_and_not_zero_or_unhandled_comparison():
    result = example_result()
    result["events"][0]["start_s"] = None
    assert "event 0: invalid observation timestamp" in verify_prefix(result, "code")
    result["events"][0]["start_s"] = float("nan")
    assert "event 0: invalid observation timestamp" in verify_prefix(result, "code")
    result["completion_status"] = "deadlock"
    assert "first-request prefix not reached: deadlock" in verify_prefix(result, "code")


def test_archived_bootstrap_target_and_request_remain_distinct_point_events(tmp_path):
    events = [
        {"line_number": 2, "module": "PROCEDURAL", "message": "PRODUCTION-SELECTED SET-START-FRAME-1", "timestamp_s": 0},
        {"line_number": 3, "module": "PROCEDURAL", "message": "PRODUCTION-FIRED SET-START-FRAME-1", "timestamp_s": 0},
        {"line_number": 6, "module": "PROCEDURAL", "message": "PRODUCTION-SELECTED FIND-2", "timestamp_s": .01},
        {"line_number": 7, "module": "PROCEDURAL", "message": "PRODUCTION-FIRED FIND-2", "timestamp_s": .06},
        {"line_number": 9, "module": "MOTOR", "message": "MOVE-CURSOR OBJECT TARGET", "timestamp_s": .16},
    ]
    (tmp_path / "point_events.json").write_text(json.dumps(events))
    (tmp_path / "reference_metadata.json").write_text('{"cached_prediction_s": null}')
    reference = historical_observations(tmp_path)
    assert reference["first_selected_rule_event"] == events[0]
    assert reference["first_target_selected_event"] == events[2]
    assert reference["first_target_fired_event"] == events[3]
    assert reference["first_mouse_request_event"] == events[4]
    assert reference["cached_metadata"]["cached_prediction_s"] is None
    assert reference["original_rerun_s"] is None
    assert reference["reuse"]["raw_trace_reparsed"] is False
    assert all("duration_s" not in item for item in events)


def test_existing_output_is_rejected_before_loading_or_overwriting(tmp_path):
    output = tmp_path / "evidence"
    output.mkdir()
    saved = output / "original.json"
    saved.write_text('{"saved": true}')
    with pytest.raises(ModelError, match="output exists"):
        run(tmp_path / "missing_input", tmp_path / "missing_scene", tmp_path / "missing_reference", output)
    assert saved.read_text() == '{"saved": true}'

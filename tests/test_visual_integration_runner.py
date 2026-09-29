"""Independent synthetic bookkeeping checks; no prediction function is called."""
from copy import deepcopy

import pytest

from cogtool_py.models import ModelError
from scripts.run_visual_integration_validation import (CONTROL_ENGINE, MILESTONES,
    legacy_comparison, run, verify_complete, visual_milestones)

pytestmark = pytest.mark.independent


def example_result():
    def event(kind, start, end=None, **fields):
        return {"event_type": kind, "start_s": start, "end_s": start if end is None else end, **fields}
    result = {key: None for key in MILESTONES}
    result.update(engine_id=CONTROL_ENGINE, engine={"name": CONTROL_ENGINE, "version": "synthetic"},
        engine_version="synthetic", execution_scope="integrated_task", implementation={"sha256": "code"},
        input_sha256="input", completion_status="complete", original_rerun_s=None,
        remaining_unsupported_mechanisms=[], blocker=None, control_configuration={"updates": []},
        reported_task_time_s=.7, predicted_time_s=.7, simulation_end_time_s=.7,
        model_stop_time_s=.1, task_stop_time_s=.1, last_device_output_time_s=.6, last_manual_release_time_s=.7,
        termination_reason="event_queue_exhausted_after_stop",
        steps=[{"index": 0, "op": "point", "target": "target"}],
        events=[event("production_fired", .1, rule="stop"), event("model_stop", .1),
                event("task_boundary", .7, details={"full_task_completed": True, "pending_events": 0})],
        motor_events=[event("cursor_move", .1, .6, step_index=0, op="point", target="target", state_after={}),
                      event("cursor_finish", .1, .7, step_index=0, op="point", target="target", state_after={})],
        vision_events=[event("visual_attention_request", .05, request_id="a", target="target", status="executed", state_after={}),
                       event("visual_encoding_complete", .05, .3, request_id="a", target="target", status="executed", state_after={}),
                       event("eye_movement_complete", .2, .4, request_id="a", target="target", status="executed", state_after={})],
        final_state={"goal_state": "stop", "manual_state": "free", "vision": {
            "visual_preparation": "free", "visual_processor": "free", "visual_execution": "free",
            "pending_events": [], "unsupported_reason": None}})
    return result


def test_complete_total_is_last_executed_event_not_early_stop_or_duration_sum():
    result = example_result()
    assert verify_complete(result, "code", "input") == []
    result.update(predicted_time_s=.1, reported_task_time_s=.1, simulation_end_time_s=.1)
    assert "simulation end differs from last actually executed module/STOP event" in verify_complete(result, "code")


@pytest.mark.parametrize("status", ["pending", "cancelled"])
def test_unfinished_or_cancelled_encoding_cannot_count_as_complete(status):
    result = example_result()
    result["vision_events"][1]["status"] = status
    issues = verify_complete(result, "code")
    assert "pending/cancelled/unexecuted visual events cannot masquerade as completion" in issues
    assert "visual request lacks exactly one matching encoding completion: a" in issues


def test_matching_request_identity_and_target_are_required():
    result = example_result()
    result["vision_events"][1]["request_id"] = "other-request"
    assert "orphan visual encoding completion" in verify_complete(result, "code")
    result["vision_events"][1]["request_id"] = "a"
    result["vision_events"][1]["target"] = "another-target"
    assert "visual request lacks exactly one matching encoding completion: a" in verify_complete(result, "code")


def test_stop_and_exhaustion_evidence_are_required_and_unknown_original_is_not_zero():
    result = example_result()
    result["original_rerun_s"] = 0
    result["events"] = result["events"][-1:]
    result["events"][0]["details"]["pending_events"] = 1
    issues = verify_complete(result, "code")
    assert "original rerun must remain explicitly null" in issues
    assert "complete result requires one actual STOP firing and model_stop record" in issues
    assert "complete result lacks exhausted-queue task boundary evidence" in issues


def test_duplicate_device_output_and_synthetic_completion_signal_are_failures():
    result = example_result()
    result["motor_events"].append(deepcopy(result["motor_events"][0]))
    result["control_configuration"]["updates"] = [{"at_s": .01, "kind": "visual_free"}]
    issues = verify_complete(result, "code")
    assert "generated device steps and actually completed outputs differ" in issues
    assert "integrated input includes prescribed completion updates or omits their evidence" in issues


def test_old_prefix_null_cannot_be_silently_replaced_with_complete_total():
    before = {"input_sha256": "same", "engine": {"version": "old"}, "predicted_time_s": None,
              "implementation": "before", "execution_fingerprint": "before", "program_runtime_s": 1}
    after = {**before, "implementation": "after", "execution_fingerprint": "after", "program_runtime_s": 2}
    assert legacy_comparison(before, after)["equal"] is True
    after["predicted_time_s"] = 0
    check = legacy_comparison(before, after)
    assert check["equal"] is False and check["changed_fields"] == [".predicted_time_s"]


def test_visual_release_comes_from_actual_state_transition_not_event_duration_sum():
    free = {key: "free" for key in ("visual_preparation", "visual_processor", "visual_execution")}
    busy = {**free, "visual_execution": "busy"}
    result = example_result()
    result["vision_state_changes"] = [{"time_s": .4, "before": busy, "after": free},
                                       {"time_s": .5, "before": free, "after": free}]
    observed = visual_milestones(result)
    assert observed["last_visual_resource_release_time_s"] == .4
    assert observed["last_visual_event_time_s"] == .4
    assert observed["visual_request_count"] == observed["encoding_completion_count"] == 1


def test_fresh_output_required_even_when_old_directory_empty(tmp_path):
    output = tmp_path / "saved"
    output.mkdir()
    with pytest.raises(ModelError, match="output exists"):
        run(tmp_path / "missing-input", output)
    assert list(output.iterdir()) == []

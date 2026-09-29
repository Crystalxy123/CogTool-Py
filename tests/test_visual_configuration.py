"""New opt-in visual parameters and scope obey the existing input lifecycle."""
from dataclasses import replace

import pytest

from cogtool_py.engine import predict
from cogtool_py.io import input_hash, save_project, load_project
from cogtool_py.models import ModelError, ParameterSet, VISION_DEFAULTS
from tests.test_control_integration import integration_scene


@pytest.mark.parametrize("frequency", [0, -0.1, 1.01, float("nan"), float("inf")])
def test_log_frequency_outside_supported_probability_range_is_rejected(frequency):
    with pytest.raises(ModelError):
        integration_scene().parameters.override("visual_object_frequency", frequency,
                                                source="invalid independent test input")


def test_visual_parameter_override_is_isolated_and_persisted(tmp_path):
    original = integration_scene()
    changed = replace(original, parameters=original.parameters.override(
        "visual_encoding_factor_s", .009, source="synthetic encoding-factor sensitivity"))
    with pytest.raises(TypeError):
        changed.parameters.entries["visual_encoding_factor_s"] = original.parameters.entries["visual_encoding_factor_s"]
    assert original.parameters.value("visual_encoding_factor_s") == .006
    assert input_hash(changed) != input_hash(original)
    target = tmp_path / "overridden.json"
    save_project(changed, target)
    restored = load_project(target)
    assert restored == changed and input_hash(restored) == input_hash(changed)
    before, after = predict(changed).data, predict(restored).data
    assert before["vision_events"] == after["vision_events"]
    assert before["reported_task_time_s"] == after["reported_task_time_s"]


def test_distinct_synthetic_eye_input_survives_without_moving_mouse(tmp_path):
    project = integration_scene("point")
    control = replace(project.control, profile="synthetic_controller_only",
                      initial_eye=(1, 0), visual_location="target", auto_stuffing=False)
    synthetic = replace(project, control=control)
    target = tmp_path / "eye.json"
    save_project(synthetic, target)
    result = predict(load_project(target)).data
    assert result["initial_state"]["mouse"] == (0.0, 0.0)
    request = next(e for e in result["vision_events"] if e["event_type"] == "visual_attention_request")
    assert request["details"]["eccentricity_deg"] == 0
    assert request["state_before"]["eye_location"] == [1.0, 0.0]
    assert result["completion_status"] == "complete"


def test_complete_visual_parameter_group_cannot_leak_into_prefix_scope():
    project = integration_scene("point")
    with pytest.raises(ModelError, match="integrated_task"):
        predict(replace(project, control=replace(project.control, execution_scope="prefix_only")))
    values = dict(project.parameters.entries)
    values.pop("eye_initiation_s")
    with pytest.raises(ModelError, match="all effective vision"):
        ParameterSet(values)
    # Legacy opt-in remains a separate, complete parameter profile.
    legacy = ParameterSet({k: v for k, v in project.parameters.entries.items() if k not in VISION_DEFAULTS})
    result = predict(replace(project, parameters=legacy,
                            control=replace(project.control, execution_scope="prefix_only"))).data
    assert result["engine_version"] == "0.1.0"
    assert result["reported_task_time_s"] is None


def test_unmodeled_prescribed_visual_content_is_rejected_in_integrated_scope():
    project = integration_scene("point")
    config = replace(project.control, profile="synthetic_controller_only", visual_content="target")
    with pytest.raises(ModelError, match="prescribed visual content"):
        predict(replace(project, control=config))


def test_implicit_visual_buffer_clear_removes_content_object_and_requested_origin():
    result = predict(integration_scene()).data
    clears = [event for event in result["events"] if event["event_type"] == "visual_buffer_clear"]
    assert len(clears) >= 2
    for event in clears:
        state = event["state_after"]
        assert state["visual_content"] is None and state["visual_object"] is None
        assert state["visual_requested"] is False
        assert state["vision"]["visual_content"] is None and state["vision"]["visual_object"] is None
        assert state["vision"]["visual_requested"] is False

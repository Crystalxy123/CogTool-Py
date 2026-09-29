"""Parameter persistence/identity contracts; these are not upstream predictions."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from cogtool_py.engine import predict
from cogtool_py.io import implementation_fingerprint, input_hash, load_project, read_json, save_project
from cogtool_py.models import DEFAULTS, DemonstrationStep, ModelError, Parameter, ParameterSet, Project, Transition


pytestmark = pytest.mark.independent
ROOT = Path(__file__).resolve().parents[1]


def parameters() -> ParameterSet:
    return ParameterSet.parse({
        key: {"value": value, "unit": "s", "source": "authored software test assumption"}
        for key, value in (("click_s", 0.2), ("key_s", 0.1), ("homing_s", 0.4))
    })


def document() -> dict:
    return {
        "schema_version": 1, "id": "lifecycle", "name": "参数生命周期", "engine": "klm_baseline",
        "parameters": {
            key: {"value": value, "unit": "s", "source": "authored software test assumption"}
            for key, value in (("click_s", 0.2), ("key_s", 0.1), ("homing_s", 0.4))
        },
        "design": {"id": "d", "name": "坐标示例", "coordinate_unit": "px", "transitions": [],
                   "frames": [{"id": "f", "name": "页", "widgets": [
                       {"id": "w", "name": "w", "label": "按钮", "kind": "button",
                        "x": -20, "y": -30, "width": 10, "height": 10}
                   ]}]},
        "tasks": [{"id": "t", "name": "思考等待", "demonstration": {
            "initial": {"frame": "f", "mouse": [-50, -60], "mouse_hand": "right", "hand": "mouse", "focus": None},
            "steps": [{"op": "think"}, {"op": "wait", "duration_s": 0.35}],
        }}],
    }


def test_entries_and_parameter_values_are_deeply_immutable_and_copied():
    supplied = dict(parameters().entries)
    first = ParameterSet(supplied)
    old = first.entries["think_s"]
    supplied["think_s"] = replace(old, value=8)
    assert first.value("think_s") == 1.2
    with pytest.raises(TypeError):
        first.entries["think_s"] = replace(old, value=2.4)
    with pytest.raises(FrozenInstanceError):
        first.entries["think_s"].value = 2.4
    with pytest.raises(TypeError):
        DEFAULTS["think_s"] = replace(old, value=2.4)


def test_override_returns_independent_set_without_changing_other_projects():
    first, other = Project.from_dict(document()), Project.from_dict(document())
    changed = replace(first, parameters=first.parameters.override("think_s", 2.4, source="explicit test override"))
    assert changed.parameters is not first.parameters
    assert first.parameters.value("think_s") == other.parameters.value("think_s") == 1.2
    assert changed.parameters.value("think_s") == 2.4
    assert changed.parameters.entries["think_s"].kind == "modeler_supplied"
    assert changed.parameters.entries["think_s"].default_version == first.parameters.entries["think_s"].default_version
    assert predict(first).data["predicted_time_s"] == pytest.approx(1.55)
    assert predict(changed).data["predicted_time_s"] == pytest.approx(2.75)
    assert input_hash(changed) != input_hash(first) == input_hash(other)


@pytest.mark.parametrize("overridden", [False, True])
def test_v1_default_or_override_saves_full_v2_and_roundtrips(tmp_path, overridden):
    project = Project.from_dict(document())
    if overridden:
        project = replace(project, parameters=project.parameters.override("think_s", 2.4, source="roundtrip assumption"))
    before = project.parameters.result_dict()
    output = tmp_path / "stored.json"
    save_project(project, output)
    saved = read_json(output)
    assert saved["schema_version"] == 2
    assert saved["parameters"] == before
    assert len(saved["parameters"]) == 9
    assert all(set(p) == {"value", "unit", "source", "kind", "scope", "overridable", "default_version"}
               for p in saved["parameters"].values())
    restored = load_project(output)
    assert restored == project
    assert input_hash(restored) == input_hash(project)
    assert predict(restored).data["predicted_time_s"] == predict(project).data["predicted_time_s"]


def test_v1_full_parameter_metadata_is_not_discarded():
    raw = document()
    effective = parameters().override("think_s", 2.4, source="retained provenance").input_dict()
    effective["think_s"].update(scope="custom documented scope", default_version="archived-default-set-1", overridable=False)
    raw["parameters"] = effective
    project = Project.from_dict(raw)
    assert project.parameters.input_dict() == effective
    assert project.to_dict()["parameters"] == effective


@pytest.mark.parametrize("field,value", [
    ("value", 2.4), ("source", "another provenance"), ("kind", "modeler_supplied"),
    ("scope", "another declared scope"), ("overridable", False), ("default_version", "historical-set-2"),
])
def test_content_hash_covers_every_effective_metadata_field(field, value):
    first = Project.from_dict(document())
    entries = dict(first.parameters.entries)
    entries["think_s"] = replace(entries["think_s"], **{field: value})
    changed = replace(first, parameters=ParameterSet(entries))
    assert input_hash(changed) != input_hash(first)


def test_hash_ignores_parameter_order_and_tracks_initial_state_and_tasks():
    project = Project.from_dict(document())
    reordered = replace(project, parameters=ParameterSet(dict(reversed(list(project.parameters.entries.items())))))
    assert input_hash(reordered) == input_hash(project)
    raw = document()
    raw["tasks"][0]["demonstration"]["initial"]["mouse"][0] = -51
    assert input_hash(Project.from_dict(raw)) != input_hash(project)
    raw = document()
    raw["tasks"][0]["demonstration"]["steps"][1]["duration_s"] = 0.36
    assert input_hash(Project.from_dict(raw)) != input_hash(project)


@pytest.mark.parametrize("value", [-0.1, True, float("nan"), float("inf"), "2.4", None])
def test_override_rejects_invalid_values(value):
    with pytest.raises(ModelError, match=r"parameters\.think_s\.value"):
        parameters().override("think_s", value, source="test assumption")


@pytest.mark.parametrize("kwargs,match", [
    ({"name": "unknown", "value": 1, "source": "test"}, "unknown override"),
    ({"name": "think_s", "value": 1000, "unit": "ms", "source": "test"}, "think_s.unit"),
    ({"name": "think_s", "value": 1, "source": ""}, "think_s.source"),
    ({"name": "pixels_per_inch", "value": 0, "source": "test"}, "pixels_per_inch.value"),
    ({"name": "viewing_distance_in", "value": 0, "source": "test"}, "viewing_distance_in.value"),
])
def test_override_rejects_unknown_units_sources_or_nonpositive_geometry(kwargs, match):
    with pytest.raises(ModelError, match=match):
        parameters().override(**kwargs)


def test_nonoverridable_parameter_is_preserved_and_enforced():
    entries = dict(parameters().entries)
    entries["think_s"] = replace(entries["think_s"], overridable=False)
    immutable = ParameterSet(entries)
    with pytest.raises(ModelError, match="not overridable"):
        immutable.override("think_s", 2.4, source="test")
    assert ParameterSet.parse(immutable.input_dict(), 2).entries["think_s"].overridable is False


@pytest.mark.parametrize("field,value", [
    ("unit", "ms"), ("value", False), ("kind", "unverified_default"), ("source", []),
    ("scope", {}), ("overridable", 1), ("default_version", ""),
])
def test_direct_parameter_sets_reject_invalid_parameter_fields(field, value):
    entries = dict(parameters().entries)
    entries["think_s"] = replace(entries["think_s"], **{field: value})
    with pytest.raises(ModelError, match=rf"parameters\.think_s\.{field}"):
        ParameterSet(entries)


@pytest.mark.parametrize("entries", [None, [], {}, {"think_s": 1}, {1: Parameter(1, "s", "test", "modeler_supplied", "test")}])
def test_direct_parameter_sets_reject_invalid_mappings(entries):
    with pytest.raises(ModelError, match="parameters"):
        ParameterSet(entries)


def test_schema2_requires_all_effective_parameters_and_metadata():
    raw = Project.from_dict(document()).to_dict()
    raw["parameters"].pop("think_s")
    with pytest.raises(ModelError, match="parameters.*missing.*think_s"):
        Project.from_dict(raw)
    raw = Project.from_dict(document()).to_dict()
    raw["parameters"]["think_s"].pop("default_version")
    with pytest.raises(ModelError, match="parameters.think_s.*missing.*default_version"):
        Project.from_dict(raw)


def test_finite_negative_widget_and_mouse_coordinates_keep_values():
    project = Project.from_dict(document())
    assert project.design.frames[0].widgets[0].bounds == (-20, -30, 10, 10)
    assert project.tasks[0].demonstration.initial.mouse == (-50, -60)
    assert Project.from_dict(project.to_dict()) == project


def test_implementation_identity_is_separate_from_model_hash(monkeypatch):
    import cogtool_py
    project = Project.from_dict(document())
    original_hash = input_hash(project)
    identity = implementation_fingerprint()
    canonical = json.dumps(identity["files"], sort_keys=True, separators=(",", ":"))
    assert identity["sha256"] == hashlib.sha256(canonical.encode()).hexdigest()
    assert identity["files"]["models.py"] == hashlib.sha256((ROOT / "cogtool_py/models.py").read_bytes()).hexdigest()
    monkeypatch.setattr(cogtool_py, "__version__", "test-version-identity")
    assert implementation_fingerprint()["software_version"] == "test-version-identity"
    assert input_hash(project) == original_hash
    assert "implementation" not in project.to_dict()


def direct_integer_project() -> Project:
    """Build legal API objects with integers in every physical numeric field."""
    parsed = Project.from_dict(document())
    frame = parsed.design.frames[0]
    frame = replace(frame, widgets=(replace(frame.widgets[0], x=-20, y=-30, width=10, height=10),))
    second = replace(frame, id="second")
    design = replace(parsed.design, frames=(frame, second),
                     transitions=(Transition("go", "f", "w", "second", 2),))
    task = parsed.tasks[0]
    task = replace(task, demonstration=replace(task.demonstration,
        initial=replace(task.demonstration.initial, mouse=(-50, -60)),
        steps=(DemonstrationStep("click", target="w", transition="go"),
               DemonstrationStep("think", duration_s=1), DemonstrationStep("wait", duration_s=3))))
    return replace(parsed, design=design, tasks=(task,))


def test_direct_integer_fields_serialize_as_floats_and_preserve_identity(tmp_path):
    direct = direct_integer_project()
    serialized = direct.to_dict()
    for frame in serialized["design"]["frames"]:
        for widget in frame["widgets"]:
            assert all(type(widget[k]) is float for k in ("x", "y", "width", "height"))
    assert type(serialized["design"]["transitions"][0]["delay_s"]) is float
    demo = serialized["tasks"][0]["demonstration"]
    assert all(type(value) is float for value in demo["initial"]["mouse"])
    assert all(type(step["duration_s"]) is float for step in demo["steps"] if "duration_s" in step)
    restored = Project.from_dict(serialized)
    assert restored == direct
    assert input_hash(restored) == input_hash(direct)
    saved = tmp_path / "direct-integers.json"
    save_project(direct, saved)
    assert input_hash(load_project(saved)) == input_hash(direct)


def test_negative_zero_is_canonicalized_without_changing_values():
    positive = Project.from_dict(document())
    task = positive.tasks[0]
    demo = replace(task.demonstration, initial=replace(task.demonstration.initial, mouse=(0, 0)),
                   steps=(DemonstrationStep("wait", duration_s=0),))
    positive = replace(positive, tasks=(replace(task, demonstration=demo),),
                       parameters=positive.parameters.override("key_s", 0, source="zero duration assumption"))
    negative = replace(positive, tasks=(replace(task, demonstration=replace(demo,
        initial=replace(demo.initial, mouse=(-0.0, -0.0)),
        steps=(DemonstrationStep("wait", duration_s=-0.0),))),),
        parameters=positive.parameters.override("key_s", -0.0, source="zero duration assumption"))
    assert negative == positive
    assert input_hash(negative) == input_hash(positive)
    assert "-0.0" not in json.dumps(negative.to_dict())


@pytest.mark.parametrize("value", [True, "1", -1, float("nan"), float("inf")])
def test_numeric_serialization_does_not_repair_invalid_direct_durations(value):
    project = direct_integer_project()
    task = project.tasks[0]
    invalid = replace(project, tasks=(replace(task, demonstration=replace(task.demonstration,
        steps=(DemonstrationStep("wait", duration_s=value),))),))
    with pytest.raises(ModelError, match=r"task\[t\]\.steps\[0\]\.duration_s"):
        invalid.to_dict()
    with pytest.raises(ModelError, match=r"task\[t\]\.steps\[0\]\.duration_s"):
        input_hash(invalid)


@pytest.mark.integration
def test_direct_integer_api_and_float_json_cli_predictions_have_identical_identity(tmp_path):
    direct = direct_integer_project()
    source = tmp_path / "integer-api.json"
    save_project(direct, source)
    restored = load_project(source)
    output = tmp_path / "cli-output"
    completed = subprocess.run([sys.executable, "-m", "cogtool_py", "predict", str(source), "--out", str(output)],
                               cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    api = predict(direct).to_dict()
    json_api = predict(restored).to_dict()
    cli = read_json(output / "result.json")
    # JSON represents the initial mouse tuple as an array; wall time varies.
    def stable_json(value):
        return json.loads(json.dumps({k: v for k, v in value.items() if k != "program_runtime_s"}))
    assert stable_json(api) == stable_json(json_api) == stable_json(cli)
    assert api["input_sha256"] == json_api["input_sha256"] == cli["input_sha256"] == input_hash(direct)
    roundtrip = tmp_path / "roundtrip.json"
    completed = subprocess.run([sys.executable, "-m", "cogtool_py", "roundtrip", str(source), "--out", str(roundtrip)],
                               cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    assert input_hash(load_project(roundtrip)) == input_hash(direct)


@pytest.mark.integration
def test_api_json_cli_use_identical_effective_overrides(tmp_path):
    project = Project.from_dict(document())
    project = replace(project, parameters=project.parameters.override("think_s", 2.4, source="CLI consistency test"))
    input_path = tmp_path / "input.json"
    save_project(project, input_path)
    output = tmp_path / "output"
    completed = subprocess.run([sys.executable, "-m", "cogtool_py", "predict", str(input_path), "--out", str(output)],
                               cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    cli_data = read_json(output / "result.json")
    api_data = predict(project).to_dict()
    for key in ("parameters", "input_sha256", "predicted_time_s", "steps", "events"):
        assert cli_data[key] == api_data[key]
    saved = tmp_path / "roundtrip.json"
    completed = subprocess.run([sys.executable, "-m", "cogtool_py", "roundtrip", str(input_path), "--out", str(saved)],
                               cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    assert read_json(saved)["parameters"] == project.parameters.input_dict()
    assert input_hash(load_project(saved)) == input_hash(project)

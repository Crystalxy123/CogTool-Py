"""Self-contained installed-package tests; no scripts or historical run paths."""
from copy import deepcopy
from importlib.resources import files
import json
from pathlib import Path

import pytest

import cogtool_py.benchmark as benchmark
from cogtool_py.engine import predict
from cogtool_py.io import input_hash, load_project, read_json, write_json
from cogtool_py.models import ModelError


@pytest.fixture
def fixture_manifest(tmp_path):
    """Fresh self-authored baseline fixture, not an upstream reference answer."""
    base = tmp_path / "fixtures"
    base.mkdir()
    input_path = base / "input.json"
    input_path.write_bytes(files("cogtool_py").joinpath("resources", "single_click.json").read_bytes())
    project = load_project(input_path)
    expected = predict(project).to_dict()
    write_json(base / "expected.json", expected)
    reference = base / "synthetic_reference.txt"
    reference.write_text("self-authored test provenance only; no upstream computation\n")
    case = {
        "case_id": "self-authored", "task_id": project.tasks[0].id,
        "role": benchmark.COMPARISON_KIND,
        "input": {"path": "input.json", "sha256": benchmark.file_sha256(input_path)},
        "expected": {"path": "expected.json", "sha256": benchmark.file_sha256(base / "expected.json")},
        "effective_input_sha256": input_hash(project),
        "parameters_sha256": benchmark.canonical_sha256(project.to_dict()["parameters"]),
        "control_sha256": benchmark.canonical_sha256(None),
        "engine": expected["engine"], "scope": None, "run_policy": None,
        "expected_status": "baseline_complete", "source_model": {"kind": "self_authored", "sha256": benchmark.file_sha256(input_path)},
        "limitations": ["test fixture, not an original reference"],
        "references": [{"path": reference.name, "sha256": benchmark.file_sha256(reference)}],
    }
    manifest = {"manifest_version": 1, "comparison": {
        "kind": benchmark.COMPARISON_KIND, "numeric_policy": "exact_json",
        "exclude_top_level_fields": list(benchmark.EXCLUDED_TOP_LEVEL_FIELDS)}, "cases": [case]}
    path = base / "manifest.json"
    write_json(path, manifest)
    return path, manifest


def forbid_prediction(*args, **kwargs):
    pytest.fail("invalid evidence must be rejected before prediction")


def test_benchmark_recomputes_exports_complete_result_without_expected_input(fixture_manifest, tmp_path, monkeypatch):
    path, manifest = fixture_manifest
    seen = []

    def observe(project, task_id):
        seen.append((input_hash(project), task_id))
        return predict(project, task_id)

    monkeypatch.setattr(benchmark, "predict", observe)
    out = tmp_path / "output"
    report = benchmark.run_benchmarks(path, out)
    assert report["status"] == "PASS" and report["passed"] and report["exit_code"] == 0
    assert report["case_count"] == report["pass_count"] == 1
    assert seen == [(manifest["cases"][0]["effective_input_sha256"], manifest["cases"][0]["task_id"])]
    actual = read_json(out / "cases/self-authored/result.json")
    expected = read_json(path.parent / "expected.json")
    assert actual["steps"] == expected["steps"] and actual["events"] == expected["events"]
    assert "distribution_identity" in actual
    assert (out / "cases/self-authored/events.csv").is_file()
    assert (out / "cases/self-authored/steps.csv").is_file()
    assert read_json(out / "summary.json")["original_program_equivalence"] is None


@pytest.mark.parametrize("artifact", ["input.json", "expected.json", "synthetic_reference.txt"])
def test_changed_file_hash_fails_before_prediction(fixture_manifest, tmp_path, monkeypatch, artifact):
    path, _ = fixture_manifest
    with (path.parent / artifact).open("ab") as file:
        file.write(b"\n")
    monkeypatch.setattr(benchmark, "predict", forbid_prediction)
    report = benchmark.run_benchmarks(path, tmp_path / "out")
    assert report["status"] == "FAIL" and report["exit_code"] == 4
    assert not report["cases"][0]["prediction_executed"]
    assert "sha256" in report["cases"][0]["error"]["message"]


@pytest.mark.parametrize("field,value", [
    ("effective_input_sha256", "0" * 64), ("parameters_sha256", "0" * 64),
    ("control_sha256", "0" * 64), ("scope", "integrated_task"),
    ("run_policy", "reference_2014"), ("task_id", "wrong-task"),
    ("engine", {"name": "klm_baseline", "version": "not-frozen-version"}),
])
def test_configuration_identity_never_silently_falls_back(fixture_manifest, tmp_path, monkeypatch, field, value):
    path, manifest = fixture_manifest
    manifest["cases"][0][field] = value
    write_json(path, manifest)
    monkeypatch.setattr(benchmark, "predict", forbid_prediction)
    report = benchmark.run_benchmarks(path, tmp_path / "out")
    assert report["status"] == "FAIL" and not report["cases"][0]["prediction_executed"]
    assert "mismatch" in report["cases"][0]["error"]["message"]


def test_changed_expected_event_fails_despite_unchanged_total(fixture_manifest, tmp_path):
    path, manifest = fixture_manifest
    expected_path = path.parent / "expected.json"
    expected = read_json(expected_path)
    expected["events"][0]["origin"] = "fabricated-origin"
    write_json(expected_path, expected)
    manifest["cases"][0]["expected"]["sha256"] = benchmark.file_sha256(expected_path)
    write_json(path, manifest)
    report = benchmark.run_benchmarks(path, tmp_path / "out")
    assert report["status"] == "FAIL" and report["cases"][0]["prediction_executed"]
    assert any(x["path"] == "/events/0/origin" for x in report["cases"][0]["differences"])
    actual = read_json(tmp_path / "out/cases/self-authored/result.json")
    assert actual["predicted_time_s"] == expected["predicted_time_s"]


@pytest.mark.parametrize("field", ["events", "motor_events", "vision_events", "motor_state_changes", "vision_state_changes", "steps", "compiled_productions"])
def test_comparison_retains_all_event_and_rule_lists_in_original_order(field):
    # Deliberately synthetic JSON exercises comparator structure, not a claim
    # that these markers or times came from any original model.
    expected = {"predicted_time_s": 1.0, field: [{"marker": "a"}, {"marker": "b"}]}
    swapped = deepcopy(expected)
    swapped[field].reverse()
    missing = deepcopy(expected)
    missing[field].pop()
    assert benchmark.compare_complete_json(expected, swapped)
    assert benchmark.compare_complete_json(expected, missing)


def test_only_five_top_level_fields_are_excluded_and_reported(fixture_manifest, tmp_path):
    path, manifest = fixture_manifest
    expected_path = path.parent / "expected.json"
    expected = read_json(expected_path)
    for field in benchmark.EXCLUDED_TOP_LEVEL_FIELDS:
        expected[field] = {"old": "explicitly-excluded-metadata"}
    write_json(expected_path, expected)
    manifest["cases"][0]["expected"]["sha256"] = benchmark.file_sha256(expected_path)
    write_json(path, manifest)
    report = benchmark.run_benchmarks(path, tmp_path / "out")
    assert report["passed"]
    assert set(report["cases"][0]["excluded_top_level_values"]) == set(benchmark.EXCLUDED_TOP_LEVEL_FIELDS)
    assert benchmark.compare_complete_json({"events": [{"program_runtime_s": 1}]}, {"events": [{"program_runtime_s": 2}]})
    assert benchmark.compare_complete_json({"engine": {"version": "1"}}, {"engine": {"version": "2"}})
    assert benchmark.compare_complete_json({"x": True}, {"x": 1})


@pytest.mark.parametrize("bad_path", ["../input.json", "/tmp/input.json", "C:\\Users\\input.json"])
def test_manifest_rejects_nonrelative_paths_before_creating_output(fixture_manifest, tmp_path, bad_path):
    path, manifest = fixture_manifest
    manifest["cases"][0]["input"]["path"] = bad_path
    write_json(path, manifest)
    with pytest.raises(ModelError):
        benchmark.run_benchmarks(path, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_symlink_cannot_escape_bundle(fixture_manifest, tmp_path):
    path, manifest = fixture_manifest
    external = tmp_path / "outside.json"
    external.write_bytes((path.parent / "input.json").read_bytes())
    (path.parent / "linked.json").symlink_to(external)
    manifest["cases"][0]["input"]["path"] = "linked.json"
    write_json(path, manifest)
    with pytest.raises(ModelError, match="outside"):
        benchmark.run_benchmarks(path, tmp_path / "out")


@pytest.mark.parametrize("mutation", ["ignore-more", "duplicate-case", "invalid-sha", "wrong-policy", "empty"])
def test_invalid_manifest_is_not_a_success(fixture_manifest, tmp_path, mutation):
    path, manifest = fixture_manifest
    if mutation == "ignore-more":
        manifest["comparison"]["exclude_top_level_fields"].append("events")
    elif mutation == "duplicate-case":
        manifest["cases"].append(deepcopy(manifest["cases"][0]))
    elif mutation == "invalid-sha":
        manifest["cases"][0]["expected"]["sha256"] = "invalid"
    elif mutation == "wrong-policy":
        manifest["comparison"]["numeric_policy"] = "round_to_same_total"
    else:
        manifest["cases"] = []
    write_json(path, manifest)
    with pytest.raises(ModelError):
        benchmark.run_benchmarks(path, tmp_path / "out")


def test_refuse_overwrite_keeps_previous_evidence(fixture_manifest, tmp_path):
    path, _ = fixture_manifest
    out = tmp_path / "out"
    benchmark.run_benchmarks(path, out)
    before = benchmark.file_sha256(out / "summary.json")
    with pytest.raises(ModelError, match="already exists"):
        benchmark.run_benchmarks(path, out)
    assert benchmark.file_sha256(out / "summary.json") == before


def test_partial_or_null_expected_is_never_accepted_as_complete(fixture_manifest, tmp_path, monkeypatch):
    path, manifest = fixture_manifest
    expected_path = path.parent / "expected.json"
    expected = read_json(expected_path)
    expected["predicted_time_s"] = None
    write_json(expected_path, expected)
    manifest["cases"][0]["expected"]["sha256"] = benchmark.file_sha256(expected_path)
    write_json(path, manifest)
    monkeypatch.setattr(benchmark, "predict", forbid_prediction)
    report = benchmark.run_benchmarks(path, tmp_path / "out")
    assert not report["passed"] and not report["cases"][0]["prediction_executed"]


def test_prediction_exception_is_retained_as_failure(fixture_manifest, tmp_path, monkeypatch):
    path, _ = fixture_manifest

    def broken(*args):
        raise ModelError("intentional self-authored test blocker")

    monkeypatch.setattr(benchmark, "predict", broken)
    report = benchmark.run_benchmarks(path, tmp_path / "out")
    assert report["exit_code"] == 4
    assert report["cases"][0]["error"]["message"] == "intentional self-authored test blocker"
    assert read_json(tmp_path / "out/summary.json")["fail_count"] == 1

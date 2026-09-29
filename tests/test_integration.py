"""Python-only integration/regression evidence, never original CogTool output."""
from __future__ import annotations

from copy import deepcopy
import csv
import json
from pathlib import Path
import subprocess
import sys

import pytest

from cogtool_py import UPSTREAM, __version__
from cogtool_py.engine import predict
from cogtool_py.io import export_result, input_hash, load_project, read_json, save_project
from cogtool_py.models import ModelError, Project


pytestmark = pytest.mark.integration
WORKSPACE = Path(__file__).resolve().parents[1]


def document() -> dict:
    """Self-contained two-page fixture with hand-computable explicit wait."""
    return {
        "schema_version": 1, "id": "integration-fixture", "name": "集成示例", "engine": "klm_baseline",
        "parameters": {
            key: {"value": value, "unit": "s", "source": "test assumption, not empirical or original CogTool"}
            for key, value in (("click_s", 0.2), ("key_s", 0.1), ("homing_s", 0.4))
        },
        "design": {
            "id": "design", "name": "测试设计", "coordinate_unit": "px",
            "frames": [
                {"id": "first", "name": "首页", "widgets": [
                    {"id": "next", "name": "next", "label": "下一页", "kind": "button",
                     "x": 80, "y": 60, "width": 40, "height": 20},
                ]},
                {"id": "second", "name": "第二页", "widgets": [
                    {"id": "field", "name": "field", "label": "名称", "kind": "textbox",
                     "x": 10, "y": 10, "width": 100, "height": 20},
                ]},
            ],
            "transitions": [{"id": "go", "from_frame": "first", "target": "next", "to_frame": "second", "delay_s": 0.5}],
        },
        "tasks": [{"id": "task", "name": "打开页面并输入", "demonstration": {
            "initial": {"frame": "first", "mouse": [0, 0], "mouse_hand": "right", "hand": "mouse", "focus": None},
            "steps": [{"op": "click", "target": "next", "transition": "go"},
                      {"op": "click", "target": "field"}, {"op": "keys", "keys": ["h", "i"]}],
        }}],
    }


def write_input(tmp_path: Path, value: dict | None = None) -> Path:
    path = tmp_path / "模型.json"
    path.write_text(json.dumps(document() if value is None else value, ensure_ascii=False), encoding="utf-8")
    return path


def cli(*args: str | Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "cogtool_py", *map(str, args)],
                          cwd=WORKSPACE, capture_output=True, text=True, timeout=20)


def test_json_save_load_roundtrip_keeps_model_and_semantic_hash(tmp_path):
    source = write_input(tmp_path)
    project = load_project(source)
    original_hash = input_hash(project)
    saved = tmp_path / "nested" / "保存.json"
    save_project(project, saved)
    restored = load_project(saved)
    assert restored == project
    assert input_hash(restored) == original_hash
    assert len(original_hash) == 64
    # Version 2 persists all effective parameters and provenance; v1 remains readable.
    assert read_json(saved)["schema_version"] == 2
    assert "集成示例" in saved.read_text(encoding="utf-8")


def test_hash_tracks_semantics_and_ignores_json_layout(tmp_path):
    raw = document()
    first = write_input(tmp_path, raw)
    second = tmp_path / "reordered.json"
    second.write_text(json.dumps(raw, sort_keys=True, indent=4), encoding="utf-8")
    assert input_hash(load_project(first)) == input_hash(load_project(second))
    raw["parameters"]["click_s"]["value"] = 0.3
    changed = Project.from_dict(raw)
    assert input_hash(changed) != input_hash(load_project(first))


def test_pipeline_exports_complete_consistent_json_and_csv(tmp_path):
    project = load_project(write_input(tmp_path))
    result = predict(project)
    result_path, events_path, steps_path = export_result(result, tmp_path / "result")
    data = read_json(result_path)
    # JSON represents all sequences as arrays, including the initial mouse tuple.
    assert data == json.loads(json.dumps(result.to_dict(), allow_nan=False))
    assert data["software_version"] == __version__
    assert data["engine"]["name"] == "klm_baseline"
    assert data["upstream"] == UPSTREAM
    assert data["input_sha256"] == input_hash(project)
    assert data["validation"]["original_comparison"] == "unverified"
    assert data["validation"]["differential_tests"] == "not_executed"
    assert data["time_unit"] == "s"
    assert data["program_runtime_s"] >= 0
    assert data["warnings"]
    assert data["final_state"]["frame"] == "second"
    assert data["final_state"]["focus"] == "field"
    assert data["final_state"]["hand"] == "keyboard"
    assert data["demonstration"] == document()["tasks"][0]["demonstration"]["steps"]

    with events_path.open(encoding="utf-8", newline="") as handle:
        event_rows = list(csv.DictReader(handle))
    with steps_path.open(encoding="utf-8", newline="") as handle:
        step_rows = list(csv.DictReader(handle))
    assert len(event_rows) == len(data["events"]) == len(step_rows) == len(data["steps"])
    assert {row["origin"] for row in step_rows} == {"automatic", "demonstrated"}
    assert all(row["source"] for row in step_rows)
    assert all(p["unit"] and p["source"] and p["scope"] for p in data["parameters"].values())

    # Invariants inspect the independently exported records; no timing function is re-used.
    assert float(event_rows[0]["start_s"]) == 0.0
    for index, row in enumerate(event_rows):
        start, end, duration = map(float, (row["start_s"], row["end_s"], row["duration_s"]))
        assert end >= start
        assert end - start == pytest.approx(duration, abs=1e-12)
        assert row["op"] == step_rows[index]["op"]
        assert row["demo_index"] == step_rows[index]["demo_index"]
        if index:
            assert start == float(event_rows[index - 1]["end_s"])
    assert data["predicted_time_s"] == float(event_rows[-1]["end_s"])
    wait = [row for row in event_rows if row["op"] == "wait"]
    assert len(wait) == 1 and float(wait[0]["duration_s"]) == 0.5


def test_prediction_is_repeatable_excluding_actual_program_runtime(tmp_path):
    project = load_project(write_input(tmp_path))
    first, second = deepcopy(predict(project).to_dict()), deepcopy(predict(project).to_dict())
    first.pop("program_runtime_s")
    second.pop("program_runtime_s")
    assert first == second


def test_model_text_is_inert_and_never_executed(tmp_path):
    marker = tmp_path / "must-not-be-created"
    raw = document()
    raw["design"]["frames"][0]["widgets"][0]["label"] = (
        f"__import__('pathlib').Path({str(marker)!r}).touch()"
    )
    project = load_project(write_input(tmp_path, raw))
    assert predict(project).to_dict()["predicted_time_s"] > 0
    assert not marker.exists()


def test_cli_validate_predict_and_roundtrip(tmp_path):
    path = write_input(tmp_path)
    validation = cli("validate", path)
    assert validation.returncode == 0, validation.stderr
    assert "valid: integration-fixture" in validation.stdout
    assert "klm_baseline" in validation.stdout

    out_dir = tmp_path / "output with spaces"
    prediction = cli("predict", path, "--out", out_dir)
    assert prediction.returncode == 0, prediction.stderr
    assert "original comparison=unverified" in prediction.stdout
    assert {p.name for p in out_dir.iterdir()} == {"result.json", "events.csv", "steps.csv"}
    assert read_json(out_dir / "result.json")["input_sha256"] == input_hash(load_project(path))

    saved = tmp_path / "roundtrip" / "restored.json"
    roundtrip = cli("roundtrip", path, "--out", saved)
    assert roundtrip.returncode == 0, roundtrip.stderr
    assert "roundtrip verified" in roundtrip.stdout
    assert input_hash(load_project(saved)) == input_hash(load_project(path))


@pytest.mark.parametrize("example", ["single_click", "text_entry", "two_page_wait"])
def test_shipped_examples_run_through_documented_cli(example, tmp_path):
    path = WORKSPACE / "examples" / f"{example}.json"
    check = cli("validate", path)
    assert check.returncode == 0, check.stderr
    output = tmp_path / example
    result = cli("predict", path, "--out", output)
    assert result.returncode == 0, result.stderr
    data = read_json(output / "result.json")
    assert data["predicted_time_s"] >= 0
    assert data["validation"]["original_comparison"] == "unverified"
    assert (output / "events.csv").is_file() and (output / "steps.csv").is_file()


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonstandard_json_numeric_constants_are_rejected(constant, tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text('{"value": ' + constant + '}', encoding="utf-8")
    with pytest.raises(ModelError, match="non-finite JSON constant"):
        read_json(path)


def test_json_exponent_overflow_reports_actual_model_field(tmp_path):
    path = write_input(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").replace('"value": 0.2', '"value": 1e309', 1), encoding="utf-8")
    with pytest.raises(ModelError, match=r"parameters\.click_s\.value"):
        load_project(path)
    output = tmp_path / "must-not-exist"
    result = cli("predict", path, "--out", output)
    assert result.returncode == 2
    assert "parameters.click_s.value" in result.stderr
    assert "Traceback" not in result.stderr
    assert not output.exists()


def test_finite_inputs_with_overflowing_derived_geometry_fail_with_step_context(tmp_path):
    raw = document()
    raw["design"]["frames"][0]["widgets"][0]["x"] = 1e308
    raw["design"]["frames"][0]["widgets"][0]["width"] = 1e308
    project = load_project(write_input(tmp_path, raw))
    with pytest.raises(ModelError, match=r"task\[task\]\.steps\[0\]\.point"):
        predict(project)


def test_duration_accumulation_overflow_is_not_exported_as_infinity(tmp_path):
    raw = document()
    raw["tasks"][0]["demonstration"]["steps"] = [{"op": "wait", "duration_s": 1e308}] * 2
    project = load_project(write_input(tmp_path, raw))
    with pytest.raises(ModelError, match=r"task\[task\]\.steps\[1\].*out of range"):
        predict(project)


@pytest.mark.parametrize("text", ['{"id": 1, "id": 2}', '{"outer": {"x": 1, "x": 2}}'])
def test_duplicate_json_fields_are_rejected(text, tmp_path):
    path = tmp_path / "duplicate.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ModelError, match="duplicate JSON field"):
        read_json(path)


@pytest.mark.parametrize("text", ["not json", '{"missing":', "[" * 1500 + "]" * 1500])
def test_malformed_or_excessively_nested_json_is_controlled_error(text, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ModelError, match="bad.json"):
        load_project(path)


def test_invalid_utf8_is_controlled_error(tmp_path):
    path = tmp_path / "encoding.json"
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(ModelError, match="encoding.json"):
        load_project(path)


def test_excessive_integer_literal_is_controlled_error(tmp_path):
    path = tmp_path / "huge-integer.json"
    path.write_text('{"schema_version": ' + "9" * 5000 + "}", encoding="utf-8")
    with pytest.raises(ModelError, match="huge-integer.json"):
        load_project(path)


def test_missing_input_is_controlled_cli_error(tmp_path):
    result = cli("validate", tmp_path / "missing.json")
    assert result.returncode == 2
    assert "missing.json" in result.stderr
    assert "Traceback" not in result.stderr


def test_multiple_tasks_require_explicit_selection(tmp_path):
    raw = document()
    other = deepcopy(raw["tasks"][0])
    other["id"] = "other"
    raw["tasks"].append(other)
    path = write_input(tmp_path, raw)
    rejected = cli("predict", path, "--out", tmp_path / "rejected")
    assert rejected.returncode == 2
    assert "explicitly select --task" in rejected.stderr
    chosen = cli("predict", path, "--task", "other", "--out", tmp_path / "chosen")
    assert chosen.returncode == 0, chosen.stderr
    assert read_json(tmp_path / "chosen" / "result.json")["task_id"] == "other"
    unknown = cli("predict", path, "--task", "missing", "--out", tmp_path / "unknown")
    assert unknown.returncode == 2
    assert "unknown task" in unknown.stderr


def test_invalid_later_task_prevents_partial_first_task_export(tmp_path):
    raw = document()
    other = deepcopy(raw["tasks"][0])
    other["id"] = "bad"
    other["demonstration"]["steps"] = [{"op": "click", "target": "missing"}]
    raw["tasks"].append(other)
    path = write_input(tmp_path, raw)
    output = tmp_path / "rejected"
    result = cli("predict", path, "--task", "task", "--out", output)
    assert result.returncode == 2
    assert "task[bad].steps[0].target" in result.stderr
    assert not output.exists()

"""Offline, exact replay of externally frozen Python regression fixtures.

Expected results are read only by the comparator, never by the predictor. A
PASS is software regression evidence, not equivalence to the original CogTool.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from .engine import predict
from .io import export_result, input_hash, load_project, read_json, write_json
from .models import ModelError


EXCLUDED_TOP_LEVEL_FIELDS = (
    "program_runtime_s", "software_version", "implementation",
    "execution_fingerprint", "distribution_identity",
)
COMPARISON_KIND = "frozen_python_regression"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


def canonical_sha256(value: Any) -> str:
    """Identity of a JSON value; list order and complete parameter metadata count."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _error(context: str, message: str) -> None:
    raise ModelError(f"benchmark {context}: {message}")


def _relative_file(base: Path, value: Any, context: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        _error(context, "file path must be a nonempty relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or ":" in value:
        _error(context, "absolute paths and parent traversal are forbidden")
    resolved = (base / value).resolve()
    if not resolved.is_relative_to(base.resolve()):
        _error(context, "file resolves outside manifest directory")
    return resolved


def _file_record(base: Path, record: Any, context: str) -> Path:
    if not isinstance(record, dict):
        _error(context, "must be an object with path and sha256")
    if not isinstance(record.get("sha256"), str) or not _SHA.fullmatch(record["sha256"]):
        _error(context, "sha256 must be a lowercase 64-character digest")
    return _relative_file(base, record.get("path"), context)


def _validate_manifest(manifest: Any, base: Path) -> list[dict]:
    if not isinstance(manifest, dict) or type(manifest.get("manifest_version")) is not int or manifest["manifest_version"] != 1:
        _error("manifest", "manifest_version must be 1")
    comparison = manifest.get("comparison")
    if not isinstance(comparison, dict) or comparison.get("kind") != COMPARISON_KIND:
        _error("manifest", "comparison kind must be frozen_python_regression")
    if comparison.get("numeric_policy") != "exact_json":
        _error("manifest", "numeric_policy must be exact_json")
    if comparison.get("exclude_top_level_fields") != list(EXCLUDED_TOP_LEVEL_FIELDS):
        _error("manifest", "only the fixed five top-level identity/runtime fields may be excluded")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        _error("manifest", "cases must be a nonempty list")
    seen: set[str] = set()
    for index, case in enumerate(cases):
        context = f"cases[{index}]"
        if not isinstance(case, dict):
            _error(context, "case must be an object")
        cid = case.get("case_id")
        if not isinstance(cid, str) or not _CASE.fullmatch(cid) or cid in seen:
            _error(context, "case_id must be a unique safe identifier")
        seen.add(cid)
        for field in ("input", "expected"):
            _file_record(base, case.get(field), f"{context}.{field}")
        for field in ("effective_input_sha256", "parameters_sha256", "control_sha256"):
            if not isinstance(case.get(field), str) or not _SHA.fullmatch(case[field]):
                _error(context, f"{field} must be a sha256 digest")
        if not isinstance(case.get("task_id"), str) or not case["task_id"]:
            _error(context, "task_id must be nonempty")
        engine = case.get("engine")
        if not isinstance(engine, dict) or set(engine) != {"name", "version"} or not all(isinstance(v, str) and v for v in engine.values()):
            _error(context, "engine must contain nonempty name and version")
        if "scope" not in case or case["scope"] not in (None, "integrated_task"):
            _error(context, "scope must explicitly be null or integrated_task")
        if "run_policy" not in case or case["run_policy"] not in (None, "legacy_bounded", "reference_2014"):
            _error(context, "run_policy must explicitly name the policy (or null for baseline)")
        if case.get("expected_status") not in ("complete", "baseline_complete"):
            _error(context, "expected_status must be complete or baseline_complete")
        if case.get("role") != COMPARISON_KIND:
            _error(context, "role must explicitly be frozen_python_regression")
        source_model = case.get("source_model")
        if (not isinstance(source_model, dict) or not isinstance(source_model.get("kind"), str)
                or not source_model["kind"] or not isinstance(source_model.get("sha256"), str)
                or not _SHA.fullmatch(source_model["sha256"])):
            _error(context, "source_model requires a kind and sha256 provenance identity")
        if not isinstance(case.get("limitations"), list) or not all(isinstance(x, str) for x in case["limitations"]):
            _error(context, "limitations must be a list of provenance statements")
        refs = case.get("references")
        if not isinstance(refs, list):
            _error(context, "references must be a list (possibly empty)")
        for i, ref in enumerate(refs):
            _file_record(base, ref, f"{context}.references[{i}]")
    return cases


def _pointer(parent: str, key: Any) -> str:
    return parent + "/" + str(key).replace("~", "~0").replace("/", "~1")


def compare_complete_json(expected: Any, actual: Any) -> list[dict]:
    """Exact JSON-value diff, retaining list order and every nonexcluded field.

    JSON numbers compare numerically (1 equals 1.0); booleans are not numbers.
    Ignoring fields applies only at the result root, never nested objects.
    """
    differences: list[dict] = []

    def visit(left: Any, right: Any, pointer: str) -> None:
        if isinstance(left, dict) and isinstance(right, dict):
            keys = sorted(set(left) | set(right))
            for key in keys:
                if not pointer and key in EXCLUDED_TOP_LEVEL_FIELDS:
                    continue
                path = _pointer(pointer, key)
                if key not in left or key not in right:
                    differences.append({"path": path, "kind": "missing_field",
                                        "expected_present": key in left, "actual_present": key in right,
                                        "expected": left.get(key), "actual": right.get(key)})
                else:
                    visit(left[key], right[key], path)
        elif isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                differences.append({"path": pointer, "kind": "list_length", "expected": len(left), "actual": len(right)})
            for i in range(max(len(left), len(right))):
                if i >= len(left) or i >= len(right):
                    differences.append({"path": _pointer(pointer, i), "kind": "missing_item",
                                        "expected_present": i < len(left), "actual_present": i < len(right),
                                        "expected": left[i] if i < len(left) else None,
                                        "actual": right[i] if i < len(right) else None})
                else:
                    visit(left[i], right[i], _pointer(pointer, i))
        else:
            numeric = type(left) in (int, float) and type(right) in (int, float)
            if (type(left) is not type(right) and not numeric) or left != right:
                differences.append({"path": pointer, "kind": "value", "expected": left, "actual": right})

    visit(expected, actual, "")
    return differences


def _check_equal(actual: Any, expected: Any, context: str) -> None:
    if actual != expected:
        _error(context, f"identity/configuration mismatch: expected {expected!r}, got {actual!r}")


def _check_complete(result: dict, expected_status: str, context: str) -> None:
    if expected_status == "complete":
        _check_equal(result.get("completion_status"), "complete", context + ".completion_status")
    elif result.get("engine", {}).get("name") != "klm_baseline":
        _error(context, "baseline_complete requires klm_baseline")
    value = result.get("predicted_time_s")
    if type(value) not in (int, float) or value < 0:
        _error(context, "a complete benchmark must have a nonnegative predicted_time_s")


def run_benchmarks(manifest_path: str | Path, out: str | Path) -> dict:
    """Validate, recompute, export and compare; no reference runtime is invoked.

    Malformed manifests or an existing destination raise ModelError. A valid
    manifest with a hash/configuration/calculation failure returns FAIL and
    exit_code 4, saves the error, and continues other independent cases.
    """
    manifest_path, out = Path(manifest_path), Path(out)
    manifest = read_json(manifest_path)
    cases = _validate_manifest(manifest, manifest_path.parent)
    if out.exists():
        _error("output", "destination already exists; refusing to replace evidence")
    out.mkdir(parents=True)
    write_json(out / "manifest_used.json", manifest)
    records = []
    for case in cases:
        cid = case["case_id"]
        directory = out / "cases" / cid
        directory.mkdir(parents=True)
        record: dict[str, Any] = {"case_id": cid, "status": "FAIL", "prediction_executed": False,
                                  "differences": [], "error": None}
        try:
            for label, ref in [("input", case["input"]), ("expected", case["expected"])] + [
                (f"reference[{i}]", value) for i, value in enumerate(case["references"])
            ]:
                path = _relative_file(manifest_path.parent, ref["path"], label)
                _check_equal(file_sha256(path), ref["sha256"], f"{cid}.{label}.sha256")
            input_path = _relative_file(manifest_path.parent, case["input"]["path"], "input")
            expected = read_json(_relative_file(manifest_path.parent, case["expected"]["path"], "expected"))
            if not isinstance(expected, dict):
                _error(cid, "expected result must be an object")
            project = load_project(input_path)
            model = project.to_dict()
            scope = project.control.execution_scope if project.control is not None else None
            policy = project.control.run_policy if project.control is not None else None
            for label, actual, wanted in (
                ("input_sha256", input_hash(project), case["effective_input_sha256"]),
                ("parameters_sha256", canonical_sha256(model["parameters"]), case["parameters_sha256"]),
                ("control_sha256", canonical_sha256(model.get("control")), case["control_sha256"]),
                ("engine.name", project.engine, case["engine"]["name"]),
                ("scope", scope, case["scope"]), ("run_policy", policy, case["run_policy"]),
                ("expected.engine", expected.get("engine"), case["engine"]),
                ("expected.task_id", expected.get("task_id"), case["task_id"]),
                ("expected.input_sha256", expected.get("input_sha256"), case["effective_input_sha256"]),
                ("expected.parameters_sha256", canonical_sha256(expected.get("parameters")), case["parameters_sha256"]),
                ("expected.scope", expected.get("execution_scope"), case["scope"]),
                ("expected.run_policy", (expected.get("runtime_policy") or {}).get("run_policy"), case["run_policy"]),
            ):
                _check_equal(actual, wanted, f"{cid}.{label}")
            _check_complete(expected, case["expected_status"], f"{cid}.expected")
            # The predictor receives only the validated project and selected task.
            record["prediction_executed"] = True
            result = predict(project, case["task_id"])
            result_path, _, _ = export_result(result, directory)
            actual = read_json(result_path)
            record["result_path"] = str(result_path.relative_to(out))
            record["result_sha256"] = file_sha256(result_path)
            record["excluded_top_level_values"] = {
                field: {"expected_present": field in expected, "actual_present": field in actual,
                        "expected": expected.get(field), "actual": actual.get(field)}
                for field in EXCLUDED_TOP_LEVEL_FIELDS
            }
            record["differences"] = compare_complete_json(expected, actual)
            _check_complete(actual, case["expected_status"], f"{cid}.actual")
            record["status"] = "FAIL" if record["differences"] else "PASS"
        except (ModelError, OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            record["error"] = {"type": type(exc).__name__, "message": str(exc)}
        write_json(directory / "comparison.json", record)
        records.append(record)
    failures = [x["case_id"] for x in records if x["status"] != "PASS"]
    summary = {"benchmark_schema_version": 1, "status": "FAIL" if failures else "PASS",
               "passed": not failures, "exit_code": 4 if failures else 0,
               "manifest_sha256": file_sha256(manifest_path),
               "comparison_kind": COMPARISON_KIND, "numeric_policy": "exact_json",
               "excluded_top_level_fields": list(EXCLUDED_TOP_LEVEL_FIELDS),
               "case_count": len(records), "pass_count": len(records) - len(failures),
               "fail_count": len(failures), "failures": failures, "cases": records,
               "original_program_equivalence": None,
               "claim": "Frozen Python software regression only; saved J-L references are hashed provenance, not recomputed by this command."}
    write_json(out / "summary.json", summary)
    return summary

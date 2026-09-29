"""Verify evidence files and report field-level differences, never full equivalence.

Synthetic bundles exercise this mechanism only. Hashes establish file integrity,
not the historical truth of a claimed original run; a human must audit provenance.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from . import UPSTREAM, UPSTREAM_COMMIT
from .models import ModelError

ABS_TOLERANCE_S = 1e-9
_REQUIRED_FILES = frozenset({
    "original_input", "configuration", "generated_steps", "raw_trace",
    "run_instructions", "runtime_identity", "normalized_result",
})
_HEX = re.compile(r"[0-9a-f]{64}\Z")


class EvidenceError(ModelError):
    """Missing, malformed, unsafe, or mismatched comparison evidence."""


def _error(path: str, message: str) -> None:
    raise EvidenceError(f"{path}: {message}")


def _reject_constant(value: str) -> None:
    raise EvidenceError(f"non-finite JSON constant: {value}")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        _error("JSON", "floating-point value overflows finite range")
    return parsed


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            _error(key, "duplicate JSON key")
        result[key] = value
    return result


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"),
                          parse_constant=_reject_constant,
                          parse_float=_finite_float,
                          object_pairs_hook=_unique_object)
    except EvidenceError:
        raise
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise EvidenceError(f"{path}: {exc}") from exc


def _object(value: Any, path: str, fields: set | frozenset) -> dict:
    if not isinstance(value, dict):
        _error(path, "expected an object")
    missing = fields - value.keys()
    if missing:
        _error(path, f"missing fields {sorted(missing)}")
    return value


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _error(path, "expected nonempty text")
    return value


def _sha(value: Any, path: str) -> str:
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        _error(path, "expected a lowercase SHA-256")
    return value


def _seconds(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        _error(path, "expected a finite nonnegative number of seconds")
    try:
        numeric = float(value)
    except OverflowError:
        _error(path, "seconds out of range")
    if not math.isfinite(numeric) or numeric < 0:
        _error(path, "expected finite nonnegative seconds")
    return numeric


def _upstream(value: Any, path: str) -> None:
    value = _object(value, path, {"commit"})
    if value["commit"] != UPSTREAM_COMMIT:
        _error(path + ".commit", f"must match fixed source {UPSTREAM_COMMIT}")
    if "repository" in value and value["repository"] != UPSTREAM["repository"]:
        _error(path + ".repository", "unexpected source repository")


def _validate_result(value: Any, label: str) -> dict:
    result = _object(value, label, {
        "task_id", "upstream", "engine", "input_sha256", "parameters", "initial_state",
        "timing_boundary", "predicted_time_s", "steps", "events",
    })
    _upstream(result["upstream"], label + ".upstream")
    _sha(result["input_sha256"], label + ".input_sha256")
    _text(result["task_id"], label + ".task_id")
    _text(result["timing_boundary"], label + ".timing_boundary")
    engine = _object(result["engine"], label + ".engine", {"name", "version"})
    for key in ("name", "version"):
        _text(engine[key], f"{label}.engine.{key}")
    for key in ("parameters", "initial_state"):
        _object(result[key], label + "." + key, set())
    _seconds(result["predicted_time_s"], label + ".predicted_time_s")
    for field in ("steps", "events"):
        if not isinstance(result[field], list):
            _error(label + "." + field, "expected an array")
    for i, step in enumerate(result["steps"]):
        location = f"{label}.steps[{i}]"
        step = _object(step, location, {"op", "origin", "demo_index", "target", "frame"})
        for key in ("op", "origin", "frame"):
            _text(step[key], location + "." + key)
        if type(step["demo_index"]) is not int or step["demo_index"] < 0:
            _error(location + ".demo_index", "expected a nonnegative integer")
        if step["target"] is not None:
            _text(step["target"], location + ".target")
    for i, event in enumerate(result["events"]):
        location = f"{label}.events[{i}]"
        event = _object(event, location, {"op", "start_s", "end_s", "resource", "step_index"})
        for key in ("op", "resource"):
            _text(event[key], location + "." + key)
        start = _seconds(event["start_s"], location + ".start_s")
        end = _seconds(event["end_s"], location + ".end_s")
        if end < start:
            _error(location, "end_s precedes start_s")
        index = event["step_index"]
        if type(index) is not int or index < 0 or index >= len(result["steps"]):
            _error(location + ".step_index", "does not reference a generated step")
    return result


def _file(root: Path, entry: Any, role: str) -> tuple[Path, str]:
    entry = _object(entry, "files." + role, {"path", "sha256"})
    relative = Path(_text(entry["path"], "files." + role + ".path"))
    if relative.is_absolute() or ".." in relative.parts:
        _error("files." + role + ".path", "must stay inside evidence directory")
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        _error("files." + role + ".path", "missing file or path escapes evidence directory")
    expected = _sha(entry["sha256"], "files." + role + ".sha256")
    try:
        content = target.read_bytes()
    except OSError as exc:
        raise EvidenceError(f"files.{role}: {exc}") from exc
    if not content.strip():
        _error("files." + role, "evidence file is empty")
    actual = hashlib.sha256(content).hexdigest()
    if expected != actual:
        _error("files." + role + ".sha256", "file hash mismatch")
    return target, actual


def _differences(python: Any, original: Any, path: str, result: list[dict]) -> None:
    if isinstance(python, dict) and isinstance(original, dict):
        for key in sorted(python.keys() | original.keys()):
            if key not in python or key not in original:
                result.append({"field": path + "." + key, "reason": "missing_field",
                               "python": python.get(key), "original": original.get(key)})
            else:
                _differences(python[key], original[key], path + "." + key, result)
    elif isinstance(python, list) and isinstance(original, list):
        if len(python) != len(original):
            result.append({"field": path + ".length", "python": len(python), "original": len(original)})
        for i, (left, right) in enumerate(zip(python, original)):
            _differences(left, right, f"{path}[{i}]", result)
    elif (path.rsplit(".", 1)[-1] in {"start_s", "end_s", "duration_s", "predicted_time_s"}
          and type(python) in (int, float) and type(original) in (int, float)):
        if not math.isclose(python, original, rel_tol=0.0, abs_tol=ABS_TOLERANCE_S):
            result.append({"field": path, "python": python, "original": original,
                           "difference_s": python - original})
    elif python != original:
        result.append({"field": path, "python": python, "original": original})


def compare_results(python_result_path: Path | str, manifest_path: Path | str) -> dict:
    """Compare one saved result with a complete, locally hash-checked evidence bundle.

    Raises EvidenceError on malformed/missing evidence, mismatched source/input,
    configuration, or unsafe paths. A successful return is a comparison report,
    never permission to mark the engine fully validated.
    """
    manifest_path = Path(manifest_path).resolve()
    manifest = _object(_read(manifest_path), "manifest", {
        "schema_version", "evidence_kind", "case_id", "upstream", "input_sha256", "files",
    })
    if manifest["schema_version"] != "1.0":
        _error("manifest.schema_version", "only version 1.0 is supported")
    if manifest["evidence_kind"] not in {"original_run", "synthetic_test"}:
        _error("manifest.evidence_kind", "must be original_run or synthetic_test")
    _text(manifest["case_id"], "manifest.case_id")
    _upstream(manifest["upstream"], "manifest.upstream")
    _sha(manifest["input_sha256"], "manifest.input_sha256")
    files = _object(manifest["files"], "manifest.files", _REQUIRED_FILES)
    checked = {role: _file(manifest_path.parent, files[role], role) for role in sorted(_REQUIRED_FILES)}
    py = _validate_result(_read(Path(python_result_path)), "python")
    original = _validate_result(_read(checked["normalized_result"][0]), "original")
    if (manifest["evidence_kind"] == "original_run"
            and original["engine"]["name"] != "cogtool_actr"):
        _error("original.engine.name", "original_run requires cogtool_actr; Python regression is not original evidence")
    for label, value in (("python", py), ("original", original)):
        if value["input_sha256"] != manifest["input_sha256"]:
            _error(label + ".input_sha256", "does not match manifest input")
    if py["task_id"] != original["task_id"]:
        _error("task_id", "Python and original select different tasks")
    config = _object(_read(checked["configuration"][0]), "configuration", {
        "input_sha256", "parameters", "initial_state", "task_id", "timing_boundary",
    })
    for key in ("input_sha256", "parameters", "initial_state", "task_id", "timing_boundary"):
        if config[key] != original[key] or config[key] != py[key]:
            _error("configuration." + key, "does not match both results; align configuration before comparison")
    if _read(checked["generated_steps"][0]) != original["steps"]:
        _error("generated_steps", "does not match normalized original steps")
    runtime = _object(_read(checked["runtime_identity"][0]), "runtime_identity", {
        "source_commit", "version", "platform", "java_version", "lisp_version",
        "build_method", "binary_sha256", "memory_image_sha256",
    })
    if runtime["source_commit"] != UPSTREAM_COMMIT:
        _error("runtime_identity.source_commit", "does not match fixed source")
    for key in ("version", "platform", "java_version", "lisp_version", "build_method"):
        _text(runtime[key], "runtime_identity." + key)
    for key in ("binary_sha256", "memory_image_sha256"):
        _sha(runtime[key], "runtime_identity." + key)
    differences: list[dict] = []
    for field in ("predicted_time_s", "steps", "events"):
        _differences(py[field], original[field], field, differences)
    return {
        "schema_version": "1.0", "case_id": manifest["case_id"],
        "evidence_kind": manifest["evidence_kind"], "evidence_integrity": "verified",
        "provenance_authenticity": "requires_human_audit",
        "source_commit": UPSTREAM_COMMIT, "input_sha256": manifest["input_sha256"],
        "python_engine": py["engine"], "original_engine": original["engine"],
        "comparison_status": "different" if differences else "matched_reported_fields",
        "differences": differences,
        "tolerance": {"absolute_seconds": ABS_TOLERANCE_S, "relative": 0.0},
        "original_validation_status": "unverified",
        "equivalence_claim": False,
        "scope": "Listed fields and one evidence bundle only; klm_baseline is not an ACT-R-compatible engine.",
        "evidence_files": {role: {"path": files[role]["path"], "sha256": digest}
                           for role, (_, digest) in checked.items()},
    }

"""Read-only same-process state-contamination check of the real prediction API.

This is synthetic software validation, not an official task or human experiment.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cogtool_py.engine import predict
from cogtool_py.io import export_result, input_hash, load_project
import cogtool_py.engine


def stable(result: dict) -> dict:
    return {k: v for k, v in result.items() if k != "program_runtime_s"}


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def effective_project_hashes(models: dict) -> dict[str, str]:
    """Read actual state without deepcopying immutable mapping proxies.

    Independent of persistence: covers every effective parameter and field.
    """
    def snapshot(value):
        if is_dataclass(value):
            return {field.name: snapshot(getattr(value, field.name)) for field in fields(value)}
        if isinstance(value, Mapping):
            return {key: snapshot(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [snapshot(item) for item in value]
        return value
    return {name: digest(snapshot(model)) for name, model in models.items()}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--a", type=Path, required=True)
    p.add_argument("--b", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if args.out.exists() and (not args.out.is_dir() or any(args.out.iterdir())):
        p.error("output must be a new or empty directory; refusing to overwrite existing evidence")
    args.out.mkdir(parents=True, exist_ok=True)
    models = {"A": load_project(args.a), "B": load_project(args.b)}
    semantic_before = {name: input_hash(model) for name, model in models.items()}
    effective_before = effective_project_hashes(models)
    records, outputs = [], []
    for i, name in enumerate(("A", "B", "A")):
        started = time.perf_counter()
        result = predict(models[name])
        elapsed = time.perf_counter() - started
        output = result.to_dict()
        export_result(result, args.out / f"{i + 1}_{name}")
        outputs.append(output)
        records.append({"position": i + 1, "model": name,
                        "predicted_task_time_s": output["predicted_time_s"],
                        "wall_clock_runtime_s": elapsed,
                        "stable_result_sha256": digest(stable(output)),
                        "effective_project_hashes_after_prediction": effective_project_hashes(models)})
    semantic_after = {name: input_hash(model) for name, model in models.items()}
    effective_after = effective_project_hashes(models)
    inputs_unmodified = effective_before == effective_after and all(
        item["effective_project_hashes_after_prediction"] == effective_before for item in records)
    passed = stable(outputs[0]) == stable(outputs[2]) and inputs_unmodified
    record = {"evidence_kind": "synthetic_unit_test", "process_mode": "same_process_reused_Project_objects",
              "prediction_module": cogtool_py.engine.__file__,
              "sequence": records, "input_hashes_before": semantic_before, "input_hashes_after": semantic_after,
              "semantic_input_hashes_unchanged": semantic_before == semantic_after,
              "effective_project_hashes_before": effective_before, "effective_project_hashes_after": effective_after,
              "effective_project_snapshot_method": "SHA-256 of canonical recursive dataclass fields and Mapping contents; includes all ParameterSet.entries values and provenance",
              "identical_A_results": stable(outputs[0]) == stable(outputs[2]),
              "inputs_unmodified": inputs_unmodified, "status": "PASS" if passed else "FAIL",
              "excluded_from_result_comparison": ["program_runtime_s"]}
    (args.out / "summary.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

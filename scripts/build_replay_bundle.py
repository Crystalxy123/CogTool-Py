#!/usr/bin/env python3
"""Copy local frozen replay material without invoking any prediction backend.

This is packaging tooling, not an installed-package dependency. Official
derived inputs and ported-backend traces stay in a LOCAL_ONLY directory.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cogtool_py.benchmark import (COMPARISON_KIND, EXCLUDED_TOP_LEVEL_FIELDS,
                                 canonical_sha256, file_sha256)
from cogtool_py.io import input_hash, load_project, read_json, write_json
from cogtool_py.models import ModelError


PRIVATE = re.compile(r"/Users/|/home/|[A-Za-z]:\\Users\\")


def personal_paths(value, pointer=""):
    """Locate values by JSON pointer; never silently rewrite a source string."""
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            escaped = key.replace("~", "~0").replace("/", "~1")
            found.extend(personal_paths(child, pointer + "/" + escaped))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(personal_paths(child, pointer + "/" + str(index)))
    elif isinstance(value, str) and PRIVATE.search(value):
        found.append({"json_pointer": pointer, "value": value})
    return found


def copy_file(source: Path, destination: Path, base: Path) -> dict:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    before, after = file_sha256(source), file_sha256(destination)
    if before != after:
        raise ModelError(f"copy changed source bytes: {source.name}")
    return {"path": destination.relative_to(base).as_posix(), "sha256": after}


def _references(source: Path, cid: str, base: Path) -> tuple[list[dict], dict, dict]:
    generation = source / "java_generation" / cid / "generation_1"
    record = read_json(generation / "generation_record.json")
    reference = source / "J-L" / cid / "repeat_1"
    summary = read_json(reference / "summary.json")
    if file_sha256(Path(record["original_input"])) != record["original_input_sha256"]:
        raise ModelError(f"{cid}: original model/spec bytes changed since Java generation")
    if file_sha256(generation / "model.lisp") != record["model_sha256"] or summary["model_sha256"] != record["model_sha256"]:
        raise ModelError(f"{cid}: full Java export identity differs across saved generation and execution")
    destination = base / "references" / cid
    files = []
    for filename, src, kind in (
        ("J-L-stdout.txt", reference / "stdout.txt", "frozen_java_lisp_trace"),
        ("J-L-summary.json", reference / "summary.json", "frozen_java_lisp_summary"),
        ("java-model.lisp", generation / "model.lisp", "frozen_full_java_export"),
        ("fresh_steps.json", generation / "fresh_steps.json", "frozen_java_generated_steps"),
        ("original_demonstration.json", generation / "original_demonstration.json", "frozen_java_demonstration"),
        ("original_scene.json", generation / "original_scene.json", "frozen_java_scene"),
    ):
        copied = copy_file(src, destination / filename, base)
        copied["kind"] = kind
        files.append(copied)
    # The raw record includes historical absolute paths. Retain its hash and a
    # bounded field projection; do not blanket-replace strings in that record.
    keep = ("case_id", "source_commit", "frontend_route", "raw_reader_shared",
            "step_generator_shared", "lisp_writer_shared", "high_level_spec_shared",
            "official_cgt_reader_executed", "case_origin", "java_generation_executed",
            "fresh_regeneration_verified", "original_input_sha256", "cgt_sha256",
            "selector", "preference_policy", "model_sha256", "frontend_patch_scope",
            "generator_call_count", "fresh_step_count", "original_demonstration_count",
            "cached_scripts_used_for_generation", "configuration_sha256", "migration_policy",
            "original_rerun_s", "java_version", "os_arch")
    provenance = {key: record.get(key) for key in keep}
    provenance.update({"projection_of_raw_record_sha256": file_sha256(generation / "generation_record.json"),
                       "omitted_fields": sorted(set(record) - set(keep)),
                       "projection_reason": "Historical absolute storage paths are not portable; original record remains in internal run.",
                       "backend_kind": summary["backend_kind"],
                       "backend_patch_scope": summary["backend_patch_scope"],
                       "reference_role": "Frozen independent Java generation + compatibility-ported Lisp observations; not a new reference execution.",
                       "original_full_program_reexecuted": False})
    write_json(destination / "provenance.json", provenance)
    files.append({"path": (destination / "provenance.json").relative_to(base).as_posix(),
                  "sha256": file_sha256(destination / "provenance.json"), "kind": "field_projected_reference_provenance"})
    model_source = {"kind": record["case_origin"], "sha256": record["original_input_sha256"],
                    "cgt_sha256": record.get("cgt_sha256"), "upstream_commit": record["source_commit"],
                    "selector": record["selector"],
                    "raw_record_sha256": file_sha256(generation / "generation_record.json")}
    return files, model_source, provenance


def build_bundle(source_run: Path, out: Path) -> dict:
    source_run, out = source_run.resolve(), out.resolve()
    if out.exists():
        raise ModelError("bundle output already exists; refusing to overwrite frozen materials")
    suite = read_json(source_run / "suite_manifest.json")
    transfer = read_json(source_run / "transfer_manifest.json")
    source_cases = [(source_run / "official_validation/unified_final_01", spec) for spec in suite["cases"]]
    source_cases += [(source_run / "frozen_transfer_check/actual_run", spec) for spec in transfer["cases"]]
    local_source = source_run / "official_validation/unified_final_01/local_regression"
    source_cases += [(local_source, {"case_id": Path(x["input"]).stem, "origin": "local",
                                    "development_role": "self_authored_baseline_regression"}) for x in suite["local_examples"]]
    counts = Counter(spec["origin"] for _, spec in source_cases)
    if counts != {"official": 5, "synthetic": 27, "local": 4}:
        raise ModelError(f"expected 5 official + 27 synthetic + 4 local inputs; found {dict(counts)}")
    if len({spec["case_id"] for _, spec in source_cases}) != 36:
        raise ModelError("benchmark case identifiers must be unique")
    base = out / "LOCAL_ONLY/benchmarks"
    base.mkdir(parents=True)
    cases = []
    privacy_audit = []
    for source, spec in source_cases:
        cid, origin = spec["case_id"], spec["origin"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", cid):
            raise ModelError("unsafe case identifier in source manifest")
        if origin == "local":
            original_input = source / cid / "saved.json"
            original_expected = source / cid / "repeat_1/result.json"
            references = []
            source_model = {"kind": "self_authored_example", "sha256": file_sha256(original_input),
                            "upstream_commit": None, "selector": None}
        else:
            original_input = source / "python_conversion" / cid / "input.json"
            original_expected = source / "P-P" / cid / "repeat_1/result.json"
            references, source_model, _ = _references(source, cid, base)
        project = load_project(original_input)
        expected = read_json(original_expected)
        effective = input_hash(project)
        if expected["input_sha256"] != effective:
            raise ModelError(f"{cid}: original input does not match frozen prediction identity")
        model = project.to_dict()
        if canonical_sha256(expected["parameters"]) != canonical_sha256(model["parameters"]):
            raise ModelError(f"{cid}: parameter identity differs from frozen result")
        for label, path in (("input", original_input), ("expected", original_expected)):
            hits = personal_paths(read_json(path))
            privacy_audit.append({"case_id": cid, "artifact": label, "personal_path_fields": hits,
                                  "policy": "No value replacement; copy original bytes."})
            if hits:
                raise ModelError(f"{cid}.{label}: personal absolute path at {hits[0]['json_pointer']}; needs a field-specific decision")
        case = {"case_id": cid, "source_category": origin,
                "source_model": source_model, "development_role": spec["development_role"],
                "role": COMPARISON_KIND, "input": copy_file(original_input, base / "inputs" / f"{cid}.json", base),
                "expected": copy_file(original_expected, base / "expected" / f"{cid}.json", base),
                "effective_input_sha256": effective,
                "parameters_sha256": canonical_sha256(model["parameters"]),
                "control_sha256": canonical_sha256(model.get("control")),
                "engine": expected["engine"], "scope": expected.get("execution_scope"),
                "run_policy": (expected.get("runtime_policy") or {}).get("run_policy"),
                "task_id": expected["task_id"],
                "expected_status": "baseline_complete" if origin == "local" else "complete",
                "references": references,
                "limitations": ["Frozen P-P JSON is software regression evidence, not an independent reference answer.",
                                "Bundled J-L observations are not rerun by the installed benchmark command.",
                                "No claim of full original-program or 2009-version equivalence.",
                                "LOCAL_ONLY: redistribution permission for official derivatives and trace material is unresolved."]}
        cases.append(case)
    negative_source = source_run / "runtime_policy/legacy_10_actual"
    negative_project = load_project(negative_source / "input.json")
    negative_result = read_json(negative_source / "P-P/result.json")
    if negative_result["input_sha256"] != input_hash(negative_project) or negative_result["predicted_time_s"] is not None:
        raise ModelError("legacy_10 diagnostic is not the frozen null-prediction input/result pair")
    if negative_result["completion_status"] == "complete":
        raise ModelError("legacy_10 diagnostic unexpectedly claims completion")
    diagnostic = {
        "case_id": "PR-CF-K-legacy-10", "counted_in_36_benchmarks": False,
        "role": "frozen_noncompletion_regression", "expected_status": negative_result["completion_status"],
        "input": copy_file(negative_source / "input.json", base / "diagnostics/PR-CF-K-legacy-10.json", base),
        "expected": copy_file(negative_source / "P-P/result.json", base / "diagnostic_expected/PR-CF-K-legacy-10.json", base),
        "effective_input_sha256": input_hash(negative_project),
        "parameters_sha256": canonical_sha256(negative_project.to_dict()["parameters"]),
        "engine": negative_result["engine"], "scope": negative_result["execution_scope"],
        "run_policy": negative_result["runtime_policy"]["run_policy"],
        "task_id": negative_result["task_id"], "predicted_time_s": None,
        "elapsed_simulation_s": negative_result["elapsed_simulation_s"],
        "termination_reason": negative_result["termination_reason"],
        "comparison": "Same exact full JSON comparison with the five listed top-level exclusions; this fixture must remain noncomplete."}
    for label, path in (("diagnostic_input", negative_source / "input.json"), ("diagnostic_expected", negative_source / "P-P/result.json")):
        hits = personal_paths(read_json(path))
        privacy_audit.append({"case_id": diagnostic["case_id"], "artifact": label, "personal_path_fields": hits,
                              "policy": "No value replacement; copy original bytes."})
        if hits:
            raise ModelError(f"{diagnostic['case_id']}.{label}: personal absolute path needs a field-specific decision")
    write_json(base / "diagnostics.json", {"counted_in_main_benchmark": False, "cases": [diagnostic]})
    manifest = {"manifest_version": 1, "bundle_policy": "LOCAL_ONLY", "case_count": 36,
                "source_counts": dict(counts), "prediction_called_by_builder": False,
                "source_suite_sha256": file_sha256(source_run / "suite_manifest.json"),
                "source_transfer_manifest_sha256": file_sha256(source_run / "transfer_manifest.json"),
                "comparison": {"kind": COMPARISON_KIND, "numeric_policy": "exact_json",
                               "exclude_top_level_fields": list(EXCLUDED_TOP_LEVEL_FIELDS)}, "cases": cases,
                "diagnostics": [{"path": "diagnostics.json", "sha256": file_sha256(base / "diagnostics.json"),
                                 "counted_in_main_benchmark": False}]}
    write_json(base / "manifest.json", manifest)
    # Separate self-authored examples do not carry the official derivative set.
    for spec in suite["local_examples"]:
        cid = Path(spec["input"]).stem
        copy_file(local_source / cid / "saved.json", out / "examples" / f"{cid}.json", out)
    reference_privacy = []
    for path in sorted((base / "references").rglob("*")):
        if not path.is_file():
            continue
        if path.suffix == ".json":
            hits = personal_paths(read_json(path))
        else:
            hits = [{"line": i, "value": line} for i, line in enumerate(path.read_text().splitlines(), 1) if PRIVATE.search(line)]
        if hits:
            reference_privacy.append({"path": path.relative_to(base).as_posix(), "locations": hits,
                                      "policy": "Historical reference bytes retained unchanged in LOCAL_ONLY."})
    write_json(base / "privacy_audit.json", {"input_and_expected": privacy_audit,
                                            "reference_material": reference_privacy,
                                            "global_replacement_performed": False})
    (out / "LOCAL_ONLY/README_zh.md").write_text(
        "# 仅限本地的冻结回放材料\n\n"
        "这里含 5 个官方模型派生输入、27 个合成机制输入和 4 个本地例子的冻结软件回归材料。"
        "官方派生输入、Java 导出和轨迹的再分发授权尚未确定；请勿把本目录作为已获公开授权的数据集分发。\n\n"
        "benchmarks/manifest.json 明确记录每个输入、有效参数、运行策略、冻结结果和 J-L 证据的哈希。"
        "输入及期望 JSON 原字节复制；个人路径逐字段检查结果在 privacy_audit.json。"
        "生成记录仅投影列明的非路径字段，内部原始记录不改。\n\n"
        "安装后运行 cogtool-py benchmark benchmarks/manifest.json --out 新结果目录，会从输入重新调用 Python 预测器，"
        "再比较全部计算 JSON。P-P 期望只用于回归比较，不能作为预测输入或原版参考答案。"
        "只有 manifest 中明确列出的五个顶层身份/墙钟字段被排除；数值不设放宽容差。\n\n"
        "J-L 文件为冻结的独立 Java 生成加装载兼容移植 Lisp 后端观测。本命令不执行 Java/Lisp，"
        "不声称完整原版程序或 2009 模型版本等价。\n", encoding="utf-8")
    (out / "examples/README_zh.md").write_text(
        "# 最小自建例子\n\n这四个简单 JSON 例子与 LOCAL_ONLY 官方派生材料分开。"
        "它们使用显式串行 baseline 引擎；不代表完整 ACT-R 并行机制。\n", encoding="utf-8")
    summary = {"status": "ASSEMBLED_NOT_EXECUTED", "case_count": len(cases), "source_counts": dict(counts),
               "manifest": "LOCAL_ONLY/benchmarks/manifest.json", "manifest_sha256": file_sha256(base / "manifest.json"),
               "prediction_called": False, "reference_execution_called": False,
               "personal_paths_in_input_or_expected": 0,
               "reference_files_with_historical_personal_paths": len(reference_privacy),
               "license_policy": "LOCAL_ONLY", "expected_role": COMPARISON_KIND}
    write_json(out / "assembly_summary.json", summary)
    inventory = [{"path": p.relative_to(out).as_posix(), "sha256": file_sha256(p)}
                 for p in sorted(out.rglob("*")) if p.is_file()]
    write_json(out / "file_inventory.json", {"algorithm": "sha256", "files": inventory,
                                           "inventory_excludes_itself": True})
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = build_bundle(args.source_run, args.out)
    except (ModelError, OSError, KeyError, ValueError) as exc:
        print(f"replay bundle error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

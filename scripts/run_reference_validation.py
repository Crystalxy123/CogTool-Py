"""Reproducible, evidence-preserving validation of the existing CogTool-Py.

Never edits the prediction package, examples, original models or catalog.
All commands run the actual local code. Reference totals never enter prediction.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cogtool_py import __version__
import cogtool_py.engine

BASELINE_TESTS = [
    "tests/test_calculation.py", "tests/test_generation.py", "tests/test_validation.py",
    "tests/test_comparison.py", "tests/test_integration.py", "tests/differential/test_original_cases.py",
]
RESULT_FIELDS = [
    "case_id", "case_group", "condition", "local_model_path", "source_model_hash",
    "comparison_scope", "python_prediction_s", "predicted_task_time_s", "wall_clock_runtime_s",
    "original_rerun_s", "published_prediction_s", "human_mean_s",
    "delta_vs_original_s", "abs_error_vs_original_s", "relative_error_vs_original_pct",
    "delta_vs_published_s", "steps_check", "trace_check", "status", "reason", "raw_output_path",
    "local_execution_status", "published_evidence_status", "strictly_comparable",
]
VALIDATION_ADDITIONS = [
    "scripts/audit_reference_catalog.py", "scripts/audit_reference_workbook.mjs",
    "scripts/inspect_original_models.py", "scripts/reference_validation_worker.py",
    "scripts/run_reference_validation.py", "tests/reference_validation/test_diagnostics.py",
]


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(data) -> str:
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def stable(result: dict) -> dict:
    return {k: v for k, v in result.items() if k != "program_runtime_s"}


def run_command(destination: Path, label: str, command: list[str], *, timeout: int = 120, extra_env: dict | None = None) -> dict:
    logs = destination / "logs"
    logs.mkdir(exist_ok=True, parents=True)
    if any((logs / f"{label}.{suffix}").exists() for suffix in ("json", "stdout.txt", "stderr.txt")):
        raise FileExistsError(f"Refusing to overwrite evidence for {label}; choose a fresh run directory")
    started = time.perf_counter()
    try:
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=timeout,
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **(extra_env or {})})
        code, stdout, stderr = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        code = 124
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        stderr += f"\nTIMEOUT after {timeout} seconds"
    except OSError as exc:
        code, stdout, stderr = 127, "", f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    record = {"command": command, "cwd": str(ROOT), "returncode": code,
              "wall_clock_runtime_s": elapsed, "recorded_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "environment_overrides": {"PYTHONDONTWRITEBYTECODE": "1", **(extra_env or {})}}
    for stream, text in (("stdout", stdout), ("stderr", stderr)):
        file = logs / f"{label}.{stream}.txt"
        file.write_text(text, encoding="utf-8")
        record[stream + "_path"] = str(file.relative_to(destination))
        record[stream + "_sha256"] = sha(file)
    write(logs / f"{label}.json", record)
    print(f"{label}: exit {code}", flush=True)
    return record


def test_stats(path: Path) -> dict:
    if not path.exists():
        return {"status": "not_executed"}
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return {"status": "invalid_test_report", "error": str(exc)}
    cases = list(root.iter("testcase"))
    failed = sum(c.find("failure") is not None for c in cases)
    errors = sum(c.find("error") is not None for c in cases)
    skipped = [c for c in cases if c.find("skipped") is not None]
    xfailed = [c for c in skipped if "xfail" in c.find("skipped").get("type", "").lower()]
    return {"status": "executed" if cases else "empty_test_report", "collected": len(cases), "passed": len(cases) - failed - errors - len(skipped),
            "failed": failed, "errors": errors, "skipped": len(skipped) - len(xfailed), "xfailed": len(xfailed),
            "failure_ids": [c.get("classname", "") + "::" + c.get("name", "") for c in cases if c.find("failure") is not None],
            "skips": [{"name": c.get("name"), "reason": c.find("skipped").get("message")} for c in skipped]}


def protect(destination: Path) -> dict:
    identity_path = destination / "snapshot/identity.json"
    if identity_path.exists():
        return read(identity_path)
    paths = []
    for directory in ("cogtool_py", "tests", "examples", "docs", "scripts", "实验数据"):
        paths.extend(p for p in (ROOT / directory).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    paths.extend(ROOT / p for p in ("README.md", "PROGRESS.md", "pyproject.toml", "requirements-dev.txt", "LICENSE", "NOTICE.md", ".gitignore") if (ROOT / p).is_file())
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}
    (destination / "snapshot").mkdir(parents=True, exist_ok=True)
    with tarfile.open(destination / "snapshot/pre_test_source.tar.gz", "w:gz") as tar:
        for path in paths:
            tar.add(path, arcname=str(path.relative_to(ROOT)), recursive=False)
    git = {}
    for name in (".", "cogtool", "reference/upstream-cogtool", "reference/upstream-documentation"):
        git[name] = {}
        for label, cmd in (("root", ["rev-parse", "--show-toplevel"]),
                           ("commit", ["rev-parse", "HEAD"]), ("status", ["status", "--porcelain=v1"])):
            r = subprocess.run(["git", "-C", str(ROOT / name), *cmd], capture_output=True, text=True)
            git[name][label] = {"returncode": r.returncode, "stdout": r.stdout, "stderr": r.stderr}
    identity = {"date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "platform": platform.platform(), "machine": platform.machine(), "python": sys.version,
                "executable": sys.executable, "base_executable": sys._base_executable,
                "prediction_module_path": cogtool_py.engine.__file__, "software_version": __version__,
                "source_hashes_before": hashes, "git": git}
    identity["workspace_inventory"] = {
        "root_entries": sorted(p.name for p in ROOT.iterdir()),
        "agent_instructions": [str(p.relative_to(ROOT)) for p in ROOT.rglob("AGENTS.md") if ".venv" not in p.parts],
        "catalog_actual_location": "实验数据/CogTool_reference_catalog.json",
        "entrypoint": ".venv/bin/python -m cogtool_py predict MODEL.json --out OUTPUT",
        "api": "cogtool_py.io.load_project -> cogtool_py.engine.predict -> cogtool_py.io.export_result",
    }
    write(identity_path, identity)
    return identity


def verify_trace(result: dict) -> dict:
    events, steps = result["events"], result["steps"]
    errors = []
    if len(events) != len(steps):
        errors.append("event/step count mismatch")
    cursor = 0.0
    for i, event in enumerate(events):
        if i >= len(steps) or event["step_index"] != i or event["op"] != steps[i]["op"]:
            errors.append(f"event {i}: wrong step association")
        if abs(event["start_s"] - cursor) > 1e-9:
            errors.append(f"event {i}: not serially contiguous")
        if abs((event["end_s"] - event["start_s"]) - event["duration_s"]) > 1e-9:
            errors.append(f"event {i}: duration does not match bounds")
        cursor = event["end_s"]
    if abs(cursor - result["predicted_time_s"]) > 1e-9:
        errors.append("last event does not match declared end")
    return {"scope": "declared serial klm_baseline internal consistency, not original trace comparison",
            "status": "PASS" if not errors else "FAIL", "errors": errors}


def empty_result(case_id: str, group: str) -> dict:
    value = {field: None for field in RESULT_FIELDS}
    value.update(case_id=case_id, case_group=group, comparison_scope="end_to_end",
                 steps_check="not_checked", trace_check="not_checked", strictly_comparable=False)
    return value


def csv_output(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(row[key], ensure_ascii=False) if isinstance(row.get(key), (list, dict))
                             else row.get(key) for key in fields})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--catalog", type=Path, default=ROOT / "实验数据/CogTool_reference_catalog.json")
    args = parser.parse_args()
    out = (args.out or ROOT / "reports/validation" / datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")).resolve()
    if out.exists():
        parser.error("output already exists; choose a new run directory to preserve all previous evidence")
    out.mkdir(parents=True, exist_ok=True)
    if (out / "run_manifest.json").exists():
        parser.error("completed run is immutable; select another --out")
    for name in ("logs", "traces", "diagnostics", "reference"):
        (out / name).mkdir(exist_ok=True)
    identity = protect(out)
    if not Path(cogtool_py.engine.__file__).resolve().is_relative_to(ROOT / "cogtool_py"):
        raise RuntimeError("wrong installed prediction module; refusing to test an unrelated package")
    write(out / "comparison_config.json", {
        "written_before_case_comparison": True, "absolute_tolerance_s": 1e-9, "relative_tolerance": 0,
        "basis": "floating-point representation only; no human-performance error allowance",
        "repetition_policy": "exact stable output equality, excluding only measured program_runtime_s",
        "official_pass_requires": ["original rerun evidence", "input/parameter/timing alignment", "step and event comparison"],
        "published_only_policy": "retain historical values; no numerical delta if no aligned Python input",
        "randomness": {"engine": "deterministic serial baseline", "seed": None, "PYTHONHASHSEED": os.environ.get("PYTHONHASHSEED")},
    })
    commands, rows, local_info = [], [], []
    # A simple existing case runs before the broader suite on every fresh invocation.
    if not (out / "logs/00_single_click.json").exists():
        commands.append(run_command(out, "00_single_click", [sys.executable, "-m", "cogtool_py", "predict",
                            str(ROOT / "examples/single_click.json"), "--out", str(out / "traces/bootstrap_single_click")]))
    else:
        commands.append(read(out / "logs/00_single_click.json"))
    if not (out / "logs/01_existing_pytest.json").exists():
        commands.append(run_command(out, "01_existing_pytest", [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                            *BASELINE_TESTS, "--junitxml", str(out / "logs/existing_pytest.xml")]))
    else:
        commands.append(read(out / "logs/01_existing_pytest.json"))
    examples = sorted((ROOT / "examples").glob("*.json"))
    for path in examples:
        raw = read(path)
        case = path.stem
        row = empty_result(case, "local_example")
        row.update(condition=raw["name"], local_model_path=str(path.relative_to(ROOT)), source_model_hash=sha(path),
                   status="NOT_COMPARABLE", reason="本地自建基线示例，未与官方任务输入对齐；非原版一致性PASS。",
                   local_execution_status="not_executed")
        repeats, outputs = [], []
        for repeat in range(1, 4):
            directory = out / "traces" / case / f"repeat_{repeat}"
            record = run_command(out, f"{case}_repeat_{repeat}",
                                 [sys.executable, "-m", "cogtool_py", "predict", str(path), "--out", str(directory)])
            commands.append(record)
            if record["returncode"] == 0 and (directory / "result.json").is_file():
                result = read(directory / "result.json")
                outputs.append(result)
                repeats.append({"repeat": repeat, "returncode": 0, "predicted_task_time_s": result["predicted_time_s"],
                                "wall_clock_runtime_s": record["wall_clock_runtime_s"], "engine_runtime_s": result["program_runtime_s"],
                                "stable_sha256": canonical_sha(stable(result)), "trace_check": verify_trace(result),
                                "raw_output_path": str((directory / "result.json").relative_to(out))})
            else:
                repeats.append({"repeat": repeat, "returncode": record["returncode"], "error_log": record["stderr_path"]})
        success = len(outputs) == 3
        repeated = success and all(stable(o) == stable(outputs[0]) for o in outputs[1:])
        if outputs:
            first_success = next(r for r in repeats if "predicted_task_time_s" in r)
            row.update(python_prediction_s=outputs[0]["predicted_time_s"],
                       predicted_task_time_s=outputs[0]["predicted_time_s"],
                       wall_clock_runtime_s=first_success["wall_clock_runtime_s"],
                       raw_output_path=first_success["raw_output_path"],
                       local_execution_status="SUCCESS" if success and repeated else "FAIL")
        else:
            row["local_execution_status"] = "FAIL"
        if not success or not repeated:
            row.update(status="FAIL", reason="本地真实执行失败或三次输出不一致；详见逐次日志，未影响其他案例。")
        row["local_trace_consistency"] = all(r.get("trace_check", {}).get("status") == "PASS" for r in repeats)
        if not row["local_trace_consistency"]:
            row.update(local_execution_status="FAIL", status="FAIL",
                       reason="本地轨迹自洽检查失败或缺少完整输出；详见逐次trace_check和日志。")
        # steps_check/trace_check remain not_checked against originals; local checks are separate.
        row["reproducibility"] = {"independent_processes": 3, "identical": repeated, "runs": repeats}
        rows.append(row)
        local_info.append({"case_id": case, "input_path": str(path.relative_to(ROOT)), "input_format": "cogtool_py schema 1 JSON",
                           "input_sha256": sha(path), "semantic_input_sha256": outputs[0]["input_sha256"] if outputs else None,
                           "required_operations": [s["op"] for t in raw["tasks"] for s in t["demonstration"]["steps"]],
                           "parameters": outputs[0]["parameters"] if outputs else raw["parameters"],
                           "status": row["local_execution_status"]})
    aba = run_command(out, "same_process_A_B_A", [sys.executable, str(ROOT / "scripts/reference_validation_worker.py"),
                         "--a", str(ROOT / "examples/single_click.json"), "--b", str(ROOT / "examples/text_entry.json"),
                         "--out", str(out / "traces/same_process_A_B_A")])
    commands.append(aba)
    # Audit auxiliary sources after local runs. These scripts do not predict from reference totals.
    for label, script in (("inspect_original_models", "scripts/inspect_original_models.py"),
                          ("audit_reference_catalog", "scripts/audit_reference_catalog.py")):
        commands.append(run_command(out, label, [sys.executable, str(ROOT / script), "--out", str(out)], timeout=180))
    diag = ROOT / "tests/reference_validation/test_diagnostics.py"
    if diag.exists():
        commands.append(run_command(out, "02_supplemental_pytest", [sys.executable, "-m", "pytest", "-q",
                            "-p", "no:cacheprovider", "-o", "junit_family=legacy", str(diag),
                            "--junitxml", str(out / "logs/supplemental_pytest.xml")],
                            extra_env={"COGTOOL_DIAGNOSTICS_DIR": str(out / "diagnostics/current_run")}))
    catalog = read(args.catalog)
    selected = [r for r in catalog["official_and_developer_published_results"]
                if r["case_id"] in {"NP-A1", "NP-A2", "NP-B1", "NP-B2"} or r["case_id"].startswith("PR-")]
    if len({r["case_id"] for r in selected}) != len(selected):
        raise ValueError("duplicate reference case_id; refusing ambiguous comparison")
    mapping = []
    # Detailed source-model audit is attached verbatim; no cache is used as Python output.
    inventory_path = out / "reference/model_inventory.json"
    inventory = read(inventory_path) if inventory_path.exists() else None
    mapped_sources = {item["case_id"]: item for item in (inventory or {}).get("mapped_records", [])}
    write(out / "reference/selected_catalog_rows.json", selected)
    for ref in selected:
        case = ref["case_id"]
        row = empty_result(case, "official_reference")
        is_np = case.startswith("NP-")
        original_path = ROOT / "reference/upstream-documentation/examples" / (
            "phone-number-lookup/N&P93.cgt.zip" if is_np else
            "command-line-v-eclispe/PERCS_CLI_PTP_Comparison_20091216_1513.cgt")
        available = original_path.is_file()
        row.update(condition=ref["condition"], local_model_path=None,
                   source_model_hash=sha(original_path) if available else None,
                   source_model_path=str(original_path.relative_to(ROOT)) if available else None,
                   published_prediction_s=ref["published_prediction_s"], human_mean_s=ref["human_mean_s"],
                   original_rerun_s=None, python_prediction_s=None,
                   published_evidence_status="LITERATURE_ONLY", local_execution_status="not_executed",
                   status="BLOCKED_UNSUPPORTED" if available else "BLOCKED_MISSING_MODEL",
                   reason=("原始官方模型在本地，但现有程序无.cgt导入器；未得到保持几何、路径、初态及参数的可执行JSON。"
                           "当前仅klm_baseline，无法代表原模型ACT-R预测；未删除不支持动作或据发表时间重建输入。")
                           if available else "未找到完整官方模型；保留发表值，不伪造输入。",
                   source_locator=ref["source_locator"], source_url=ref["source_url"],
                   version_and_boundary_notes=ref["notes"])
        row["published_prediction_provenance"] = ref.get("prediction_provenance")
        source_record = mapped_sources.get(case, {})
        row["source_mapping"] = source_record
        if source_record:
            row["reason"] += " 源模型检查：" + str(source_record.get("reason", "见source_mapping"))
            row["historical_cached_prediction_s"] = source_record.get("cached_prediction_s")
            row["cached_prediction_provenance"] = "saved_legacy_model_not_rerun"
        rows.append(row)
        mapping.append({"case_id": case, "condition": ref["condition"],
                        "local_input": None, "source_model": row.get("source_model_path"),
                        "source_model_hash": row["source_model_hash"],
                        "interface": source_record.get("source_design") or ("Design A dialog" if case.startswith("NP-A") else "Design B popup menu" if is_np else ref["condition"].split(" / ")[1]),
                        "source_task": source_record.get("source_task"),
                        "method": source_record.get("method") or ref["condition"],
                        "parameters": source_record.get("parameter_evidence", "unverified; no aligned current-engine parameter set"),
                        "comparison_scope": "end_to_end", "strictly_comparable": False,
                        "status": row["status"], "missing_information": row["reason"]})
    for local in local_info:
        mapping.append({"case_id": local["case_id"], "condition": "local synthetic example",
                        "local_input": local["input_path"], "source_model": local["input_path"],
                        "source_model_hash": local["input_sha256"], "interface": "self-built example",
                        "source_task": local["case_id"], "method": local["required_operations"], "parameters": local["parameters"],
                        "comparison_scope": "end_to_end", "strictly_comparable": False,
                        "status": "NOT_COMPARABLE" if local["status"] == "SUCCESS" else "FAIL", "missing_information": "no official case linkage; local checks are separate"})
    write(out / "results.json", rows)
    csv_output(out / "results.csv", rows, RESULT_FIELDS)
    csv_output(out / "case_mapping.csv", mapping, list(mapping[0]))
    write(out / "diagnostics/reproducibility.json", {"local_cases": [
        {"case_id": r["case_id"], **r["reproducibility"]} for r in rows if r["case_group"] == "local_example"],
        "same_process_A_B_A": read(out / "traces/same_process_A_B_A/summary.json") if aba["returncode"] == 0 else aba})
    changed = [p for p, old in identity["source_hashes_before"].items()
               if not (ROOT / p).exists() or sha(ROOT / p) != old]
    core_changed = [p for p in changed if p.startswith("cogtool_py/")]
    original_rows = [r for r in rows if r["case_group"] == "official_reference"]
    summary = {"planned_unique_cases": len(local_info) + len(selected),
               "planned_local_cases": len(local_info), "local_cases_executed": len(local_info),
               "local_cases_successful": sum(r["status"] == "SUCCESS" for r in local_info),
               "independent_repetitions_per_local_case": 3,
               "independent_local_prediction_invocations": len(local_info) * 3,
               "same_process_A_B_A_status": "PASS" if aba["returncode"] == 0 else "FAIL",
               "planned_official_cases": len(selected), "official_python_runs": 0, "original_reruns": 0,
               "strictly_comparable_official_cases": 0, "official_status_counts": dict(Counter(r["status"] for r in original_rows)),
               "official_pass_rate": None, "reason_pass_rate_null": "zero comparable official cases; not 100% pass",
               "existing_tests": test_stats(out / "logs/existing_pytest.xml"),
               "supplemental_tests": test_stats(out / "logs/supplemental_pytest.xml")}
    summary["failed_commands"] = [r for r in commands if r["returncode"] != 0]
    summary["missing_or_invalid_test_reports"] = [group for group in ("existing_tests", "supplemental_tests")
                                                   if summary[group].get("status") != "executed"]
    observed_files = set()
    for directory in ("cogtool_py", "tests", "examples", "docs", "scripts", "实验数据"):
        observed_files.update(str(p.relative_to(ROOT)) for p in (ROOT / directory).rglob("*")
                              if p.is_file() and "__pycache__" not in p.parts)
    new_files = sorted(observed_files - set(identity["source_hashes_before"]))
    manifest = {"run_id": out.name, "started": identity["date_utc"],
                "finished_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "identity": identity,
                "invocation": sys.argv, "catalog_path": str(args.catalog), "catalog_sha256": sha(args.catalog),
                "local_cases": local_info, "summary": summary, "commands": commands,
                "code_preservation": {"modified_preexisting_files": changed, "core_unchanged": not core_changed},
                "prediction_module_path": cogtool_py.engine.__file__, "dependencies": {p.metadata["Name"]: p.version for p in importlib.metadata.distributions()},
                "new_or_modified_files": sorted(set(new_files + changed)) + [str(out.relative_to(ROOT)) + "/**"],
                "validation_tooling_added_in_this_task": VALIDATION_ADDITIONS,
                "artifact_file_listing": "artifact_inventory.json (all evidence files except this self-referential inventory)",
                "original_model_inventory": inventory,
                "excluded_reference_cases": [r["case_id"] for r in catalog["official_and_developer_published_results"] if r not in selected]}
    write(out / "run_manifest.json", manifest)
    # A concise machine-generated report is supplemented with source-specific findings by the audit scripts.
    lines = ["# CogTool-Py 真实运行与参考案例测试", "",
             f"当前版本在 {len(local_info)} 个本地基线示例中成功运行 {summary['local_cases_successful']} 个，三次独立进程结果见下表。本轮没有完成官方案例的Python预测或原版重跑。",
             "官方发表数字保留为历史参考。完整输入未转换、预测引擎范围不同，不能计算有意义的Python－发表值差异。",
             "确定的问题集中于直接Python对象API：未知操作、快捷键与单位缺少统一校验；修改默认参数后哈希不变且保存丢失修改；非法几何与错误步骤对象处理不完整。下文列出证据、函数与复现方法。",
             "仍缺官方任务的可信转换输入、对齐参数与真实重跑轨迹，不能宣称完整等价于CogTool。",
             "", "## 测试统计", "",
             f"计划 {summary['planned_unique_cases']} 个案例：本地 {len(local_info)} 个、官方 {len(selected)} 个。执行本地 {summary['local_cases_executed']} 个，三次独立预测共 {summary['independent_local_prediction_invocations']} 次；另有最简入口检查和同进程 A→B→A。重复次数不是真人样本数。",
             f"已有测试：{summary['existing_tests'].get('passed', 0)} 通过、{summary['existing_tests'].get('failed', 0)} 失败、{summary['existing_tests'].get('skipped', 0)} 跳过；跳过项缺少原版运行证据，不算通过。",
             f"新增 synthetic_unit_test：{summary['supplemental_tests'].get('passed', 0)} 通过、{summary['supplemental_tests'].get('failed', 0)} 失败、{summary['supplemental_tests'].get('skipped', 0)} 跳过，没有用 xfail 隐藏缺陷。",
             f"同进程 A→B→A：{summary['same_process_A_B_A_status']}。官方 Python 运行 0、原版重跑 0、严格可比较 0；通过率未定义，保留 null。官方状态：{json.dumps(summary['official_status_counts'], ensure_ascii=False)}。",
             "本地重复比较排除电脑计算耗时，其余完整结果必须一致；轨迹自洽按当前引擎声明的串行规则检查，不将此规则套用于ACT-R。容差在comparison_config.json中预先固定。", "",
             "## 本地案例", "", "| 案例 | 预测秒数 | 三次一致 | 本地轨迹自洽 |", "|---|---:|---|---|"]
    for row in rows[:len(local_info)]:
        lines.append(f"| {row['case_id']} | {row['python_prediction_s']} | {row['reproducibility']['identical']} | {row['local_trace_consistency']} |")
    lines += ["", "本地结果未与官方案例对齐，所以results中的status为NOT_COMPARABLE，local_execution_status另记运行成功。",
              "计算耗时在wall_clock_runtime_s；预测的人类时间在predicted_task_time_s。二者独立保存。",
              "", "## 官方案例", "", "| 案例 | 条件 | 发表预测秒数 | 原版重跑 | Python正式结果 | 状态 |",
              "|---|---|---:|---|---|---|"]
    for row in original_rows:
        lines.append(f"| {row['case_id']} | {row['condition']} | {row['published_prediction_s']} | 缺失 | 缺失 | {row['status']} |")
    lines += ["", "没有本次原版重跑轨迹，steps_check和trace_check均为not_checked。旧模型可含历史缓存和旧trace，但不能用作本次原版执行证据。",
              "不能用本地轨迹自洽代替原版对照。没有对齐的Python正式案例，因此全部原版误差和发表值差值保留null。",
              "本轮初次核查的15条发表值与JSON、Excel及原论文一致：NP为CHI 2004 Table 1（PDF第6页），PR为本地PLATEAU论文Figure 4（PDF第5页）。另4条PDA不在本轮范围；Min汇总和空白方法不计为独立案例。每次复跑的来源核验结果详见reference/catalog_audit.json。",
              "PR的Help时间不含帮助正文阅读，所有PR模型排除系统响应时间。NP发表值来自2004年工具链；现存NP/PR模型分别保存于1.0.4 r3035 / 1.2trunk r3309（2009），固定参考源码为2014 tag。因此发表值、旧缓存与本轮结果不能默认同版本同边界。",
              "详见reference/MODELS_zh.md、reference/CATALOG_zh.md、diagnostics/内新增测试证据。",
              "", "## 原版运行环境", "",
              "在当前macOS arm64上实际尝试了固定源码编译、原Java启动方式及随源码提供的CLISP。首次诊断证实：当前JDK拒绝Java 1.5编译目标，启动拒绝-d32，i386 CLISP返回bad CPU type。每次复跑的原始命令、退出码与输出见diagnostics/original_environment.json和logs/original/。未取得任何官方任务新预测。",
              "仍需与原模型版本匹配的32位JVM/SWT、i386 CLISP及可运行宿主，或提供同版本重新计算后带参数、完整动作和事件轨迹的可信导出。现有DMG未被假定与固定源码对应。",
              "", "## 已证实的问题与修复优先级", "",
              "以下均由未修改版本的日志/源码证实，且仅涉及直接构造或修改Python对象的API通道；正常JSON/CLI案例的重复运行没有发现这些错误。",
              "",
              "1. P1：预测API没有统一的完整输入校验。cogtool_py/engine.py:57的predict调用cogtool_py/generator.py:181的validate，但后者仅生成脚本；未知op可被静默丢弃，CTRL+C可被算成一个普通键，错误单位可直接当秒数。最早差异在输入校验/步骤生成。",
              "   复现：.venv/bin/python -m pytest tests/reference_validation/test_diagnostics.py -k 'direct_unknown_operation or direct_unsupported_shortcut or direct_parameter_unit' -q",
              "   最小修复方向：在公开API边界验证真实对象的类型、操作、键集合、单位、初态及尺寸；generator未知操作明确raise ModelError。不要只依赖调用方曾运行JSON解析，也不要先通过有缺陷的序列化丢掉参数。",
              "",
              "2. P1：有效默认参数可变，但输入哈希和保存遗漏其变化。cogtool_py/models.py:92的ParameterSet.entries可改写；:116的input_dict仅输出kind=modeler_supplied；cogtool_py/io.py:54的save_project及:61的input_hash使用该字典。Think从1.2改为2.4后结果1.55→2.75 s，hash不变；保存重载又回1.55 s。最早差异在参数身份/序列化。",
              "   复现：.venv/bin/python -m pytest tests/reference_validation/test_diagnostics.py -k 'mutable_effective' -q",
              "   最小修复方向：使参数集不可变，提供验证过的覆盖入口；模型哈希包含所有实际生效参数及来源，往返保持有效值。",
              "",
              "3. P2：直接对象的非法几何可被零距离短路掩盖，已展开步骤/空键序列触发非结构化异常。cogtool_py/engine.py:27的point_time在验证尺寸前对零距离返回0；cogtool_py/generator.py:125和:150对ScriptStep/空keys抛AttributeError/IndexError。最早差异在输入契约/几何校验。这与第1项共享验证缺口，并非三个独立根因。",
              "   复现：.venv/bin/python -m pytest tests/reference_validation/test_diagnostics.py -k 'zero_distance or expanded_script_objects or direct_empty_keys' -q",
              "   最小修复方向：先验证几何和步骤对象，再做零距离优化；明确拒绝expanded ScriptStep作为Demonstration，不重新展开；统一带任务/步骤上下文的ModelError。",
              "",
              "本轮未应用任何核心修复或调参。关于ACT-R资源重叠、EMMA等造成的实际数值偏差，目前仍缺真实重跑轨迹，不能量化或归因。",
              "官方验证的最早阻塞是.cgt到当前受限JSON的语义输入转换；其后还有原始控件/快捷键等支持范围、引擎类型、旧版本和原版运行环境问题。",
              "", "## 文件保护与复跑", "", f"核心代码保持不变：{not core_changed}。原始快照见snapshot/pre_test_source.tar.gz。",
              "新增文件清单及全部环境、实际命令、退出码见run_manifest.json。逐个产物路径和哈希见artifact_inventory.json。未修改原始参考目录或参数。",
              "本轮新增的测试工具如下（后续复跑时这些工具已经属于运行前快照）：", "",
              *["- " + path for path in VALIDATION_ADDITIONS], "",
              "复跑到新目录（不要覆盖本次证据）：", "",
              "    .venv/bin/python scripts/run_reference_validation.py", "",
              "退出码1代表新增诊断或本地测试存在失败；报告仍完整生成。官方阻塞不计为PASS。"]
    (out / "REPORT_zh.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write(out / "artifact_inventory.json", {str(path.relative_to(out)): sha(path)
                                             for path in sorted(out.rglob("*")) if path.is_file()})
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Report: {out / 'REPORT_zh.md'}")
    failures = sum(summary[group].get(field, 0) for group in ("existing_tests", "supplemental_tests") for field in ("failed", "errors"))
    local_failed = any(r["status"] != "SUCCESS" for r in local_info)
    return 1 if (failures or changed or local_failed or aba["returncode"] or
                 summary["failed_commands"] or summary["missing_or_invalid_test_reports"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())

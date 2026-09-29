#!/usr/bin/env python3
"""Read NP-B2 archived reference only after frozen and vNext first runs exist.

This never calls a predictor and never writes model inputs. It preserves saved
trace lines, generated states, reference values, and limited validity evidence.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.analyze_npb1_trace import parse_trace, pair_productions
from scripts.convert_phone_case import ConversionError, app_for, read_phone
from scripts.inspect_original_models import CODE_COMMIT, classname, field, scalar


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def node_fields(node):
    result = []
    for child in node:
        if child.tag == "sup":
            result.extend(node_fields(child))
        else:
            result.append({"tag": child.tag, "field": child.get("var"), "object_id": child.get("id"),
                           "idref": child.get("idref"), "class": classname(child),
                           "scalar": scalar(child) if child.tag in {"str", "char", "bool", "int", "dbl", "enum", "null"} else None})
    return result


def extract(out):
    out = out.resolve()
    if not out.is_relative_to(ROOT / "reports") or out.exists():
        raise ConversionError("Reference output must be a new directory under workspace reports")
    run = out.parent
    prerequisites = [run/"npb2_first_run/summary.json", run/"post_fix_retest/NP-B2_first/result.json"]
    if any(not path.is_file() for path in prerequisites):
        raise ConversionError("Preserved frozen first run and vNext first run must exist before reference extraction")
    graph, provenance = read_phone()
    app = app_for(graph, "Pop-Up", "Look up two numbers")
    if app.get("id") != "373":
        raise ConversionError("Pinned NP-B2 TaskApplication ID changed")
    results = [node for node in app.iter("obj") if classname(node) == "TimePredictionResult"]
    if len(results) != 1:
        raise ConversionError("Expected one saved NP-B2 result; do not choose by timing")
    result = results[0]
    script, demo = graph.get(result, "script"), graph.get(app, "demonstration")
    if graph.get(script, "demonstration") is not demo:
        raise ConversionError("Result script does not reference NP-B2's own demonstration")
    trace_lines = [scalar(node) for node in graph.entries(graph.get(result, "traceLines"))]
    error_lines = [scalar(node) for node in graph.entries(graph.get(result, "errorLines"))]
    if any(not isinstance(line, str) for line in trace_lines+error_lines):
        raise ConversionError("Nonstring saved trace/error entry")
    trace_text = "\n".join(trace_lines)+"\n"
    parsed = parse_trace(trace_text)
    productions = pair_productions(parsed["events"])
    generated = []
    for index, state in enumerate(graph.entries(graph.get(script, "stepStates"))):
        step = graph.get(state, "forStep")
        generated.append({**graph.step(step), "archived_generated_index": index,
                          "state_object_id": state.get("id"), "state_class": classname(state),
                          "saved_state_fields": node_fields(state)})
    cache_raw = field(result, "taskTime").get("val")
    cached = graph.value(result, "taskTime")
    events = parsed["events"]
    stamps = [Decimal(event["timestamp_text"]) for event in events]
    stops = [e for e in events if e["module"] == "PROCEDURAL" and re.fullmatch(r"PRODUCTION-FIRED STOP-\d+", e["message"])]
    motor_finish = [e for e in events if e["module"] == "MOTOR" and e["message"] == "FINISH-MOVEMENT"]
    device_clicks = [e for e in events if e["module"] == "COGTOOL" and e["message"] == "DEVICE-CLICK"]
    ended = [e for e in events if e["message"] == "Stopped because no events left to process"]
    scalars = [row for row in parsed["raw_lines"] if row["kind"] == "scalar_output"]
    cache_decimal = Decimal(cache_raw)
    exact = lambda text: Decimal(text) == cache_decimal
    checks = {
        "lossless_normalized_trace_reconstruction": parsed["lossless_raw_reconstruction"],
        "timestamps_monotone": all(a <= b for a,b in zip(stamps, stamps[1:])),
        "first_timed_event_at_zero": bool(stamps) and stamps[0] == 0,
        "exactly_one_STOP_firing": len(stops) == 1,
        "exactly_one_queue_exhausted_end": len(ended) == 1,
        "last_motor_finish_equals_cache_exact_decimal": bool(motor_finish) and exact(motor_finish[-1]["timestamp_text"]),
        "queue_end_equals_cache_exact_decimal": bool(ended) and exact(ended[-1]["timestamp_text"]),
        "last_timed_event_equals_cache_exact_decimal": bool(events) and exact(events[-1]["timestamp_text"]),
        "terminal_scalar_equals_cache_exact_decimal": bool(scalars) and exact(scalars[-1]["value_raw"]),
        "all_selected_fired_productions_uniquely_paired": not productions["unmatched"],
        "result_script_references_own_demonstration": graph.get(script, "demonstration") is demo,
        "saved_active_algo_matches_result_algo": graph.get(app, "algorithm") is graph.get(result, "computeAlg"),
    }
    validity = {"result_state_saved": graph.value(result, "resultState"),
        "result_state_interpretation": "IS_COMPUTED=1 in pinned 2014 APredictionResult.java:130-142; consistent with saved ACT-R Time name",
        "demonstration_invalid_count": graph.value(demo, "invalidCount"),
        "demonstration_obsolete_count": graph.value(demo, "obsoleteCount"),
        "saved_invalidation_flags_present": field(demo,"invalidCount") is not None and field(demo,"obsoleteCount") is not None,
        "demonstration_flags_interpretation": "invalidCount>0 or obsoleteCount>0 marks invalid/obsolete in Demonstration.java:890-907",
        "saved_invalid_or_obsolete_flag": bool(graph.value(demo,"invalidCount") or graph.value(demo,"obsoleteCount")),
        "status": "archive_declares_computed_and_nonobsolete; independent_cache_freshness_unknown",
        "error_line_count": len(error_lines), "error_lines_are_empty": not error_lines,
        "observed_warning_count": sum("Warning:" in line for line in error_lines),
        "warning_effect_on_prediction": "unknown; preserve 9 NIL-slot warnings despite computed state and complete-looking trace",
        "computation_timestamp": None, "model_revision_at_computation": None,
        "modification_history_since_computation": None, "input_hash_saved_with_cache": None,
        "freshness_independently_verified": False,
        "trace_consistency_is_not_original_rerun_or_equivalence": True}
    catalog_path = ROOT/"实验数据/CogTool_reference_catalog.json"
    catalog = json.loads(catalog_path.read_text())
    rows = [row for row in catalog["official_and_developer_published_results"] if row["case_id"] == "NP-B2"]
    if len(rows) != 1:
        raise ConversionError("Expected one local catalog NP-B2 published row")
    publication = {"reference_kind": "published_reference", "row": rows[0],
                   "source_catalog": str(catalog_path.relative_to(ROOT)), "source_sha256": digest(catalog_path),
                   "verification_in_this_extraction": "catalog_transcribed; no new PDF verification performed",
                   "not_same_version_as_archived_file": True, "used_for_input_or_prediction": False}
    out.mkdir(parents=True)
    (out/"archived_traceLines.txt").write_text(trace_text, encoding="utf-8")
    (out/"archived_errorLines.txt").write_text("\n".join(error_lines)+"\n", encoding="utf-8")
    write(out/"archived_traceLines.json", trace_lines)
    write(out/"archived_errorLines.json", error_lines)
    write(out/"trace_events.json", events)
    write(out/"trace_parameters.json", parsed["parameters"])
    write(out/"trace_lines_parsed.json", parsed["raw_lines"])
    write(out/"production_pairs.json", productions)
    write(out/"saved_generated_steps.json", generated)
    write(out/"published_reference.json", publication)
    binding = {"TaskApplication": app.get("id"), "task": graph.get(app,"task").get("id"),
               "design": graph.get(app,"design").get("id"), "Demonstration": demo.get("id"),
               "InitialState": graph.get(demo,"initialState").get("id"), "startFrame": graph.get(demo,"startFrame").get("id"),
               "scriptResults_map": graph.get(app,"scriptResults").get("id"), "ScriptResults": "380",
               "Script": script.get("id"), "model_generator": graph.get(script,"modelGen").get("id"),
               "model_generator_class": classname(graph.get(script,"modelGen")),
               "compute_algorithm": graph.get(result,"computeAlg").get("id"),
               "compute_algorithm_class": classname(graph.get(result,"computeAlg")),
               "TimePredictionResult": result.get("id"), "result_fields": node_fields(result),
               "demonstration_fields": node_fields(demo), "script_fields": node_fields(script),
               "trace_array": graph.get(result,"traceLines").get("id"), "error_array": graph.get(result,"errorLines").get("id"),
               "saved_model_steps_array": graph.get(result,"modelSteps").get("id"),
               "saved_model_step_count": len(graph.entries(graph.get(result,"modelSteps")))}
    write(out/"object_mapping.json", binding)
    integrity = {"checks": checks, "all_internal_checks_consistent": all(checks.values()),
        "case_id": "NP-B2", "reference_kind": "archived_reference", "event_count": len(events),
        "line_count": len(trace_lines), "parsed_line_kinds": dict(Counter(row["kind"] for row in parsed["raw_lines"])),
        "production_pair_count": len(productions["pairs"]), "unknown_line_numbers": [row["line_number"] for row in parsed["raw_lines"] if row["kind"] == "unknown"],
        "STOP_events": stops, "last_device_click": device_clicks[-1] if device_clicks else None,
        "device_click_count": len(device_clicks), "last_motor_finish": motor_finish[-1] if motor_finish else None,
        "queue_exhausted_events": ended, "terminal_scalar": scalars[-1] if scalars else None,
        "cached_prediction_s": cached, "cached_prediction_raw_xml_value": cache_raw,
        "comparison_method": "exact Decimal equality only for printed cache/terminal/end consistency; no borrowed NP-B1 tolerance",
        "observed_event_timestamp_decimal_places": sorted({max(0,-Decimal(e["timestamp_text"]).as_tuple().exponent) for e in events}),
        "validity": validity, "original_rerun_s": None, "comparison_to_python_performed": False}
    write(out/"trace_integrity.json", integrity)
    files = {path.name: {"path": path.name, "sha256": digest(path)} for path in sorted(out.iterdir()) if path.is_file()}
    metadata = {"case_id": "NP-B2", "provenance": "archived_reference", "reference_kind": "archived_reference", "rerun": False,
        "extracted_at_utc": datetime.now(timezone.utc).isoformat(), "source": provenance,
        "source_object_id": result.get("id"), "task_application_object_id": app.get("id"),
        "saved_version": graph.root.attrib, "archived_compute_algorithm_class": classname(graph.get(result,"computeAlg")),
        "trace_version": graph.value(result,"__ACTRPredictionAlgo.traceVersion"), "name": graph.value(result,"name"),
        "cached_prediction_s": cached, "cached_prediction_raw_xml_value": cache_raw,
        "saved_generated_steps": generated, "validity": validity, "files": files,
        "used_for_input_or_prediction": False, "original_rerun_s": None,
        "first_runs_preceded_reference_access": {str(path.relative_to(run)): {"sha256":digest(path)} for path in prerequisites},
        "unknowns": {"source_2009_commit": None, "actual_saved_generated_Lisp": None,
                     "computation_date": None, "independent_cache_freshness": None,
                     "unprinted_resource_states": None, "2009_vs_2014_semantic_equivalence": None,
                     "2004_paper_vs_2009_model_equivalence": None},
        "not_strict_blind_study": True}
    write(out/"archived_reference.json", metadata)
    lines = ["# NP-B2 历史参考提取", "", "本目录仅供后续差分，不参与输入或预测。冻结版首次拒绝与 vNext 首次执行已保存后，才进行本次参考字段读取。", "",
        "TaskApplication373 → ScriptResults380 → Script381 → TimePredictionResult408；Script引用Demonstration374，computeAlg306为ACTR6PredictionAlgo，生成器289为KLMCognitiveGenerator。", "",
        f"缓存 taskTime 原值 **{cache_raw} s**。文件保存头为 CogTool1.0.4 / revision3035 / build05/06/2009-04:34，Java1.5.0_16，Mac OS X10.5.6。这是2009归档，不能写成2014源码的新运行结果。", "",
        "历史生成脚本10步：point8、right-click8、Think1.2、point22、click22、point42、right-click42、Think1.2、point46、click46。对象及每步保存状态在saved_generated_steps.json，保留owner377/378绑定。它们只作参考，不补入预测输入。", "",
        f"原trace共有{len(trace_lines)}行，解析到{len(events)}个时刻事件、{len(parsed['parameters'])}项打印参数、{len(productions['pairs'])}对唯一selected/fired。STOP4.762、最后设备click4.822、最后motor release与queue exhausted均4.912，末标量4.912与缓存精确十进制一致；未把STOP当完整返回时长。所有原行和未知行都保留。", "",
        "缓存有效性证据：保存resultState=1（2014定义IS_COMPUTED）；demo.invalidCount=0、obsoleteCount=0，未见保存的修改失效标记。可是没有计算日期、绑定的输入hash、计算后编辑历史或2009源码身份，缓存是否与当时输入完全同步仍unknown。内部一致性不是独立重跑验证。", "",
        f"errorLines并非空：{len(error_lines)}条Warning，内容是COGTOOL-BUTTON类chunk没有NIL槽。它们与computed/结束轨迹共存；对计算的影响unknown，不能称无警告的有效运行。", "",
        "本地catalog转录NP-B2发表预测6.2 s、真人均值6.5 s、SD0.9 s、N20，定位John et al.(2004) Table1，PDF第6页/印刷460页，取This paper行。此次没有重新读PDF；2004工具链、2009归档与2014代码不得假定等价。", "",
        "当前未进行与Python结果的差分。reference_kind=archived_reference；original_rerun_s=null；没有把发表/缓存/新运行三种数值互相替代。", ""]
    (out/"REFERENCE_zh.md").write_text("\n".join(lines), encoding="utf-8")
    return {"case_id":"NP-B2", "cached_prediction_s":cached, "trace_events":len(events),
            "generated_steps":len(generated), "internal_consistency":all(checks.values()), "warnings":len(error_lines)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    try:
        print(json.dumps(extract(args.out),ensure_ascii=False))
        return 0
    except (ConversionError,OSError,ValueError,KeyError) as exc:
        print(f"Archived phone extraction failed: {exc}",file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())

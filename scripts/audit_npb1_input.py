#!/usr/bin/env python3
"""Audit only NP-B1 input provenance without rerunning an original backend.

The current converter is called only for NP-B1. It never uses saved generated
steps or time values to construct the input. Output must be a new directory.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.convert_phone_case import (  # noqa: E402
    ConversionError, baseline_parameters, construct_candidate, extract_case,
    read_phone, source_rules,
)
from cogtool_py.generator import generate  # noqa: E402
from cogtool_py.io import input_hash, read_json  # noqa: E402
from cogtool_py.models import ModelError, Project  # noqa: E402


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode()


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def file_record(path: Path) -> dict:
    return {'path': str(path.resolve()), 'sha256': sha(path.read_bytes())}


def numeric_fields(value: object, path: str = '$') -> dict:
    if isinstance(value, bool):
        return {}
    if isinstance(value, (int, float)):
        return {path: {'type': type(value).__name__, 'value': value}}
    result = {}
    if isinstance(value, dict):
        for key, item in value.items():
            result.update(numeric_fields(item, path + '.' + key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            result.update(numeric_fields(item, f'{path}[{index}]'))
    return result


def audit(out: Path, baseline: Path, version_path: Path) -> dict:
    out, baseline, version_path = out.resolve(), baseline.resolve(), version_path.resolve()
    if out.exists():
        raise ConversionError(f'Output already exists; refuse to overwrite evidence: {out}')
    if not out.is_relative_to(ROOT / 'reports'):
        raise ConversionError('Audit output must be a new directory below workspace reports/')
    paths = {name: baseline / name for name in ('candidate_input.json', 'extraction.json',
                                               'archived_reference.json', 'python_prediction/result.json')}
    before = {name: file_record(path) for name, path in paths.items()}
    original_input = read_json(paths['candidate_input.json'])
    previous_extraction = read_json(paths['extraction.json'])
    archive = read_json(paths['archived_reference.json'])
    baseline_result = read_json(paths['python_prediction/result.json'])
    versions = read_json(version_path)
    graph, provenance = read_phone()
    extraction = extract_case(graph, 'NP-B1')
    assumptions, assumption_profile = baseline_parameters()
    candidate, mappings, blockers = construct_candidate(graph, extraction, assumptions)
    if blockers:
        raise ConversionError(f'NP-B1 converter returned blockers: {blockers}')
    if previous_extraction.get('source') != provenance:
        raise ConversionError('Retained baseline extraction has different source provenance')
    if versions.get('case_id') != 'NP-B1' or versions.get('provenance') != provenance:
        raise ConversionError('Version audit belongs to different source evidence')
    if archive.get('source_object_id') != '307' or archive.get('provenance') != 'archived_reference' or archive.get('rerun') is not False:
        raise ConversionError('Retained archive metadata is not identified as the NP-B1 saved result')
    fresh_saved_steps = [graph.step(graph.get(s, 'forStep'))
                         for s in graph.entries(graph.get(graph.index['291'], 'stepStates'))]
    if fresh_saved_steps != archive['saved_generated_steps']:
        raise ConversionError('Retained archived generated steps differ from read-only original objects')
    project = Project.from_dict(candidate)
    old_project = Project.from_dict(original_input)
    current_steps = [asdict(step) for step in generate(project, project.tasks[0]).steps]
    comparison = {
        'raw_json_canonical_algorithm': 'SHA-256 of UTF-8 JSON; sorted keys, compact separators, ensure_ascii=False; number types retained',
        'baseline_raw_canonical_sha256': sha(canonical(original_input)),
        'current_raw_canonical_sha256': sha(canonical(candidate)),
        'raw_canonical_strictly_equal': canonical(original_input) == canonical(candidate),
        'numeric_field_count': len(numeric_fields(candidate)),
        'numeric_fields_and_types_strictly_equal': numeric_fields(original_input) == numeric_fields(candidate),
        'baseline_normalized_input_sha256': input_hash(old_project),
        'current_normalized_input_sha256': input_hash(project),
        'retained_result_input_sha256': baseline_result['input_sha256'],
        'normalized_hash_matches_retained_result': input_hash(project) == input_hash(old_project) == baseline_result['input_sha256'],
        'python_generated_steps_match_retained_baseline': current_steps == baseline_result['steps'],
        'numeric_differences': [],
        'input_values_changed': False,
        'source_interpretation_corrected': True,
    }
    if not all(comparison[key] for key in ('raw_canonical_strictly_equal', 'numeric_fields_and_types_strictly_equal',
                                            'normalized_hash_matches_retained_result', 'python_generated_steps_match_retained_baseline')):
        raise ConversionError('Input or generation differs from retained baseline; no unchanged-input claim allowed')
    widgets = candidate['design']['frames'][0]['widgets']
    geometry = []
    for item in widgets:
        raw = graph.target(graph.index[item['id'][1:]])
        bounds = {name: item[name] for name in ('x', 'y', 'width', 'height')}
        if bounds != raw['geometry']:
            raise ConversionError(f'Geometry differs from original object {raw["object_id"]}')
        target = project.design.frames[0].widget(item['id'], 'audit.geometry').center
        expected = [bounds['x'] + math.floor(bounds['width'] / 2), bounds['y'] + math.floor(bounds['height'] / 2)]
        if list(target) != expected:
            raise ConversionError(f'Core center differs from cited floor rule: {item["id"]}')
        geometry.append({'source_object_id': raw['object_id'], 'source_class': raw['class'],
                         'python_widget_id': item['id'], 'parent': item['parent'], 'source_geometry': raw['geometry'],
                         'python_geometry': bounds, 'strict_equal': True, 'conditional_2014_visual_target': expected,
                         'is_selected_path': item['id'] in ('w8', 'w22')})
    step_map = []
    for index, saved in enumerate(fresh_saved_steps):
        current = current_steps[index]
        step_map.append({'demonstration_object_id': '287', 'archived_step_object_id': saved['object_id'],
                         'archived_class': saved['class'], 'archived_demonstrated_flag': saved['demonstrated'],
                         'archived_inserted_by_user': saved['inserted_by_user'],
                         'python_step_index': current['index'], 'python_op': current['op'],
                         'python_origin': current['origin'], 'python_target': current['target'],
                         'alignment_level': 'coarse operator identity only; not timing equivalence',
                         'cache_used_to_generate': False})
    action = extraction['demonstration_steps'][0]['action']
    items = [
        {'id': '01_version_binding', 'title_zh': '版本、设计、任务和对象引用', 'status': 'PARTIALLY_VERIFIED',
         'evidence': {'saved_version': provenance['persist_metadata'], 'design': {'name': 'Pop-Up', 'object_id': '3'},
                      'task': {'name': 'Look up one number', 'object_id': '279'}, 'task_application_object_id': '283',
                      'demonstration_object_id': '284', 'initial_object_id': '285', 'script_object_id': '291',
                      'result_object_id': '307', 'algorithm_object_id': '306',
                      'fixed_2014_commit': versions['source_version_alignment']['fixed_reference_commit']},
         'unknowns': {'source_2009_r3035_commit': None},
         'conclusion_zh': '模型来源和对象绑定已核对；r3035 源码未知，2014 规则只是条件参考。'},
        {'id': '02_demonstration_and_generation', 'title_zh': '原示范、旧生成步骤和 Python 生成步骤', 'status': 'VERIFIED_WITH_SCOPE_LIMIT',
         'evidence': {'demonstration_count': 1, 'demonstration_object_ids': ['287'],
                      'candidate_demonstration': candidate['tasks'][0]['demonstration']['steps'],
                      'archived_generated_count': len(fresh_saved_steps), 'python_generated_count': len(current_steps),
                      'mapping': step_map, 'extra_python_step': current_steps[-1],
                      'generation_uses_demonstration_and_parent_chain': True, 'archive_used_for_generation': False},
         'unknowns': {'exact_r3035_generator_source': None},
         'conclusion_zh': '一条 menu_select 独立生成五个操作及一次零时长自转移；旧五步仅作事后粗粒度对照。'},
        {'id': '03_geometry', 'title_zh': '控件几何与坐标规则', 'status': 'VERIFIED_WITH_SCOPE_LIMIT',
         'evidence': {'retained_widget_count': len(geometry), 'records': geometry,
                      'target_rule': 'x + floor(width/2), y + floor(height/2)',
                      'rule_source': 'fixed 2014 cogtool-actr.lisp:934-946; not verified against r3035',
                      'selected_parent_target': [64.0, 313.0], 'selected_item_target': [123.0, 352.5]},
         'unknowns': {'r3035_visual_target_rule': None},
         'conclusion_zh': '10 个控件原始矩形全部保留；两目标点遵循固定 2014 floor 规则。'},
        {'id': '04_menu_actions', 'title_zh': '右键打开和左键选项', 'status': 'VERIFIED_WITH_SCOPE_LIMIT',
         'evidence': {'original_demonstrated_action': action, 'transition_object_id': '25',
                      'menu_item_object_id': '22', 'parent_context_object_id': '8',
                      'explicit_context_action_override': extraction['demonstration_steps'][0]['menu_attribute_evidence'][0]['explicit_context_menu_action'],
                      'python_parent_action': 'right_click', 'python_selection_action': 'click',
                      'right_click_default_source': 'fixed 2014 WidgetAttributes.java:333-347,453-455',
                      'initially_closed_menu': 'restricted baseline generator contract; not a separately saved menu-open field'},
         'unknowns': {'r3035_context_default_source': None},
         'conclusion_zh': '左键点击来自动作 24；右键打开取 2014 缺省规则，旧步骤 297 可独立佐证动作标签。'},
        {'id': '05_initial_state', 'title_zh': '鼠标、双手和视觉初态', 'status': 'PARTIALLY_VERIFIED',
         'evidence': {'original_saved': extraction['initial_saved'],
                      'original_saved_last_widget_references': extraction['initial_widget_references'],
                      'python_initial': candidate['tasks'][0]['demonstration']['initial'],
                      'conditional_mouse_source': extraction['initial_derived'],
                      'dual_hand_scope': 'Saved right=M,left=K retained in audit; baseline models active mouse hand only; no left-hand operation occurs',
                      'visual_scope': 'Null lastLookedAtWidget does not establish ACT-R eye coordinates, visual attention, or zero visual latency'},
         'unknowns': {'original_2009_mouse_position': None, 'original_eye_position': None,
                      'original_visual_attention_state': None, 'original_keyboard_focus': None},
         'conclusion_zh': '手位来自保存值；鼠标 (0,0) 为 2014 条件假设；2009 鼠标和视觉模块初态未知。'},
        {'id': '06_think_and_lookat', 'title_zh': 'Think、LookAt 的显式与自动来源', 'status': 'VERIFIED_WITH_SCOPE_LIMIT',
         'evidence': {'demonstrated_think_count': 0, 'demonstrated_lookat_count': 0,
                      'archived_generated_think_object_id': '300', 'archived_think_s': 1.2,
                      'python_think_steps': [s for s in current_steps if s['op'] == 'think'],
                      'python_lookat_count': sum(s['op'] == 'look_at' for s in current_steps),
                      'python_think_parameter': baseline_result['parameters']['think_s'],
                      'archived_think_used_as_input': False,
                      'caution': 'No LookAt demonstration does not imply absence of automatic ACT-R/EMMA visual processing'},
         'unknowns': {'r3035_automatic_visual_processing_reimplementation': None},
         'conclusion_zh': '示范没有 Think/LookAt；Think 由规则自动生成，1.2 秒取参数默认；未补造视觉时长。'},
        {'id': '07_parameters', 'title_zh': '参数来源和 2009 未知项', 'status': 'PARTIALLY_VERIFIED',
         'evidence': {'input_assumption_profile': assumption_profile,
                      'effective_baseline_parameters': baseline_result['parameters'],
                      'source_default_applicability': 'Upstream defaults/components refer to fixed 2014 source only, not proven 2009 defaults',
                      'archived_parameters_path': str(version_path),
                      'archived_parameter_count': len(versions['saved_trace_parameters']),
                      'archived_parameters_used_for_candidate': False,
                      'full_input_unchanged': comparison},
         'unknowns': {'complete_verified_r3035_parameter_source': None, 'original_current_rerun_s': None},
         'conclusion_zh': 'click/key/home 沿用原示例假设，未调参；旧 116 条参数仅历史参考；完整原版配置未确认。'},
        {'id': '08_boundaries_wait', 'title_zh': '开始、结束及等待边界', 'status': 'VERIFIED_WITH_SCOPE_LIMIT',
         'evidence': {'source_start_frame_object_id': '6', 'source_destination_frame_object_id': '6',
                      'source_transition_object_id': '25', 'source_transition_delay_s': extraction['demonstration_steps'][0]['delay_s'],
                      'candidate_transition': candidate['design']['transitions'],
                      'python_timing_boundary': baseline_result['timing_boundary'],
                      'python_wait_step_count': sum(s['op'] == 'wait' for s in current_steps),
                      'python_final_transition': current_steps[-1],
                      'system_wait_added': False, 'end_user_trial_completion_inferred': False},
         'unknowns': {'independently_verified_r3035_run_boundary': None, 'human_trial_boundary_alignment': None},
         'conclusion_zh': '从 f6 开始并自转移回 f6，原 delay=0；保留零时长转移，没有添加等待或人类试验终点。'},
    ]
    if {name: file_record(path) for name, path in paths.items()} != before:
        raise ConversionError('Retained baseline evidence changed during this read-only audit')
    out.mkdir(parents=True)
    write(out / 'candidate_input.json', candidate)
    write(out / 'extraction.json', {**extraction, 'source': provenance})
    write(out / 'field_mapping.json', {'fields': mappings, 'source_rules': source_rules()})
    write(out / 'python_generated_steps.json', {'computed_by': 'cogtool_py.generator.generate',
                                               'timing_engine_executed': False, 'steps': current_steps})
    write(out / 'step_mapping.json', {'mapping': step_map, 'python_extra_zero_transition': current_steps[-1]})
    write(out / 'numeric_input_fields.json', numeric_fields(candidate))
    result = {'case_id': 'NP-B1', 'status': 'INPUT_UNCHANGED_PROVENANCE_NARROWED',
              'original_equivalence_claim': False, 'original_rerun_s': None,
              'input_comparison': comparison, 'checks': items,
              'source_provenance': provenance, 'retained_baseline_files': before,
              'version_audit_file': file_record(version_path), 'retained_baseline_files_unchanged': True,
              'input_values_changed': False, 'source_interpretation_corrected': True,
              'correction_zh': '(0,0) 从泛称上游初态收窄为固定 2014 源码条件默认；2009 r3035 初态与对应源码仍未知。',
              'scope': 'NP-B1 only; no NP-A1 conversion, backend launch, timing computation, fitting, or cached trace replay'}
    write(out / 'audit.json', result)
    lines = ['# NP-B1 输入审计', '',
             '输入结构和值未改变；当前重新构造的输入与本轮保留基线严格一致。只更正初始鼠标 (0,0) 的来源解释：它是固定 2014 源码的条件默认，2009 r3035 初态仍未知。', '',
             f'规范输入哈希：`{comparison["current_normalized_input_sha256"]}`。原始 JSON 的规范哈希和全部 {comparison["numeric_field_count"]} 个数值字段（含类型）均一致，重新生成的 Python 步骤与保留基线一致。', '',
             '| 核对项 | 状态 | 结论 |', '|---|---|---|']
    lines += [f'| {item["title_zh"]} | {item["status"]} | {item["conclusion_zh"]} |' for item in items]
    lines += ['', '| 原示范 | 旧生成对象 | Python 步骤 | 对照范围 |', '|---|---|---|---|']
    lines += [f'| 287 | {row["archived_step_object_id"]} | {row["python_step_index"]}: {row["python_op"]} {row["python_target"] or ""} | 仅操作身份 |' for row in step_map]
    lines += ['| 287/转移25 | 同末步转移 | 5: transition f6→f6 | 零时长状态提交 |', '',
              '旧步骤 297 的 demonstrated=true、insertedByUser=false；这不代表另有一条用户示范。原始示范集合仍只有对象 287。Python 按自己的生成来源标为 automatic，两种字段不直接等同。', '',
              '本次只做读取、对象转换和步骤生成，没有运行计时引擎、原版后端或 NP-A1。历史总时间/轨迹不进入输入；未知字段保留 null；局部步骤一致不构成时间等价。']
    (out / 'AUDIT_zh.md').write_text('\n'.join(lines) + '\n')
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--baseline-dir', type=Path)
    parser.add_argument('--version-audit', type=Path)
    args = parser.parse_args()
    run = args.out.resolve().parent
    baseline = args.baseline_dir or run / 'baseline/repair_validation/official/NP-B1'
    version = args.version_audit or run / 'reference_routes/npb1_version_audit.json'
    started = time.perf_counter()
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        result = audit(args.out, baseline, version)
    except (ConversionError, ModelError, OSError, KeyError, ValueError) as exc:
        print(f'NP-B1 input audit failed: {exc}', file=sys.stderr)
        return 2
    write(args.out / 'invocation.json', {'command': [sys.executable, *sys.argv], 'cwd': str(Path.cwd()),
                                       'started_at_utc': timestamp, 'wall_clock_runtime_s': time.perf_counter() - started,
                                       'returncode': 0})
    print(json.dumps({'status': result['status'], 'checks': len(result['checks']),
                      'input_sha256': result['input_comparison']['current_normalized_input_sha256']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

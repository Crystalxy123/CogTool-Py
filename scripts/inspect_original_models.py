#!/usr/bin/env python3
"""Read-only, bounded inspection of two pinned original CogTool model archives.

This is diagnostic inventory, NOT a .cgt importer, evaluator, or prediction engine.
No Java serialization is executed, no XML entities are resolved, and ZIP contents
are only read in memory. Cached legacy predictions are labelled and never reused.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DOC_COMMIT = '1f5fe10e2bebfb7544aa85a6db2c10078df9f9d3'
CODE_COMMIT = 'a91d91e8dcf95d762b6e08020029a36ea079bbba'
DOC_ROOT = ROOT / 'reference/upstream-documentation'
SOURCE = ROOT / 'reference/upstream-cogtool'
MODELS = [
    ('NP4', 'examples/phone-number-lookup/N&P93.cgt.zip'),
    ('PR11', 'examples/command-line-v-eclispe/PERCS_CLI_PTP_Comparison_20091216_1513.cgt'),
]
MAX_BYTES = 64 * 1024 * 1024
BUTTONS = {'0': 'left', '1': 'right', '2': 'middle'}
PRESSES = {'0': 'click', '1': 'down', '2': 'up', '3': 'double', '4': 'hover', '5': 'triple'}
ASCII_KEYS = set("qwertasdfgzxcvb12345` yuiophjklnm67890-=[]\\;',./")
CASE_IDS = {
    ('Dialog Box', 'Look up one number'): 'NP-A1',
    ('Dialog Box', 'Look up two numbers'): 'NP-A2',
    ('Pop-Up', 'Look up one number'): 'NP-B1',
    ('Pop-Up', 'Look up two numbers'): 'NP-B2',
    ('Command Line', 'HelloWorld_mpi with keyboard'): 'PR-HW-K',
    ('Command Line', 'HelloWorld_mpi with mouse'): 'PR-HW-M',
    ('PTP-Eclipse', 'HelloWorld_mpi with mouse'): 'PR-HW-E',
    ('Command Line', 'F1 Help with keyboard'): 'PR-F1-K',
    ('Command Line', 'F1 Help with mouse'): 'PR-F1-M',
    ('PTP-Eclipse', 'F1 Help with mouse'): 'PR-F1-E',
    ('Command Line', 'Code folding with keyboard'): 'PR-CF-K',
    ('Command Line', 'Code folding with mouse'): 'PR-CF-M',
    ('PTP-Eclipse', 'Code folding with mouse'): 'PR-CF-E',
    ('Command Line', 'Barrier Analysis'): 'PR-BA-C',
    ('PTP-Eclipse', 'Barrier Analysis'): 'PR-BA-E',
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def classname(node: ET.Element | None) -> str | None:
    return node.get('class', '').rsplit('.', 1)[-1] if node is not None else None


def field(node: ET.Element | None, var: str) -> ET.Element | None:
    if node is not None:
        for child in node:
            if child.get('var') == var:
                return child
            if child.tag == 'sup':
                found = field(child, var)
                if found is not None:
                    return found
    return None


def scalar(node: ET.Element | None):
    if node is None or node.tag == 'null':
        return None
    if node.tag in ('str', 'char'):
        text = node.text or ''
        # ObjectLoader.java:2193-2200 removes ObjectSaver's trailing sentinel.
        if not text.endswith('@'):
            raise ValueError('Persistence string lacks expected @ sentinel')
        return text[:-1]
    if node.tag == 'bool':
        return node.get('val') == 't'
    if node.tag == 'int':
        return int(node.get('val'))
    if node.tag == 'dbl':
        return float(node.get('val'))
    if node.tag == 'enum':
        return node.get('val')
    return None


class Graph:
    """Only inspect explicit fields and idrefs; never instantiate persisted classes."""
    def __init__(self, root: ET.Element):
        self.root = root
        self.index = {}
        for node in root.iter():
            ident = node.get('id')
            if ident:
                if ident in self.index:
                    raise ValueError(f'duplicate persistence id: {ident}')
                self.index[ident] = node

    def resolve(self, node: ET.Element | None) -> ET.Element | None:
        if node is not None and node.tag == 'ref':
            return self.index[node.get('idref')]
        return node

    def get(self, node: ET.Element | None, var: str) -> ET.Element | None:
        return self.resolve(field(node, var))

    def name(self, node: ET.Element | None):
        return scalar(field(self.resolve(node), 'name'))

    def value(self, node: ET.Element | None, var: str):
        return scalar(field(node, var))

    def entries(self, node: ET.Element | None):
        return [self.resolve(child) for child in node] if node is not None else []

    def target(self, node: ET.Element | None) -> dict | None:
        node = self.resolve(node)
        if node is None or node.tag == 'null':
            return None
        shape = self.get(node, 'shape')
        rect = self.get(shape, 'r')
        return {'object_id': node.get('id'), 'class': classname(node), 'name': self.name(node),
                'title': self.value(node, 'title'),
                'geometry': {k: self.value(rect, k) for k in ('x', 'y', 'width', 'height')} if rect is not None else None}

    def action(self, node: ET.Element | None) -> dict | None:
        node = self.resolve(node)
        if node is None:
            return None
        result = {'class': classname(node), 'object_id': node.get('id')}
        for key in ('text', 'isCommand', 'button', 'pressType', 'modifiers', 'homeTarget', 'whichHand'):
            if field(node, key) is not None:
                result[key] = self.value(node, key)
        if classname(node) == 'ButtonAction':
            result['button_name'] = BUTTONS.get(result.get('button'), 'unknown') if result.get('button') is not None else None
            result['press_type_name'] = PRESSES.get(result.get('pressType'), 'unknown')
        if 'text' in result:
            result['non_ascii_codepoints'] = sorted({f'U+{ord(c):04X}' for c in result['text'] if ord(c) > 127})
            result['unsupported_ascii_characters'] = sorted({c for c in result['text'] if ord(c) < 128 and c not in ASCII_KEYS})
        return result

    def step(self, node: ET.Element) -> dict:
        node = self.resolve(node)
        result = {'object_id': node.get('id'), 'class': classname(node),
                  'current_frame': self.name(self.get(node, 'currentFrame')),
                  'demonstrated': self.value(node, 'demonstrated'),
                  'inserted_by_user': self.value(node, 'insertedByUser'),
                  'owner_object_id': self.get(node, 'owner').get('id') if self.get(node, 'owner') is not None else None}
        if classname(node) == 'TransitionScriptStep':
            transition = self.get(node, 'transition')
            result.update(transition_object_id=transition.get('id'),
                          destination_frame=self.name(self.get(transition, 'destination')),
                          target=self.target(self.get(transition, 'source')),
                          action=self.action(self.get(transition, 'action')),
                          delay_s=self.value(transition, 'delayInSecs'))
        elif classname(node) == 'ActionScriptStep':
            result.update(target=self.target(self.get(node, 'source')), action=self.action(self.get(node, 'action')),
                          delay_s=self.value(node, 'delayInSecs'))
        elif classname(node) == 'LookAtScriptStep':
            result.update(target=self.target(self.get(node, 'lookAtTarget')), duration_s=None)
        elif classname(node) == 'ThinkScriptStep':
            result.update(duration_s=self.value(node, 'duration'), label=self.value(node, 'label'))
        elif classname(node) == 'TextActionSegment':
            result.update(text=self.value(node, 'text'))
        return result


def safe_member(z: zipfile.ZipFile, member: str, inventory: list) -> bytes:
    infos = z.infolist()
    if len(infos) > 128 or len({i.filename for i in infos}) != len(infos):
        raise ValueError('unexpected or duplicate ZIP entries')
    if any(Path(i.filename).is_absolute() or '..' in Path(i.filename).parts for i in infos):
        raise ValueError('unsafe ZIP name')
    if sum(i.file_size for i in infos) > MAX_BYTES:
        raise ValueError('ZIP declared expansion exceeds 64 MiB bound')
    inventory.append([{'name': i.filename, 'uncompressed_bytes': i.file_size,
                       'compressed_bytes': i.compress_size, 'crc32': f'{i.CRC:08x}'} for i in infos])
    target = z.getinfo(member)
    if target.flag_bits & 1 or target.file_size > MAX_BYTES:
        raise ValueError('encrypted or oversized member')
    with z.open(target) as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES or len(data) != target.file_size:
        raise ValueError('ZIP expansion length mismatch')
    return data


def required_unsupported(steps: list[dict], generated: list[dict]) -> list[str]:
    unsupported = {'original_cgt_importer_absent', 'actr_resource_scheduling_and_generated_think_rules'}
    for step in steps + generated:
        if step.get('class') == 'LookAtScriptStep':
            unsupported.add('target_only_look_at_requires_original_visual_timing_not_explicit_baseline_duration')
        target = step.get('target') or {}
        if target.get('class') in {'ContextMenu', 'MenuItem', 'MenuHeader'}:
            unsupported.add('hierarchical_menu_and_context_menu_generation')
        action = step.get('action') or {}
        if action.get('class') == 'KeyAction':
            if action.get('non_ascii_codepoints'):
                unsupported.add('original_private_use_key_encoding_requires_audited_translation')
            if action.get('unsupported_ascii_characters'):
                unsupported.add('shifted_uppercase_or_other_unsupported_physical_keys')
            if action.get('modifiers'):
                unsupported.add('modifier_chords')
            if step.get('destination_frame') and step.get('destination_frame') != step.get('current_frame'):
                unsupported.add('keyboard_triggered_frame_transition')
        if action.get('class') == 'ButtonAction':
            if action.get('button_name') not in ('left', None):
                unsupported.add('mouse_button_' + str(action.get('button_name')))
            if action.get('press_type_name') != 'click':
                unsupported.add('mouse_press_' + str(action.get('press_type_name')))
            if action.get('modifiers'):
                unsupported.add('modifier_chords')
    return sorted(unsupported)


def inspect_model(group: str, relative: str) -> dict:
    path = DOC_ROOT / relative
    data = path.read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError('model exceeds inspection size bound')
    expected_blob = subprocess.check_output(['git', '-C', str(ROOT / 'documentation'), 'rev-parse',
                                            f'{DOC_COMMIT}:{relative}'], text=True).strip()
    actual_blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    if actual_blob != expected_blob:
        raise ValueError(f'fixed Git blob mismatch: {relative}')
    layers = []
    with zipfile.ZipFile(BytesIO(data)) as outer:
        if relative.endswith('.zip'):
            inner = safe_member(outer, 'N&P93.cgt', layers)
            with zipfile.ZipFile(BytesIO(inner)) as archive:
                persist = safe_member(archive, 'PERSIST', layers)
        else:
            inner = data
            persist = safe_member(outer, 'PERSIST', layers)
    if b'<!DOCTYPE' in persist.upper() or b'<!ENTITY' in persist.upper():
        raise ValueError('XML DTD/entity declarations are forbidden')
    root = ET.fromstring(persist)
    if root.tag != 'persist':
        raise ValueError('not CogTool persistence XML')
    graph = Graph(root)
    project = next(node for node in root.iter('obj') if classname(node) == 'Project')
    designs = [{'object_id': node.get('id'), 'name': graph.name(node),
                'frame_count': len(graph.entries(graph.get(node, 'frames')))}
               for node in root.iter('obj') if classname(node) == 'Design']
    task_groups = {child.get('id'): graph.name(node)
                   for node in root.iter('obj') if classname(node) == 'TaskGroup'
                   for child in graph.entries(graph.get(node, 'children'))}
    apps = []
    for app in root.iter('obj'):
        if classname(app) != 'TaskApplication':
            continue
        task = graph.get(app, 'task')
        demo = graph.get(app, 'demonstration')
        demo_steps = [graph.step(node) for node in graph.entries(graph.get(demo, 'steps'))]
        scripts = [node for node in app.iter('obj') if classname(node) == 'Script']
        generated = [graph.step(graph.get(state, 'forStep')) for script in scripts
                     for state in graph.entries(graph.get(script, 'stepStates'))]
        cached = [node for node in app.iter('obj') if classname(node) == 'TimePredictionResult']
        task_name = graph.name(task)
        method = 'keyboard' if task_name.endswith('with keyboard') else ('mouse' if task_name.endswith('with mouse') else graph.name(graph.get(app, 'design')))
        initial = graph.get(demo, 'initialState')
        apps.append({
            'source_task_application_object_id': app.get('id'),
            'source_design': graph.name(graph.get(app, 'design')), 'source_task': task_name,
            'source_task_group': task_groups.get(task.get('id')), 'method': method,
            'start_frame': graph.name(graph.get(demo, 'startFrame')),
            'start_frame_chosen': graph.value(demo, 'startFrameChosen'),
            'initial_state_saved': {key: graph.value(initial, key) for key in ('mouseHand', 'rightHandLoc', 'leftHandLoc', 'modifiers')},
            'initial_mouse_coordinates': None,
            'demonstration_step_count': len(demo_steps), 'generated_step_count': len(generated),
            'demonstration_steps': demo_steps, 'saved_generated_steps': generated,
            'required_unsupported': required_unsupported(demo_steps, generated) if demo_steps else ['empty_original_demonstration'],
            'cached_prediction_s': graph.value(cached[0], 'taskTime') if len(cached) == 1 else None,
            'cached_prediction_object_id': cached[0].get('id') if len(cached) == 1 else None,
            'cached_prediction_origin': 'saved_legacy_TimePredictionResult.taskTime; NOT recomputed, NOT validation reference',
            'cached_prediction_unit_evidence': 'reference/upstream-cogtool/java/edu/cmu/cs/hcii/cogtool/model/TimePredictionResult.java:100 (seconds), :124 (saveDouble taskTime)',
            'cached_prediction_count': len(cached),
            'cached_result_step_count': sum(classname(node) == 'ResultStep' for node in app.iter('obj')),
        })
    return {'group_id': group, 'source_model_path': str(path.relative_to(ROOT)),
            'source_model_hash': sha(data), 'source_bytes': len(data),
            'source_repository': 'https://github.com/cogtool/documentation', 'source_commit': DOC_COMMIT,
            'source_git_blob': expected_blob, 'verified_git_blob': actual_blob, 'git_blob_verified': True,
            'archive_layers': layers, 'inner_model_sha256': sha(inner),
            'persist_sha256': sha(persist), 'persist_bytes': len(persist),
            'persist_metadata': root.attrib, 'project_name': graph.name(project),
            'designs': designs, 'task_applications': apps,
            'saved_source_version_differs_from_current_reference': True,
            'inspection_scope': 'read-only fields/idrefs only; not a supported .cgt loader'}


def attempt(out: Path, name: str, args: list[str], cwd: Path, timeout: int = 30) -> dict:
    logs = out / 'logs/original'
    logs.mkdir(parents=True, exist_ok=True)
    record = {'id': name, 'command': args, 'cwd': str(cwd), 'started_at_utc': now()}
    try:
        completed = subprocess.run(args, cwd=cwd, capture_output=True, text=True, errors='replace', timeout=timeout)
        stdout, stderr = completed.stdout, completed.stderr
        record.update(returncode=completed.returncode, outcome='completed')
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or b'').decode(errors='replace') if isinstance(exc.stdout, bytes) else (exc.stdout or '')
        stderr = (exc.stderr or b'').decode(errors='replace') if isinstance(exc.stderr, bytes) else (exc.stderr or '')
        record.update(returncode=None, outcome='timeout', exception=str(exc))
    except OSError as exc:
        stdout, stderr = '', ''
        record.update(returncode=None, outcome=type(exc).__name__, exception=str(exc))
    for stream, text in [('stdout', stdout), ('stderr', stderr)]:
        path = logs / f'{name}.{stream}.txt'
        path.write_text(text, encoding='utf-8')
        record[stream + '_path'] = str(path.relative_to(out))
        record[stream + '_sha256'] = sha(path.read_bytes())
    record['finished_at_utc'] = now()
    save(logs / f'{name}.json', record)
    return record


def diagnose(out: Path) -> dict:
    build = out / 'diagnostics/original-build'
    build.mkdir(parents=True, exist_ok=True)
    commands = [
        ('01_os', ['/usr/bin/sw_vers']),
        ('02_architecture', ['/usr/bin/uname', '-a']),
        ('03_java_installations', ['/usr/libexec/java_home', '-V']),
        ('04_java_version', ['/usr/bin/java', '-version']),
        ('05_ant_version', ['/bin/zsh', '-c', 'ant -version']),
        ('06_clisp_architecture', ['/usr/bin/file', str(SOURCE / 'clisp-mac-intel/lisp.run')]),
        ('07_compile_fixed_source', ['/bin/zsh', '-c', 'exec ant "$@"', 'ant', '-f', str(SOURCE / 'build.xml'),
                                    '-Dbuilddir=' + str(build), '-Ddistdir=' + str(out / 'diagnostics/original-dist'), 'compile']),
        ('08_launch_original_java', ['/usr/bin/java', '-d32', '-XstartOnFirstThread', '-Xmx400000000',
                                     '-classpath', str(build) + ':' + str(SOURCE / 'lib/*') + ':' + str(SOURCE / 'lib/macintosh/swt.jar'),
                                     'edu.cmu.cs.hcii.cogtool.CogTool', '-help']),
        ('09_launch_bundled_clisp', ['/bin/zsh', '-c', 'exec "$@"', 'original-clisp',
                                    str(SOURCE / 'clisp-mac-intel/lisp.run'), '-M', str(SOURCE / 'clisp-mac-intel/actr6.mem'),
                                    '-x', '(progn (print :runtime-started) (ext:quit))']),
    ]
    records = [attempt(out, name, cmd, build) for name, cmd in commands]
    blocked = any(record['returncode'] != 0 for record in records[-3:])
    return {'schema_version': 1, 'created_at_utc': now(), 'source_commit': CODE_COMMIT,
            'status': 'original_run_blocked' if blocked else 'runtime_probes_only_no_task_prediction', 'original_prediction_generated': False,
            'platform': platform.platform(), 'machine': platform.machine(), 'python': sys.version,
            'attempts': records,
            'limitations': ['compile and startup attempted only; no original task prediction obtained',
                            'saved 2009 caches are not current-reference results',
                            'existing CogTool.dmg not used because source-build correspondence is unproved'],
            'required_environment': 'Compatible 32-bit legacy JVM/SWT and i386 CLISP; upstream build.xml targets Java 1.5. No replacement runtime or source modifications attempted.',
            'artifact_hashes': {str(path.relative_to(ROOT)): sha(path.read_bytes()) for path in [
                SOURCE / 'build.xml', SOURCE / 'clisp-mac-intel/lisp.run', SOURCE / 'clisp-mac-intel/actr6.mem']}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='A new report run directory')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    catalog_path = ROOT / '实验数据/CogTool_reference_catalog.json'
    catalog = json.loads(catalog_path.read_text(encoding='utf-8'))
    expected_ids = {row['case_id'] for row in catalog['official_and_developer_published_results']
                    if row['case_id'].startswith(('NP-', 'PR-'))}
    if set(CASE_IDS.values()) != expected_ids:
        raise ValueError('Explicit original task mapping no longer matches reference catalog case IDs')
    models = [inspect_model(group, rel) for group, rel in MODELS]
    mapped = []
    empty = []
    for model in models:
        active = [app for app in model['task_applications'] if app['demonstration_step_count']]
        for app in active:
            mapped.append({
                'case_id': CASE_IDS[(app['source_design'], app['source_task'])], 'group_id': model['group_id'],
                'source_model_path': model['source_model_path'], 'source_model_hash': model['source_model_hash'],
                'source_commit': model['source_commit'], 'source_git_blob': model['source_git_blob'],
                'source_design': app['source_design'], 'source_task': app['source_task'], 'method': app['method'],
                'source_task_application_object_id': app['source_task_application_object_id'],
                'demonstration_step_count': app['demonstration_step_count'],
                'generated_step_count': app['generated_step_count'],
                'start_frame': app['start_frame'], 'initial_state_saved': app['initial_state_saved'],
                'initial_mouse_coordinates': None,
                'geometry_evidence': [step['target'] for step in app['demonstration_steps']
                                      if step.get('target') is not None],
                'parameter_evidence': {
                    'complete_parameter_set_recovered': False,
                    'saved_generated_think_durations_s': sorted({s['duration_s'] for s in app['saved_generated_steps']
                                                              if s['class'] == 'ThinkScriptStep'}),
                    'saved_demonstration_delays_s': [s['delay_s'] for s in app['demonstration_steps'] if 'delay_s' in s],
                    'note': 'Only explicitly serialized values are recorded; no defaults or LookAt durations inferred.'},
                'input_alignment': 'original_model_available_not_converted_or_aligned',
                'required_unsupported': app['required_unsupported'],
                'reason': 'Official original input is available and Git-verified, but current Python core has no .cgt importer, original state/geometry/key encodings have not been aligned, and listed operations or ACT-R scheduling are unsupported. Legacy cached prediction is not a new computation.',
                'cached_prediction_s': app['cached_prediction_s'],
                'cached_prediction_object_id': app['cached_prediction_object_id'],
                'cached_prediction_source_version': model['persist_metadata'],
                'cached_prediction_use': 'inventory_only_do_not_compute_errors_or_claim_validation',
                'python_prediction_s': None, 'original_rerun_prediction_s': None,
            })
        empty.extend({'group_id': model['group_id'], 'source_design': app['source_design'],
                      'source_task': app['source_task'], 'source_task_application_object_id': app['source_task_application_object_id'],
                      'reason': 'Saved TaskApplication has zero demonstration steps, no result, and startFrameChosen=false'}
                     for app in model['task_applications'] if not app['demonstration_step_count'])
    catalog_order = {row['case_id']: index for index, row in enumerate(catalog['official_and_developer_published_results'])}
    mapped.sort(key=lambda row: catalog_order[row['case_id']])
    inventory = {'schema_version': 1, 'created_at_utc': now(), 'status': 'read_only_inventory',
                 'fixed_source_commit': CODE_COMMIT, 'fixed_documentation_commit': DOC_COMMIT,
                 'reference_catalog_path': str(catalog_path.relative_to(ROOT)),
                 'reference_catalog_sha256': sha(catalog_path.read_bytes()),
                 'models': models, 'mapped_records': mapped, 'empty_methods': empty,
                 'not_a_cgt_importer': True, 'cached_values_used_for_computation': False}
    save(out / 'reference/model_inventory.json', inventory)
    environment = diagnose(out)
    save(out / 'diagnostics/original_environment.json', environment)
    lines = ['# 官方模型只读取证', '',
             f'固定文档 commit：`{DOC_COMMIT}`；当前代码参考 commit：`{CODE_COMMIT}`。', '',
             '这是 ZIP/PERSIST/XML 的只读库存。未建立 `.cgt` 导入器，未运行预测，未将旧缓存填入 Python 结果。ZIP 读取限制为 64 MiB，拒绝不安全路径、重复成员、DTD/实体声明；没有实例化持久化 Java 类。', '',
             '两个模型均以现有 Git 仓库固定 commit 的路径 blob 与实际文件重新核对。字节 SHA-256、Git blob、PERSIST 哈希及保存元数据见 `model_inventory.json`。', '',
             '| 分组 | 文件保存版本 | 已建模方法 | 空方法 |', '|---|---|---:|---:|']
    for model in models:
        attrs = model['persist_metadata']
        lines.append(f"| {model['group_id']} | {attrs.get('cogtool_version')} r{attrs.get('cogtool_revision')} / {attrs.get('cogtool_buildtime')} | {sum(bool(a['demonstration_step_count']) for a in model['task_applications'])} | {sum(not a['demonstration_step_count'] for a in model['task_applications'])} |")
    lines += ['', '## 真实设计与方法映射', '',
              '以下秒数仅是原文件中明确识别的 `TimePredictionResult.taskTime` 旧缓存；它们既不是本次重跑，也不是本次 Python 计算，不用于误差统计。case_id 与实验数据/CogTool_reference_catalog.json 精确绑定；绑定依据是原文件设计与任务名称。', '',
              '| 库存编号 | 设计 | 任务 | 旧缓存秒数 | 必须补齐的支持 |', '|---|---|---|---:|---|']
    for row in mapped:
        lines.append(f"| {row['case_id']} | {row['source_design']} | {row['source_task']} | {row['cached_prediction_s']} | {', '.join(row['required_unsupported'])} |")
    lines += ['', '## 原版实际启动尝试', '',
              '当前环境的探测、固定源码编译、Java 主类启动及附带 CLISP 启动命令逐条记录在 `logs/original/`；每项含返回码、stdout/stderr及其哈希。完整诊断位于 `diagnostics/original_environment.json`。', '',
              '原版任务没有成功计算。旧缓存保存自2009年版本，当前参考源码来自2014年，不可混为同版本差分结果。现有 CogTool.dmg 未使用，因为尚未证明构建源码对应。', '',
              '当前必须补齐：经过核对的原版输入转换、缺失操作与层级菜单规则、按键编码、LookAt视觉时序及ACT-R资源调度。几何和初始状态未完全对齐前不得生成“完整官方案例”预测。', '',
              '序列化依据：固定代码 `util/ObjectPersister.java` 的 PERSIST/ZIP加载；`util/ObjectLoader.java` 的字符串尾部 @ 标记；`model/MouseButtonState.java`、`MousePressType.java` 的枚举。库存对文件中对象ID进行只读引用解析，不承诺其他版本和结构可导入。', '']
    (out / 'reference/MODELS_zh.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'models': len(models), 'mapped_records': len(mapped), 'empty_methods': len(empty),
                      'inventory': str(out / 'reference/model_inventory.json'), 'original_status': environment['status']}, ensure_ascii=False))


if __name__ == '__main__':
    main()

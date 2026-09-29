#!/usr/bin/env python3
"""Narrow read-only conversion of pinned NP-A1 / NP-B1 phone-model objects.

No generic .cgt import support is claimed. Archived generated steps and times are
saved as reference evidence only; candidate inputs derive from demonstrations,
widget parent references, geometry, and cited initialization/default rules.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.inspect_original_models import (  # noqa: E402
    CODE_COMMIT, DOC_COMMIT, Graph, classname, field, safe_member, scalar,
)

MODEL_REL = 'examples/phone-number-lookup/N&P93.cgt.zip'
MODEL_PATH = ROOT / 'reference/upstream-documentation' / MODEL_REL
MODEL_SHA256 = 'fed4f20a8139ff0f0d75b840d9600379d5851541a19d1e4c4d2c990c039d666a'
MODEL_BLOB = '1b25bede00fa52219571d43d751e12717a9d53a2'
KIND = {'0': 'noninteractive', '1': 'button', '2': 'menu_header', '3': 'submenu',
        '4': 'menu_item', '5': 'textbox', '13': 'link', '14': 'context_menu'}
SOURCE_RULES = [
    ('java/edu/cmu/cs/hcii/cogtool/resources/cogtool-actr.lisp', 'cogtool-run-model', '1137-1152', '2014 reference initializes mouse to (0,0); 2009 r3035 initial mouse remains unverified'),
    ('java/edu/cmu/cs/hcii/cogtool/resources/cogtool-actr.lisp', 'frame-vis-loc-template', '934-946', 'Visual target is x+floor(width/2),y+floor(height/2)'),
    ('java/edu/cmu/cs/hcii/cogtool/model/KLMCognitiveGenerator.java', 'produceMenuSteps/produceItemSteps', '1046-1218', 'Context parent move,right-click,Think,then item selection; nested submenu remains excluded'),
    ('java/edu/cmu/cs/hcii/cogtool/model/WidgetAttributes.java', 'CONTEXT_MENU_ACTION_ATTR/default registry', '333-347,453-455', 'Unspecified context-menu action defaults to right click'),
    ('java/edu/cmu/cs/hcii/cogtool/model/WidgetAttributes.java', 'SUBMENU_ACTION_ATTR/SUBMENU_DELAY_ATTR default registry', '303-330,443-450', 'Unspecified submenu action defaults to hover with zero extra delay'),
    ('java/edu/cmu/cs/hcii/cogtool/model/ACTRPredictionAlgo.java', 'startScriptOutput', '1413-1424', 'Saved mouse-hand location determines start-with-mouse'),
    ('java/edu/cmu/cs/hcii/cogtool/model/TimePredictionResult.java', 'taskTime/SAVER', '100-124', 'Archived taskTime is measured in seconds; never current computation'),
]


class ConversionError(ValueError):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def parse_persist(data: bytes) -> Graph:
    if len(data) > 4 * 1024 * 1024:
        raise ConversionError('Phone PERSIST exceeds narrow 4 MiB limit')
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ConversionError('DTD and entity declarations are forbidden')
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ConversionError('Malformed phone PERSIST XML') from exc
    if root.tag != 'persist' or root.get('version') != '2':
        raise ConversionError('Expected pinned CogTool persist version 2')
    try:
        graph = Graph(root)
    except ValueError as exc:
        raise ConversionError(f'Persistence object table: {exc}') from exc
    for node in root.iter('ref'):
        if node.get('idref') not in graph.index:
            raise ConversionError(f"Persistence field {node.get('var')!r} references missing object {node.get('idref')!r}")
    return graph


def read_phone(path: Path = MODEL_PATH) -> tuple[Graph, dict]:
    data = path.read_bytes()
    if sha(data) != MODEL_SHA256:
        raise ConversionError('Phone archive differs from pinned official SHA-256')
    expected = subprocess.check_output(['git', '-C', str(ROOT / 'documentation'), 'rev-parse',
                                        f'{DOC_COMMIT}:{MODEL_REL}'], text=True).strip()
    actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    if expected != MODEL_BLOB or actual != expected:
        raise ConversionError('Official archive does not match fixed Git blob')
    layers = []
    with zipfile.ZipFile(BytesIO(data)) as outer:
        inner = safe_member(outer, 'N&P93.cgt', layers)
    with zipfile.ZipFile(BytesIO(inner)) as archive:
        persist = safe_member(archive, 'PERSIST', layers)
    graph = parse_persist(persist)
    return graph, {'source_model_path': str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                   'source_sha256': sha(data), 'source_git_blob': actual, 'source_commit': DOC_COMMIT,
                   'source_repository': 'https://github.com/cogtool/documentation',
                   'persist_sha256': sha(persist), 'persist_metadata': graph.root.attrib,
                   'archive_layers': layers, 'read_only': True}


def source_rules() -> list[dict]:
    records = []
    for relative, symbol, lines, meaning in SOURCE_RULES:
        content = (ROOT / 'reference/upstream-cogtool' / relative).read_bytes()
        expected = subprocess.check_output(['git', '-C', str(ROOT / 'cogtool'), 'rev-parse',
                                            f'{CODE_COMMIT}:{relative}'], text=True).strip()
        actual = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
        if actual != expected:
            raise ConversionError(f'Rule source differs from fixed commit: {relative}')
        records.append({'repository': 'https://github.com/cogtool/cogtool', 'commit': CODE_COMMIT,
                        'path': relative, 'symbol': symbol, 'lines': lines, 'meaning': meaning,
                        'git_blob': expected, 'sha256': sha(content)})
    return records


def app_for(graph: Graph, design: str, task: str) -> ET.Element:
    matches = [n for n in graph.root.iter('obj') if classname(n) == 'TaskApplication'
               and graph.name(graph.get(n, 'design')) == design and graph.name(graph.get(n, 'task')) == task]
    if len(matches) != 1:
        raise ConversionError(f'Expected one task binding: {design} / {task}')
    return matches[0]


def parent_chain(graph: Graph, node: ET.Element) -> list[dict]:
    result, seen = [], set()
    current = node
    while current is not None and current.tag != 'null':
        ident = current.get('id')
        if ident in seen or len(seen) >= 16:
            raise ConversionError('Cyclic or unexpectedly deep widget parent chain')
        seen.add(ident)
        result.append(graph.target(current))
        current = graph.get(current, 'parent')
    return result


def baseline_parameters() -> tuple[dict, dict]:
    path = ROOT / 'examples/single_click.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    parameters = {}
    for name in ('click_s', 'key_s', 'homing_s'):
        entry = data['parameters'][name]
        parameters[name] = {key: entry[key] for key in ('value', 'unit', 'source')}
    return parameters, {'path': str(path.relative_to(ROOT)), 'sha256': sha(path.read_bytes()),
                        'use': 'Unchanged existing baseline assumptions; not extracted original motor times; not fitted to any result',
                        'values': copy.deepcopy(parameters)}


def widget(graph: Graph, node: ET.Element) -> dict:
    info = graph.target(node)
    if info is None or info['geometry'] is None:
        raise ConversionError('Required rectangular widget geometry is missing')
    rect = info['geometry']
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in rect.values()) or rect['width'] <= 0 or rect['height'] <= 0:
        raise ConversionError('Invalid source widget rectangle')
    parent = graph.get(node, 'parent')
    return {'id': 'w' + node.get('id'), 'name': info['name'], 'label': info['title'] or '',
            'kind': KIND.get(graph.value(node, 'widgetType'), 'unsupported_original_widget_type'),
            'parent': 'w' + parent.get('id') if parent is not None and parent.tag != 'null' else None, **rect}


def extract_case(graph: Graph, case_id: str) -> dict:
    if case_id not in ('NP-A1', 'NP-B1'):
        raise ConversionError('Only explicit NP-A1 and NP-B1 bindings are supported')
    design_name = 'Dialog Box' if case_id == 'NP-A1' else 'Pop-Up'
    app = app_for(graph, design_name, 'Look up one number')
    demo = graph.get(app, 'demonstration')
    initial = graph.get(demo, 'initialState')
    steps = graph.entries(graph.get(demo, 'steps'))
    records = []
    for index, node in enumerate(steps):
        record = graph.step(node)
        target = graph.get(graph.get(node, 'transition'), 'source') if classname(node) == 'TransitionScriptStep' else graph.get(node, 'lookAtTarget')
        record['demonstration_index'] = index
        record['target_parent_chain'] = parent_chain(graph, target) if target is not None and classname(target) != 'InputDevice' else []
        record['menu_attribute_evidence'] = [
            {'object_id': item['object_id'],
             'explicit_submenu_action': graph.value(graph.index[item['object_id']], 'WidgetType.submenuAction'),
             'explicit_submenu_delay_s': graph.value(graph.index[item['object_id']], 'WidgetType.submenuDelay'),
             'explicit_context_menu_action': graph.value(graph.index[item['object_id']], 'WidgetType.contextMenuAction'),
             'absent_value_policy': 'Use only the cited fixed source registry defaults; do not borrow cached timing.'}
            for item in record['target_parent_chain'] if item['class'] in {'MenuHeader', 'ContextMenu'}]
        records.append(record)
    return {'case_id': case_id, 'source_design': design_name, 'source_task': 'Look up one number',
            'task_application_object_id': app.get('id'), 'demonstration_object_id': demo.get('id'),
            'initial_state_object_id': initial.get('id'),
            'start_frame_object_id': graph.get(demo, 'startFrame').get('id'),
            'start_frame': graph.name(graph.get(demo, 'startFrame')),
            'initial_saved': {key: graph.value(initial, key) for key in ('mouseHand', 'rightHandLoc', 'leftHandLoc', 'modifiers')},
            'initial_widget_references': {key: graph.get(initial, key).get('id') if graph.get(initial, key) is not None else None
                                         for key in ('lastClickedWidget', 'lastMovedToWidget', 'lastLookedAtWidget')},
            'initial_derived': {'mouse': [0, 0], 'source': 'cogtool-actr.lisp:cogtool-run-model:1150-1151',
                                'source_version': '1.3-2014-02-10', 'source_commit': CODE_COMMIT,
                                'status': 'conditional_2014_default_not_verified_for_2009_r3035',
                                'archived_2009_mouse': None,
                                'focus': None, 'focus_note': 'No focus field saved; null does not affect NP-B1 which has no keyboard input'},
            'demonstration_steps': records,
            'not_used_to_construct_input': ['TimePredictionResult.taskTime', 'traceLines', 'saved Script.stepStates']}


def construct_candidate(graph: Graph, extraction: dict, parameters: dict) -> tuple[dict, list[dict], list[dict]]:
    case_id = extraction['case_id']
    frames: dict[str, dict] = {}
    mappings = []
    blockers = []
    demo_steps = []
    transitions = []
    for record in extraction['demonstration_steps']:
        node = graph.index[record['object_id']]
        frame = graph.get(node, 'currentFrame')
        frame_id = 'f' + frame.get('id')
        if frame_id not in frames:
            frames[frame_id] = {'id': frame_id, 'name': graph.name(frame), 'widgets': []}
        targets = [graph.index[t['object_id']] for t in record['target_parent_chain']]
        for target in targets:
            item = widget(graph, target)
            if not any(old['id'] == item['id'] for old in frames[frame_id]['widgets']):
                frames[frame_id]['widgets'].append(item)
                mappings.append({'python_field': f'design.frames[{frame_id}].widgets[{item["id"]}]',
                                 'source_object_id': target.get('id'), 'source_class': classname(target),
                                 'fields': {'name': 'ATransitionSource.name', 'label': 'Widget.title', 'kind': 'Widget.widgetType',
                                            'parent': 'MenuItem.parent idref', 'x/y/width/height': 'Widget.shape/AShape.r/DoubleRectangle'},
                                 'visual_target_from_source_rule': [item['x'] + math.floor(item['width'] / 2),
                                                                   item['y'] + math.floor(item['height'] / 2)]})
        index = record['demonstration_index']
        step_map = {'python_field': f'tasks[0].demonstration.steps[{index}]', 'source_object_id': node.get('id'),
                    'source_class': classname(node), 'meaning': 'One original demonstration step; generated cache is not replayed'}
        if classname(node) == 'LookAtScriptStep':
            demo_steps.append({'op': 'look_at', 'target': 'w' + record['target']['object_id'], 'duration_s': None})
            blockers.append({'demonstration_index': index, 'object_id': node.get('id'), 'field': 'duration_s',
                             'reason': 'Source LookAt has target only. Baseline requires explicit duration; no EMMA reconstruction or fabricated visual dwell is allowed.'})
        elif classname(node) == 'TransitionScriptStep':
            transition = graph.get(node, 'transition')
            action = graph.get(transition, 'action')
            target = graph.get(transition, 'source')
            destination = graph.get(transition, 'destination')
            if classname(action) == 'ButtonAction':
                if graph.value(action, 'button') != '0' or graph.value(action, 'pressType') != '0' or graph.value(action, 'modifiers') != 0:
                    raise ConversionError('Unexpected demonstration mouse action outside this narrow converter')
                op = 'menu_select' if classname(target) == 'MenuItem' else 'click'
                tid = 't' + transition.get('id')
                demo_steps.append({'op': op, 'target': 'w' + target.get('id'), 'transition': tid})
                transitions.append({'id': tid, 'from_frame': frame_id, 'target': 'w' + target.get('id'),
                                    'to_frame': 'f' + destination.get('id'), 'delay_s': graph.value(transition, 'delayInSecs')})
                frames.setdefault('f' + destination.get('id'), {'id': 'f' + destination.get('id'), 'name': graph.name(destination), 'widgets': []})
                if op == 'menu_select':
                    chain = record['target_parent_chain']
                    if len(chain) != 2 or chain[1]['class'] != 'ContextMenu':
                        blockers.append({'demonstration_index': index, 'object_id': node.get('id'), 'field': 'target.parent',
                                         'reason': 'Nested menu selection requires MenuHeader->submenu hover->leaf. Only direct ContextMenu->MenuItem is supported.',
                                         'parent_chain_object_ids': [c['object_id'] for c in chain]})
                    else:
                        parent = graph.index[chain[1]['object_id']]
                        explicit = graph.value(parent, 'WidgetType.contextMenuAction')
                        authority = graph.get(parent, 'authority')
                        if explicit not in (None, 0) or (authority is not None and authority.tag != 'null'):
                            raise ConversionError('Unsupported context-menu attribute/authority; cannot infer default right click')
                        step_map['parent_action'] = {'value': 'right_click', 'from': 'WidgetAttributes.java:453-455 default',
                                                     'parent_object_id': parent.get('id'), 'explicit_override': explicit}
                step_map['transition_object_id'] = transition.get('id')
            elif classname(action) == 'KeyAction':
                if graph.value(action, 'modifiers') != 0 or graph.value(action, 'pressType') != '0':
                    raise ConversionError('Unsupported original key modifiers/press type')
                text = graph.value(action, 'text')
                if any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-=[]\\;',./` " for c in text):
                    raise ConversionError('Key sequence contains unimplemented strokes')
                if destination.get('id') != frame.get('id') or graph.value(transition, 'delayInSecs') != 0:
                    raise ConversionError('Keyboard transition/wait cannot be silently dropped')
                demo_steps.append({'op': 'keys', 'keys': list(text)})
                step_map['transition_object_id'] = transition.get('id')
                step_map['self_transition_note'] = 'Same-frame keyboard transition with zero delay; key strokes preserve this state in baseline.'
            else:
                raise ConversionError('Unsupported original action class')
        else:
            raise ConversionError('Unexpected demonstration step class')
        mappings.append(step_map)
    # Preserve every widget in the actual NP-B1 start frame, including unselected
    # sibling items and the second context menu. They remain unexecuted.
    if case_id == 'NP-B1':
        start = graph.index[extraction['start_frame_object_id']]
        frames['f' + start.get('id')]['widgets'] = [widget(graph, n) for n in graph.entries(graph.get(start, 'widgets'))]
        known = {row.get('source_object_id') for row in mappings if 'widgets[' in row['python_field']}
        for target in graph.entries(graph.get(start, 'widgets')):
            if target.get('id') not in known:
                item = widget(graph, target)
                mappings.append({'python_field': f'design.frames[f{start.get("id")}].widgets[{item["id"]}]',
                                 'source_object_id': target.get('id'), 'source_class': classname(target),
                                 'fields': {'name': 'ATransitionSource.name', 'label': 'Widget.title', 'kind': 'Widget.widgetType',
                                            'parent': 'MenuItem.parent idref', 'x/y/width/height': 'Widget.shape/AShape.r/DoubleRectangle'},
                                 'note': 'Retained unselected original widget; never executed'})
    initial = extraction['initial_saved']
    if initial != {'mouseHand': True, 'rightHandLoc': 'M', 'leftHandLoc': 'K', 'modifiers': 0}:
        raise ConversionError('Unexpected phone initial state; no silent hand conversion')
    project = {'schema_version': 1, 'id': case_id + '-official-input-baseline',
               'name': case_id + ' official demonstration / serial baseline only', 'engine': 'klm_baseline',
               'parameters': copy.deepcopy(parameters),
               'design': {'id': 'phone-' + case_id, 'name': extraction['source_design'], 'coordinate_unit': 'px',
                          'frames': list(frames.values()), 'transitions': transitions},
               'tasks': [{'id': case_id, 'name': extraction['source_task'],
                          'demonstration': {'initial': {'frame': 'f' + extraction['start_frame_object_id'], 'mouse': [0, 0],
                                                       'mouse_hand': 'right', 'hand': 'mouse', 'focus': None},
                                            'steps': demo_steps}}]}
    mappings.append({'python_field': 'tasks[0].demonstration.initial', 'source_object_id': extraction['initial_state_object_id'],
                     'fields': {'frame': 'Demonstration.startFrame', 'mouse_hand/hand': 'mouseHand/rightHandLoc/leftHandLoc',
                                'mouse': '2014 source cogtool-run-model set-cursor-position 0 0; conditional diagnostic assumption, 2009 r3035 unverified', 'focus': 'unspecified; no effect for keyboard-free NP-B1'}})
    return project, mappings, blockers


def archive_reference(graph: Graph, extraction: dict, out: Path) -> dict:
    app = graph.index[extraction['task_application_object_id']]
    result = next(n for n in app.iter('obj') if classname(n) == 'TimePredictionResult')
    for field_name in ('traceLines', 'errorLines'):
        values = [scalar(n) for n in graph.entries(graph.get(result, field_name))]
        (out / ('archived_' + field_name + '.txt')).write_text('\n'.join(values) + '\n', encoding='utf-8')
    script = graph.get(result, 'script')
    generated = []
    for state in graph.entries(graph.get(script, 'stepStates')):
        node = graph.get(state, 'forStep')
        item = graph.step(node)
        if classname(node) == 'TextActionSegment':
            item['text'] = graph.value(node, 'segment')
        generated.append(item)
    return {'provenance': 'archived_reference', 'rerun': False, 'source_object_id': result.get('id'),
            'saved_version': graph.root.attrib, 'cached_prediction_s': graph.value(result, 'taskTime'),
            'saved_generated_steps': generated, 'used_for_input_or_prediction': False,
            'files': {name: {'path': name, 'sha256': sha((out / name).read_bytes())}
                      for name in ('archived_traceLines.txt', 'archived_errorLines.txt')}}


def run_python(project_path: Path, out: Path) -> dict:
    records = []
    for verb, args in [('validate', ['validate', str(project_path)]),
                       ('predict', ['predict', str(project_path), '--out', str(out / 'python_prediction')])]:
        command = [sys.executable, '-m', 'cogtool_py', *args]
        started = time.perf_counter()
        try:
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
            stdout, stderr = result.stdout, result.stderr
            returncode, outcome = result.returncode, 'completed'
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or b'').decode(errors='replace') if isinstance(exc.stdout, bytes) else (exc.stdout or '')
            stderr = (exc.stderr or b'').decode(errors='replace') if isinstance(exc.stderr, bytes) else (exc.stderr or '')
            returncode, outcome = None, 'timeout'
        wall_clock_runtime_s = time.perf_counter() - started
        (out / f'{verb}.stdout.txt').write_text(stdout)
        (out / f'{verb}.stderr.txt').write_text(stderr)
        record = {'command': command, 'returncode': returncode, 'outcome': outcome, 'timeout_seconds': 30,
                  'wall_clock_runtime_s': wall_clock_runtime_s, 'stdout_path': f'{verb}.stdout.txt',
                  'stderr_path': f'{verb}.stderr.txt', 'executed_at_utc': datetime.now(timezone.utc).isoformat()}
        write(out / f'{verb}.process.json', record)
        records.append(record)
        if outcome == 'timeout' or returncode != 0:
            return {'status': 'python_cli_timeout' if outcome == 'timeout' else 'python_core_rejected_candidate',
                    'diagnostic_python_prediction_s': None, 'processes': records}
    data = json.loads((out / 'python_prediction/result.json').read_text())
    return {'status': 'computed_serial_baseline', 'diagnostic_python_prediction_s': data['predicted_time_s'],
            'input_sha256': data['input_sha256'], 'engine': data['engine'], 'processes': records,
            'not_original_equivalence': True, 'not_human_accuracy_validation': True}


def convert(out: Path, *, run: bool = True, model_path: Path = MODEL_PATH) -> dict:
    out = out.resolve()
    if out == ROOT or any(out.is_relative_to(ROOT / protected) for protected in ('reference', 'cogtool', 'code', 'documentation', '实验数据', 'cogtool_py')):
        raise ConversionError('Output must not overwrite any source or user input directory')
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ConversionError(f'Output already exists and is not empty; preserve historical evidence: {out}')
    graph, provenance = read_phone(model_path)
    rules = source_rules()
    parameters, profile = baseline_parameters()
    catalog = json.loads((ROOT / '实验数据/CogTool_reference_catalog.json').read_text())
    published = {r['case_id']: r for r in catalog['official_and_developer_published_results']}
    summary = {'schema_version': 1, 'selection': {'priority_examined': 'NP-A1', 'selected_for_complete_baseline': 'NP-B1',
               'reason': 'NP-B1 has one direct context-menu parent chain, no hover and no unresolved LookAt duration. Selection uses input/operation completeness, never closeness to published or cached times.'},
               'source': provenance, 'source_rules': rules, 'baseline_parameter_profile': profile, 'cases': []}
    for case_id in ('NP-A1', 'NP-B1'):
        directory = out / case_id
        directory.mkdir(parents=True, exist_ok=True)
        extraction = extract_case(graph, case_id)
        candidate, mappings, blockers = construct_candidate(graph, extraction, parameters)
        write(directory / 'extraction.json', {**extraction, 'source': provenance})
        write(directory / 'candidate_input.json', candidate)
        write(directory / 'field_mapping.json', {'fields': mappings, 'source_rules': rules,
              'unvisited_frames': 'Only frames on demonstrated path retained; NP-B1 start-frame widgets retained in full',
              'geometry_origin': 'Original DoubleRectangle values; no screenshot measurements or inferred sizes'})
        write(directory / 'blockers.json', {'complete_baseline_input': not blockers, 'first_blocker': blockers[0] if blockers else None,
              'blockers': blockers, 'not_implemented': ['ACT-R module resources/overlap/productions', 'EMMA', 'general .cgt import'],
              'semantic_differences': ['Serial klm_baseline durations use modeler assumptions for whole click/key/home.',
                  'Original model saved in 2009; current rule reference fixed at 2014. No original rerun.',
                  'Automatic steps are regenerated from parent chain by Python core, not copied from cached generated script.']})
        archived = archive_reference(graph, extraction, directory)
        write(directory / 'archived_reference.json', archived)
        python = run_python(directory / 'candidate_input.json', directory) if run and not blockers else {
            'status': 'blocked_incomplete_conversion' if blockers else 'not_requested', 'diagnostic_python_prediction_s': None}
        values = {
            'published_reference': {'published_prediction_s': published[case_id]['published_prediction_s'],
                                    'human_mean_s': published[case_id]['human_mean_s'], 'source_locator': published[case_id]['source_locator']},
            'archived_reference': {'cached_prediction_s': archived['cached_prediction_s'], 'source_object_id': archived['source_object_id'],
                                   'used_for_input_or_prediction': False, 'original_version': graph.root.attrib['cogtool_version']},
            'current_original_rerun': {'prediction_s': None, 'status': 'not_executed_original_environment_unavailable'},
            'diagnostic_python': python,
        }
        write(directory / 'numerical_provenance.json', values)
        summary['cases'].append({'case_id': case_id, 'complete_baseline_input': not blockers,
                                 'blockers': blockers, 'numerical_sources': values,
                                 'diagnostic_python_prediction_s': python['diagnostic_python_prediction_s']})
    write(out / 'conversion_summary.json', summary)
    selected = next(record for record in summary['cases'] if record['case_id'] == 'NP-B1')
    values = selected['numerical_sources']
    write(out / 'summary.json', {
        'selected_case_id': 'NP-B1', 'selection_basis': summary['selection']['reason'],
        'diagnostic_python_prediction_s': selected['diagnostic_python_prediction_s'],
        'published_prediction_s': values['published_reference']['published_prediction_s'],
        'archived_prediction_s': values['archived_reference']['cached_prediction_s'],
        'original_rerun_s': None,
        'status': 'DIAGNOSTIC_ONLY' if values['diagnostic_python']['status'] == 'computed_serial_baseline' else 'NOT_COMPUTED',
        'input_path': 'NP-B1/candidate_input.json', 'result_path': 'NP-B1/python_prediction/result.json',
        'four_sources_separate': True, 'original_equivalence_claim': False,
        'human_accuracy_validation': False, 'original_reference_status': 'unverified',
    })
    lines = ['# 电话案例对象引用转换', '',
             '先检查 NP-A1：首步需要菜单头及子菜单 hover，第三步 LookAt 仅保存目标且没有时长，因此完整候选保留明确阻塞。没有把 hover 替成点击，也没有给 LookAt 补数字。', '',
             '选择 NP-B1 是因为其唯一示范可追溯为一层 ContextMenu→MenuItem，无 hover、LookAt 或未解析键序列。输入从原始示范与父引用构造；自动步骤由同一 Python 核心生成。', '',
             '原始 ZIP/嵌套 PERSIST 的 Git blob、SHA-256、对象ID及每个字段映射均保留。初始鼠标(0,0)是2014固定源码 cogtool-run-model 的条件默认，不是已证实的2009 r3035缓存初态；对应旧版源码未知。数值未变，来源声明收窄。左右手位置来自持久化初态。', '',
             'NP-B1的10个原始起始页控件均保留。仅省略路径不访问的页面。菜单geometry原样保留，视觉定位点按源码floor规则由核心计算。', '',
             'NP-A1/candidate_input.json 是故意保留空缺的不可执行候选；NP-B1/candidate_input.json 是有限串行基线候选。该转换器不构成通用 .cgt 支持。', '',
             '四类数值独立保存在 numerical_provenance.json：published_reference、archived_reference、current_original_rerun、diagnostic_python。旧结果与旧轨迹只能作为 archived_reference，绝不进入预测输入。', '',
             '基线click/key/home参数直接沿用已有单按钮示例，明确属于建模假设；未从总时间反推或调参。原版完整ACT-R参数、生产规则及资源重叠尚未重建，所以完整输入可计算不等于CogTool时间一致。', '']
    for record in summary['cases']:
        lines.append(f"- {record['case_id']}: {record['numerical_sources']['diagnostic_python']['status']}；Python诊断时间 {record['diagnostic_python_prediction_s']} s；完整基线输入 {record['complete_baseline_input']}。")
    lines += ['', '| NP-B1 数值来源 | 秒数 | 状态 |', '|---|---:|---|',
              f"| 文献公开预测 | {values['published_reference']['published_prediction_s']} | published_reference，不是本次运行 |",
              f"| 原文件旧缓存 | {values['archived_reference']['cached_prediction_s']} | archived_reference，未用于计算 |",
              '| 当前固定版本原版重跑 | null | 未执行 |',
              f"| 当前 Python 串行基线 | {selected['diagnostic_python_prediction_s']} | DIAGNOSTIC_ONLY，不声明原版或人体等价 |", '']
    (out / 'CONVERSION_zh.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path, help='Official conversion output directory')
    parser.add_argument('--no-run', action='store_true', help='Extract only; never claim successful diagnostic computation')
    args = parser.parse_args()
    result = convert(args.out.resolve(), run=not args.no_run)
    print(json.dumps({'output': str(args.out.resolve()), 'cases': [
        {'case_id': c['case_id'], 'complete_baseline_input': c['complete_baseline_input'],
         'diagnostic_python_prediction_s': c['diagnostic_python_prediction_s'],
         'status': c['numerical_sources']['diagnostic_python']['status']} for c in result['cases']]}, ensure_ascii=False))
    selected = next(record for record in result['cases'] if record['case_id'] == 'NP-B1')
    if args.no_run or selected['numerical_sources']['diagnostic_python']['status'] != 'computed_serial_baseline':
        raise SystemExit(2)


if __name__ == '__main__':
    main()

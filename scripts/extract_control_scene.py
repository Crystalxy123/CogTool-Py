#!/usr/bin/env python3
"""Extract the pinned NP-B1 scene for a source-defined 2014 control profile.

Read-only narrow extraction, not a general .cgt importer or an original run.
Group names/order are deliberately unknown: Java HashSet/Lisp hash iteration
was not executed. A unique leftmost location does not depend on those choices.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.convert_phone_case import CODE_COMMIT, ConversionError, read_phone, classname

JAVA = 'java/edu/cmu/cs/hcii/cogtool/'
SOURCES = [
    (JAVA + 'model/ACTRPredictionAlgo.java', '172,670-735,883-999,1350-1392,1756-1783',
     'ordinary output includes menu items and SimpleWidgetGroup locations; zero-time start-frame production'),
    (JAVA + 'model/Association.java', '226-249,371-374', 'group bounds union its members'),
    (JAVA + 'resources/cogtool-actr.lisp', '819-835,871-950,1037-1049,1138-1180',
     'initial device, scene export, location geometry, transition and initial processing'),
    ('lisp/actr6/core-modules/vision.lisp', '625-748,891-910,1094-1132,2429-2453,2542-2647',
     'scene entry and reset, leftmost-new stuffing, requested distinction'),
    (JAVA + 'resources/emma.lisp', '137-139,163-179,775-786,818-918',
     'selected visual module reset and absence of registered auto-attend parameter'),
]


def evidence() -> list[dict]:
    records = []
    for relative, lines, purpose in SOURCES:
        data = (ROOT / 'reference/upstream-cogtool' / relative).read_bytes()
        actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        expected = subprocess.check_output(['git', '-C', str(ROOT / 'cogtool'), 'rev-parse',
                                            f'{CODE_COMMIT}:{relative}'], text=True).strip()
        if actual != expected:
            raise ConversionError(f'Fixed source blob changed: {relative}')
        records.append({'path': relative, 'lines': lines, 'purpose': purpose, 'source_commit': CODE_COMMIT,
                        'git_blob': actual, 'sha256': hashlib.sha256(data).hexdigest()})
    return records


def center(bounds: dict) -> list[float]:
    return [bounds['x'] + math.floor(bounds['width'] / 2),
            bounds['y'] + math.floor(bounds['height'] / 2)]


def extract_scene() -> dict:
    graph, provenance = read_phone()
    start = graph.index['6']
    groups = {}
    widgets = []
    originals = graph.entries(graph.get(start, 'widgets'))
    for index, node in enumerate(originals):
        info = graph.target(node)
        parent_group = graph.get(node, 'parentGroup')
        if parent_group is not None and parent_group.tag != 'null':
            if classname(parent_group) != 'SimpleWidgetGroup':
                raise ConversionError('Unexpected non-simple NP-B1 parent group')
            groups[parent_group.get('id')] = parent_group
        loc = center(info['geometry'])
        widgets.append({'id': 'w' + node.get('id'), 'frame': 'f6', 'kind': info['class'],
                        'name': info['name'], 'center': loc, 'x': loc[0], 'y': loc[1],
                        'visible': True, 'creation_time_s': 0.0,
                        'creation_event': 'initial_transition_proc_display', 'order': None,
                        'persisted_widget_order': index,
                        'member_of_group': 'g' + parent_group.get('id') if parent_group is not None and parent_group.tag != 'null' else None,
                        'source': {'object_id': node.get('id'), 'bounds': info['geometry'],
                                   'renderWidget': graph.value(node, 'renderWidget'),
                                   'note': 'renderWidget is a rendering field, not an outputFrame visibility filter'}})
    auxiliary = []
    for ident, node in sorted(groups.items(), key=lambda pair: int(pair[0])):
        members = graph.entries(graph.get(node, 'members'))
        if not members:
            raise ConversionError(f'Empty original group {ident}')
        member_geometry = [graph.target(member)['geometry'] for member in members]
        if any(rect is None for rect in member_geometry):
            raise ConversionError(f'Non-rectangular group member: {ident}')
        left = min(rect['x'] for rect in member_geometry)
        top = min(rect['y'] for rect in member_geometry)
        right = max(rect['x'] + rect['width'] for rect in member_geometry)
        bottom = max(rect['y'] + rect['height'] for rect in member_geometry)
        bounds = {'x': left, 'y': top, 'width': right - left, 'height': bottom - top}
        loc = center(bounds)
        auxiliary.append({'id': 'g' + ident, 'frame': 'f6', 'kind': 'cogtool-group',
                          'center': loc, 'x': loc[0], 'y': loc[1], 'visible': True,
                          'creation_time_s': 0.0, 'creation_event': 'initial_transition_proc_display',
                          'order': None, 'original_generated_symbol': None,
                          'source': {'object_id': ident, 'class': classname(node),
                                     'members': [m.get('id') for m in members], 'bounds': bounds,
                                     'geometry_rule': 'union original member bounds then x+floor(width/2),y+floor(height/2)',
                                     'source_commit': CODE_COMMIT,
                                     'unknown_symbol_reason': 'Anonymous GROUP [iN] numbering depends on unexecuted Java emission order'}})
    all_locs = widgets + auxiliary
    smallest = min(location['x'] for location in all_locs)
    leftmost = [location['id'] for location in all_locs if location['x'] == smallest]
    return {'schema_version': 1, 'case_id': 'NP-B1', 'source_commit': CODE_COMMIT,
            'initial_state_profile': 'source_defined_2014_normal_emma_defaults',
            'original_runtime_observed': False, 'original_rerun_s': None,
            'frame': {'id': 'f6', 'source_object_id': '6', 'name': graph.name(start), 'visible': True},
            'widgets': widgets, 'auxiliary_locations': auxiliary,
            'visibility_contract': {'ordinary_cogtool_emitVirtualFrames': False, 'ct_explorer_mode': False,
                                    'menu_items_in_initial_scene': True, 'menu_open_visibility_filter_exists': False,
                                    'whole_frame_visibility': True, 'vision_suppression_interval_s': 0,
                                    'process_cursor': False},
            'normal_stuffing': {'when': 'After zero-time set-start-frame transition invokes proc-display',
                                'time_s': 0.0, 'conditions': ['visual-location buffer empty', 'device locks=0', 'no tracked object'],
                                'default_spec': {'isa': 'visual-location', 'screen-x': 'lowest', 'attended': 'new'},
                                'leftmost_candidates': leftmost,
                                'chosen_id': leftmost[0] if len(leftmost) == 1 else None,
                                'selection_status': 'unique_leftmost_proven' if len(leftmost) == 1 else 'unsupported_tie',
                                'requested': False, 'set_buffer_priority': 10, 'unlock_priority': 9,
                                'tie_policy_from_source': 'max visual timestamp, sort symbol names, random-item',
                                'tie_implementation_in_this_extractor': None},
            'initial_buffers_and_modules': {
                'before_start_frame': {'visual_location': None, 'visual': None, 'scene': [], 'current_frame': None},
                'after_start_frame_stuffing': {'visual_location': leftmost[0] if len(leftmost) == 1 else None,
                                              'visual_location_requested': False, 'visual': None},
                'visual': {'modality': 'free', 'preparation': 'free', 'processor': 'free', 'execution': 'free',
                           'current_marker': None, 'currently_attended': None, 'moving_attention': None,
                           'eye_position': [0, 0], 'eye_position_source': 'selected 2014 EMMA reset only'},
                'mouse_position': [0, 0], 'saved_2009_mouse_position': None},
            'explicit_profile_conditions': ['fresh model', 'CogTool preference defaults', 'USE_EMMA=true',
                                            'ordinary ACTR output (emitVirtualFrames=false)', 'no optional runtime override file',
                                            'no explicit visual-location default override', 'no saved 2009 initial state claim'],
            'source': provenance, 'source_evidence': evidence(),
            'unknowns': {'source_2009_commit': None, 'actual_2014_generated_lisp': None,
                         'actual_2014_runtime_preferences': None, 'java_group_iteration_order': None,
                         'lisp_hash_iteration_order': None, 'archived_2009_visual_state': None},
            'not_used_as_input': ['2009 trace timestamps', 'cached task time', 'published result']}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    try:
        if out.exists():
            raise ConversionError(f'Output exists; refuse overwrite: {out}')
        if not out.is_relative_to(ROOT / 'reports'):
            raise ConversionError('Scene output must be a new directory below workspace reports/')
        scene = extract_scene()
        out.mkdir(parents=True)
        (out / 'scene.json').write_text(json.dumps(scene, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
        (out / 'auxiliary_locations.json').write_text(json.dumps(scene['auxiliary_locations'], ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'locations': len(scene['widgets']) + len(scene['auxiliary_locations']),
                          'normal_stuffing': scene['normal_stuffing']['chosen_id'],
                          'status': scene['normal_stuffing']['selection_status']}, ensure_ascii=False))
        return 0
    except (ConversionError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f'Control scene extraction failed: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

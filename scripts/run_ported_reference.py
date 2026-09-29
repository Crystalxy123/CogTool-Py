#!/usr/bin/env python3
"""Bounded source-only SBCL port of the fixed ACT-R/CogTool backend.

Not an original binary rerun: the loader compatibility patch and independently
transcribed Java templates are saved.  Only the frozen project and shared KLM
generator supply the input.  No Python predictor, cached trace or reference
time is read by this script.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import difflib
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cogtool_py.generator import generate
from cogtool_py.io import load_project

COMMIT = 'a91d91e8dcf95d762b6e08020029a36ea079bbba'
SOURCE = ROOT / 'reference/upstream-cogtool'
REPO = ROOT / 'cogtool'
RESOURCE = 'java/edu/cmu/cs/hcii/cogtool/resources/'
LOADER = 'lisp/actr6/load-act-r-6.lisp'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def quoted(value: str) -> str:
    if '\n' in value or '\r' in value:
        raise ValueError('Multiline Lisp string not supported by this bounded writer')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def verified_copy(destination: Path) -> list[dict]:
    files = sorted((SOURCE / 'lisp/actr6').rglob('*.lisp'))
    files += [SOURCE / RESOURCE / name for name in ('emma.lisp', 'cogtool-actr.lisp')]
    manifest = []
    for source in files:
        rel = source.relative_to(SOURCE).as_posix()
        data = source.read_bytes()
        git_data = subprocess.check_output(['git', '-C', str(REPO), 'show', f'{COMMIT}:{rel}'])
        if git_data != data:
            raise ValueError(f'Fixed source bytes mismatch: {rel}')
        blob = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', f'{COMMIT}:{rel}'], text=True).strip()
        output = destination / rel
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        manifest.append({'path': rel, 'git_blob': blob, 'sha256': sha(data)})
    return manifest


def patch_loader(path: Path) -> str:
    before = path.read_text()
    macro = "`(sb-c::%defconstant ',name ,value ',documentation (sb-c:source-location)))"
    if before.count(macro) != 1:
        raise ValueError('Unexpected DEFCONSTANT loader source')
    after = before.replace(macro, '`(cl:defconstant ,name ,value ,documentation))')
    start = after.index('#-(and :ccl-4.3.5 :ccl-5.0) \n(defun compile-and-load')
    end = after.index(';;; SMART-LOAD', start)
    after = after[:start] + ''';; PORT COMPATIBILITY: load source once, avoiding compile/load duplicate constants.
#-(and :ccl-4.3.5 :ccl-5.0)
(defun compile-and-load (pathname)
  (when (pathname-type pathname)
    (if (string-equal (pathname-type pathname) "lisp")
        (setf pathname (make-pathname :host (pathname-host pathname)
                                     :directory (pathname-directory pathname)
                                     :device (pathname-device pathname)
                                     :name (pathname-name pathname)))
        (error "To load a file it must have a .lisp extension")))
  (let ((srcpath (merge-pathnames pathname *.lisp-pathname*)))
    (unless (probe-file srcpath) (error "File ~S does not exist" srcpath))
    (load srcpath)))

''' + after[end:]
    path.write_text(after)
    return ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                       fromfile='upstream/' + LOADER, tofile='ported/' + LOADER))


def _menu_model_text(input_path: Path) -> tuple[str, dict]:
    """Static distinct-parent menus: pinned Java templates, not control rules."""
    data = json.loads(input_path.read_text())
    project = load_project(input_path)
    control = project.control
    if (control is None or control.profile != 'source_2014_defaults'
            or control.execution_scope != 'integrated_task' or control.initial_eye is not None):
        raise ValueError('Only source_2014_defaults/integrated_task with default initial eye is supported')
    if len(project.tasks) != 1 or len(project.design.frames) != 1:
        raise ValueError('Only one task in one static frame is supported')
    task = project.tasks[0]
    initial = task.demonstration.initial
    if (initial.mouse != (0, 0) or initial.mouse_hand != 'right'
            or initial.hand != 'mouse' or initial.focus is not None):
        raise ValueError('Only the original default cursor, right hand on mouse and empty focus are supported')
    frame = data['design']['frames'][0]
    fn = quoted(frame['name'])
    widgets = {w['id']: w for w in frame['widgets']}
    transitions = {t['id']: t for t in data['design']['transitions']}
    if any(t['delay_s'] != 0 or t['from_frame'] != frame['id'] or t['to_frame'] != frame['id']
           for t in transitions.values()):
        raise ValueError('Only zero-delay self transitions in the single frame are supported')
    parents = []
    for demo in task.demonstration.steps:
        if demo.op != 'menu_select' or demo.target not in widgets:
            raise ValueError('Only specified menu-item selections are supported')
        selected = widgets[demo.target]
        parent = widgets.get(selected['parent'])
        if selected['kind'] != 'menu_item' or not parent or parent['kind'] != 'context_menu':
            raise ValueError('Only direct children of a context menu are supported')
        if parent['id'] in parents:
            raise ValueError('Repeated selection of the same parent menu is unsupported')
        if demo.transition not in transitions:
            raise ValueError('This bounded writer requires an explicit zero-delay self transition per selection')
        parents.append(parent['id'])
    script = generate(project, task)
    expected_ops = ['point', 'right_click', 'think', 'point', 'click', 'transition'] * len(parents)
    if not parents or [s.op for s in script.steps] != expected_ops:
        raise ValueError('Shared generated operation structure is outside the verified template subset')
    last_point = None
    for step in script.steps:
        if step.op == 'point':
            widget = widgets[step.target]
            position = (widget['x'], widget['y'], widget['width'], widget['height'])
            if position == last_point:
                raise ValueError('Consecutive same-location targets need additional Java look-at suppression support')
            last_point = position
    names = {key: quoted(w['name'] + ' in ' + frame['name']) for key, w in widgets.items()}
    groups = []
    for auxiliary in data['control']['auxiliary_locations']:
        source = json.loads(auxiliary['source'])
        if source.get('class') != 'SimpleWidgetGroup' or auxiliary['frame'] != frame['id']:
            raise ValueError('Only extracted SimpleWidgetGroup geometry is supported')
        bounds = source['bounds']
        if (auxiliary['x'] != bounds['x'] + math.floor(bounds['width'] / 2)
                or auxiliary['y'] != bounds['y'] + math.floor(bounds['height'] / 2)):
            raise ValueError('Auxiliary center differs from actual source bounds')
        if any('w' + str(member) not in widgets for member in source['members']):
            raise ValueError('Group object references do not map to extracted widget IDs')
        groups.append((auxiliary['id'], source))
    group_names = {gid: quoted('SHARED-GROUP-' + gid + ' in ' + frame['name']) for gid, _ in groups}
    memberships = {str(m): gid for gid, group in groups for m in group['members']}
    text = [';; Independent transcription of ACTRPredictionAlgo.java templates at fixed 2014 commit.',
            ';; Shared JSON/KLM generator input. This is NOT Java frontend output.',
            '(defun define-design ()',
            "  (setq *cogtool-design* (make-instance 'cogtool-device))",
            f"  (let ((frame (make-instance 'cogtool-frame :name {fn})) (groups nil) widget)"]
    for widget in frame['widgets']:
        kind = {'context_menu': 'cogtool-context-menu', 'menu_item': 'cogtool-menu-item'}[widget['kind']]
        text.append(f"    (setf widget (make-instance 'cogtool-widget :name {names[widget['id']]} :title {quoted(widget['label'])}"
                    f" :x {widget['x']} :y {widget['y']} :width {widget['width']} :height {widget['height']} :wtype '{kind}"
                    + (f" :member-of-groups '({group_names[memberships[widget['id'][1:]]]})" if widget['id'][1:] in memberships else '') + '))')
        text.append('    (push widget (widgets frame))')
    for gid, group in groups:
        b = group['bounds']
        text.append(f"    (push (make-instance 'cogtool-widget :name {group_names[gid]} :x {b['x']} :y {b['y']}"
                    f" :width {b['width']} :height {b['height']} :wtype 'cogtool-group) groups)")
    text += ['    (resolve-widget-refs frame groups)', f'    (setf (gethash {fn} (frames *cogtool-design*)) frame)))']
    # Independent provenance fixes the experiment's declared source defaults.
    # Serial baseline click/key/home parameters never enter this backend.
    mapping = {'visual_encoding_factor_s': ':visual-encoding-factor',
               'visual_encoding_exponent_per_deg': ':visual-encoding-exponent',
               'visual_object_frequency': ':vis-obj-freq', 'eye_saccade_rate_s_per_deg': ':eye-saccade-rate',
               'eye_saccade_base_s': ':saccade-base-time', 'production_action_s': ':dat',
               'motor_feature_prep_s': ':motor-feature-prep-time', 'motor_burst_s': ':motor-burst-time',
               'motor_initiation_s': ':motor-initiation-time', 'fitts_coefficient_s': ':mouse-fitts-coeff',
               'fitts_min_s': ':min-fitts-time', 'pixels_per_inch': ':pixels-per-inch',
               'viewing_distance_in': ':viewing-distance'}
    values = {key: p['value'] for key, p in data['parameters'].items()}
    # These source slots lack equivalent generated parameter assignments here.
    for key, expected in [('eye_feature_prep_s', .05), ('eye_initiation_s', .05), ('motor_key_closure_s', .01)]:
        if values[key] != expected:
            raise ValueError(f'{key} must retain the audited upstream default')
    text += ["(setq *overridden-global-parameters* '(" + ' '.join(f'{lisp} {values[key]}' for key, lisp in mapping.items())
             + ' :use-tree nil :er nil :egs 0 :iu 0 :ul nil :esc t :randomize-time nil :seed (1 0) :vpft nil :ppm nil))',
             f'(define-cogtool-model (:start-with-mouse t :timeout {control.max_time_s})',
             '''(p *suppress-re-encoding-1
 =goal> isa klm suppress-re-encoding t
 ?visual> state free
 ?frame> status visible
 ==>
 +visual> isa clear
 =goal> suppress-re-encoding nil)
(spp *suppress-re-encoding-1 :at 0.0)''',
             f'''(p set-start-frame-2
 =goal> isa klm state 1
 ==>
 !eval! (set-cogtool-plist :destination-frame {fn})
 =goal> state 2)
(spp set-start-frame-2 :at 0.0)''']
    state, count = 2, 3
    records = []
    for step in script.steps:
        records.append(asdict(step))
        target = names.get(step.target)
        prop = f'(set-cogtool-plist :current-frame {fn})'
        target_prop = f'(set-cogtool-plist :target {target} :current-frame {fn})'
        if step.op == 'point':
            text.append(f'''(p find-{count}
 =goal> isa klm state {state}
 ?frame> name {fn} status visible
 ==>
 !eval! {target_prop}
 +visual-location> isa visual-location value {target}
 =goal> state {state + 1})
(spp find-{count} :u -1.0)''')
            count += 1
            for prior in (state, state + 1):
                text.append(f'''(p look-at-{count}
 =goal> isa klm state {prior}
 =visual-location> isa visual-location value {target}
 ?visual> state free
 ?frame> name {fn} status visible
 ==>
 !eval! {target_prop}
 +visual> isa move-attention screen-pos =visual-location
 =visual-location>
 =goal> state {state + 2} suppress-re-encoding t)''')
                count += 1
            state += 2
            text.append(f'''(p find-location-{count}
 =goal> isa klm state {state}
 ?frame> name {fn} status visible
 ==>
 !eval! {prop}
 +visual-location> isa visual-location value {target}
 =goal> state {state})
(spp find-location-{count} :u -1.0)''')
            count += 1
            text.append(f'''(p move-mouse-{count}
 =goal> isa klm state {state}
 =visual-location> isa visual-location value {target}
 ?manual> preparation free execution free state free
 ?frame> name {fn} status visible
 ==>
 !eval! {prop}
 +manual> isa move-cursor loc =visual-location
 =visual-location>
 =goal> state {state + 1})''')
            count += 1
            state += 1
        elif step.op in ('right_click', 'click'):
            text.append(f'''(p prepare-click-{count}
 =goal> isa klm state {state}
 ?manual> preparation free
 ?frame> name {fn}
 ==>
 !eval! {target_prop}
 +manual> isa prepare style punch hand right finger index
 =goal> state {state + 1})''')
            count += 1
            state += 1
            text.append(f'''(p click-mouse-{count}
 =goal> isa klm state {state}
 ?manual> execution free
 ?frame> name {fn}
 ==>
 !eval! {target_prop}
 +manual> isa click-mouse
 =goal> state {state + 1})''')
            count += 1
            state += 1
        elif step.op == 'think':
            text.append(f'''(p think-{count}
 =goal> isa klm state {state}
 ?manual> state free
 ==>
 !eval! (set-cogtool-plist :duration {step.duration_s} :current-frame {fn})
 =goal> state {state + 1})
(spp think-{count} :at {step.duration_s})''')
            count += 1
            state += 1
        elif step.op != 'transition':
            raise ValueError(f'Unsupported operation {step.op}')
    text.append(f'''(p stop-{count}
 =goal> isa klm state {state}
 ==>
 !eval! (set-cogtool-plist)
 +goal> isa stop)
(spp stop-{count} :at 0.0)
)
(format t "~&REFERENCE_STAGE model-defined~%")
(format t "~&REFERENCE_INITIAL_SLOTS ~S~%"
 (list :auto-attend (auto-attend (get-module :vision))
       :eye-feature-prep-s (feat-prep-time (get-module :vision))
       :eye-initiation-s (init-time (get-module :vision))
       :key-closure-s (key-closure-time (current-device-interface))
       :initial-eye (eye-loc (get-module :vision))))
(setq *cogtool-result* (cogtool-run-model))
(format t "~&REFERENCE_RETURNED_TIME ~S~%" *cogtool-result*)
(format t "~&REFERENCE_FINAL_MP_TIME ~S~%" (mp-time))
(format t "~&REFERENCE_GOAL ~S~%" (buffer-read 'goal))
(format t "~&~S~%" *cogtool-result*)
''')
    provenance = {'case_id': task.id, 'classification': 'ported_reference_backend',
                  'shared_generator': True, 'independent_backend': True,
                  'java_frontend_executed': False, 'python_predictor_used': False,
                  'archived_trace_or_value_used': False,
                  'source_commit': COMMIT, 'input_sha256': sha(input_path.read_bytes()),
                  'shared_generator_source_sha256': sha((ROOT / 'cogtool_py/generator.py').read_bytes()),
                  'shared_generated_steps': records,
                  'writer_source_rules': ['ACTRPredictionAlgo.java:1484-1636,1742-1805,1997-2039,2074-2120,2502-2587,2598-2628',
                                          'ACTRPredictionAlgo.java:660-734,901-999 (geometry/group writer)'],
                  'parameter_assignments': {key: {'lisp': lisp, 'value': values[key]} for key, lisp in mapping.items()},
                  'not_used_parameters': ['click_s', 'key_s', 'homing_s'],
                  'source_default_slots': {'eye_feature_prep_s': {'source_default': .05, 'observed': None},
                                           'eye_initiation_s': {'source_default': .05, 'observed': None},
                                           'motor_key_closure_s': {'source_default': .01, 'observed': None}},
                  'auto_attend': {'source_default': False, 'observed': None, 'sgp_parameter_available_in_emma': False,
                                  'source': 'emma.lisp:128-139; vision.lisp:588',
                                  'explanation': 'EMMA deliberately omits the parameter; inherited slot remains NIL'},
                  'limitations': ['No independent Java frontend: shared generator expansion and input model',
                                  'Anonymous group symbols are stable substitutes; original Java implicit numbering unknown',
                                  'Only static single-frame distinct-parent menus, each with explicit zero-delay self transition',
                                  'SBCL source-loading compatibility port, not original CLISP binary',
                                  '2009 source/runtime equivalence remains unverified']}
    return '\n\n'.join(text), provenance


def _ordinary_model_text(input_path: Path) -> tuple[str, dict]:
    """Bounded ordinary-action exporter, independently transcribed from Java.

    The shared KLM generator is the sole step input. No controller rules,
    predictor output, Java export, historical trace, or predicted time is read.
    """
    data = json.loads(input_path.read_text())
    project = load_project(input_path)
    control = project.control
    if (control is None or control.profile != 'source_2014_defaults'
            or control.execution_scope != 'integrated_task' or control.initial_eye is not None):
        raise ValueError('Ordinary writer requires source_2014_defaults/integrated_task and default eye')
    if len(project.tasks) != 1 or control.auxiliary_locations:
        raise ValueError('Ordinary writer requires one task and no unrepresented auxiliary groups')
    task = project.tasks[0]
    initial = task.demonstration.initial
    if initial.mouse != (0, 0) or initial.mouse_hand != 'right' or initial.focus is not None:
        raise ValueError('Ordinary writer supports default cursor, right mouse hand and empty initial focus')
    if any(s.op not in {'point', 'click', 'keys', 'home', 'think', 'look_at'} for s in task.demonstration.steps):
        raise ValueError('Only ordinary point/click, lowercase text/DOWN keys, home, Think and source LookAt are supported')
    frames = {f.id: f for f in project.design.frames}
    fnames = {fid: quoted(f.name) for fid, f in frames.items()}
    if len(set(fnames.values())) != len(fnames):
        raise ValueError('Frame names must be unique for the Lisp device table')
    widgets = {(f.id, w.id): w for f in frames.values() for w in f.widgets}
    names = {key: quoted(w.name + ' in ' + frames[key[0]].name) for key, w in widgets.items()}
    if len(set(names.values())) != len(names):
        raise ValueError('Global widget names must be unique for the Lisp visual scene')
    kinds = {'button': 'cogtool-button', 'link': 'cogtool-link', 'textbox': 'cogtool-text-box', 'text': 'cogtool-text'}
    if any(w.kind not in kinds or w.parent is not None for w in widgets.values()):
        raise ValueError('Ordinary writer represents buttons, links, textboxes and Text without groups')
    transitions = {t.id: t for t in project.design.transitions}
    script = generate(project, task)
    allowed = {'point', 'click', 'think', 'home', 'key', 'transition', 'wait', 'look_at'}
    if any(s.op not in allowed for s in script.steps):
        raise ValueError('Shared generator produced an operation outside the ordinary writer scope')
    # TransitionDelayScriptStep is deliberately a no-op in the Java writer
    # (2491-2496). It is represented once on the firing action's plist below.
    for step in script.steps:
        if step.op == 'wait':
            following = script.steps[step.index + 1] if step.index + 1 < len(script.steps) else None
            if (step.origin != 'automatic' or following is None or following.op != 'transition'
                    or following.demo_index != step.demo_index or following.note not in transitions
                    or step.duration_s != transitions[following.note].delay_s):
                raise ValueError('Only generated transition-delay annotations are supported; standalone wait is obsolete upstream')
    text = [';; Independent fixed-2014 Java template transcription: ordinary actions.',
            ';; Input and KLM expansion only; not Java frontend output or Python predictions.',
            '(defun define-design ()', "  (setq *cogtool-design* (make-instance 'cogtool-device))"]
    for frame in project.design.frames:
        fn = fnames[frame.id]
        text.append(f"  (let ((frame (make-instance 'cogtool-frame :name {fn})) (groups nil) widget)")
        for widget in frame.widgets:
            title = f' :title {quoted(widget.label)}' if widget.label else ''
            text.append(f"    (setf widget (make-instance 'cogtool-widget :name {names[(frame.id, widget.id)]}{title}"
                        f" :x {widget.x} :y {widget.y} :width {widget.width} :height {widget.height}"
                        f" :wtype '{kinds[widget.kind]}))")
            for transition in project.design.transitions:
                if (getattr(transition,'source_type','widget')=='widget' and
                        transition.from_frame == frame.id and transition.target == widget.id):
                    text.append("    (setf (gethash '((click left)) (transitions widget)) "
                                f"(make-instance 'cogtool-transition :target {fnames[transition.to_frame]}))")
            text.append('    (push widget (widgets frame))')
        text += ['    (resolve-widget-refs frame groups)',
                 f'    (setf (gethash {fn} (frames *cogtool-design*)) frame))']
    text.append(')')
    mapping = {'visual_encoding_factor_s': ':visual-encoding-factor',
               'visual_encoding_exponent_per_deg': ':visual-encoding-exponent',
               'visual_object_frequency': ':vis-obj-freq', 'eye_saccade_rate_s_per_deg': ':eye-saccade-rate',
               'eye_saccade_base_s': ':saccade-base-time', 'production_action_s': ':dat',
               'motor_feature_prep_s': ':motor-feature-prep-time', 'motor_burst_s': ':motor-burst-time',
               'motor_initiation_s': ':motor-initiation-time', 'fitts_coefficient_s': ':mouse-fitts-coeff',
               'fitts_min_s': ':min-fitts-time', 'pixels_per_inch': ':pixels-per-inch',
               'viewing_distance_in': ':viewing-distance'}
    values = {k: p['value'] for k, p in data['parameters'].items()}
    if any(s.op in {'key', 'home'} for s in script.steps):
        if 'motor_peck_fitts_coefficient_s' not in values:
            raise ValueError('Keyboard/homing writer requires the explicit effective keyboard parameter profile')
        mapping['motor_peck_fitts_coefficient_s'] = ':peck-fitts-coeff'
    for key, expected in [('eye_feature_prep_s', .05), ('eye_initiation_s', .05), ('motor_key_closure_s', .01)]:
        if values[key] != expected:
            raise ValueError(f'{key} must retain the audited upstream default')
    text += ["(setq *overridden-global-parameters* '(" + ' '.join(f'{v} {values[k]}' for k, v in mapping.items())
             + ' :use-tree nil :er nil :egs 0 :iu 0 :ul nil :esc t :randomize-time nil :seed (1 0) :vpft nil :ppm nil))',
             f"(define-cogtool-model (:start-with-mouse {'t' if initial.hand == 'mouse' else 'nil'} :timeout {control.max_time_s})",
             '''(p *suppress-re-encoding-1
 =goal> isa klm suppress-re-encoding t
 ?visual> state free
 ?frame> status visible
 ==>
 +visual> isa clear
 =goal> suppress-re-encoding nil)
(spp *suppress-re-encoding-1 :at 0.0)''',
             f'''(p set-start-frame-2
 =goal> isa klm state 1
 ==>
 !eval! (set-cogtool-plist :destination-frame {fnames[initial.frame]})
 =goal> state 2)
(spp set-start-frame-2 :at 0.0)''']
    state, count = 2, 3
    last_looked_bounds = None
    home_pending = False
    omitted_annotations = []

    def prop(step, *, target=None, transition=False, extra=''):
        content = (':target ' + target + ' ') if target is not None else ''
        if extra:
            content += extra + ' '
        content += ':current-frame ' + fnames[step.frame]
        if transition:
            demo = task.demonstration.steps[step.demo_index]
            if demo.transition is not None:
                tr = transitions[demo.transition]
                if tr.delay_s > 0:
                    if tr.delay_label is None:
                        raise ValueError('Positive transition delay requires an explicit source or synthetic delay_label')
                    content += f' :delay-duration {tr.delay_s} :delay-label {quoted(tr.delay_label)}'
                if tr.to_frame != tr.from_frame or tr.delay_s > 0:
                    content += ' :destination-frame ' + fnames[tr.to_frame]
        return '(set-cogtool-plist ' + content + ')'

    def emit(name, guards, actions, plist, *, next_state=None, spp=None):
        nonlocal state, count, home_pending
        dest = state + 1 if next_state is None else next_state
        text.append(f'(p {name}-{count}\n =goal> isa klm state {state}\n' + guards
                    + '\n ==>\n !eval! ' + plist + '\n' + actions
                    + f'\n =goal> state {dest})'
                    + (f'\n(spp {name}-{count} {spp})' if spp else ''))
        count += 1
        state = dest
        home_pending = False

    def look(step, target):
        nonlocal state, count, last_looked_bounds, home_pending
        origin = state
        fn = fnames[step.frame]
        emit('find', f' ?frame> name {fn} status visible',
             f' +visual-location> isa visual-location value {target}', prop(step, target=target),
             next_state=origin + 1, spp=':u -1.0')
        for prior in (origin, origin + 1):
            state = prior
            # suppress-re-encoding is a goal slot, so this template is emitted
            # explicitly rather than passed as a separate buffer request.
            text.append(f'''(p look-at-{count}
 =goal> isa klm state {prior}
 =visual-location> isa visual-location value {target}
 ?visual> state free
 ?frame> name {fn} status visible
 ==>
 !eval! {prop(step, target=target)}
 +visual> isa move-attention screen-pos =visual-location
 =visual-location>
 =goal> state {origin + 2} suppress-re-encoding t)''')
            count += 1
        state = origin + 2
        home_pending = False
        last_looked_bounds = widgets[(step.frame, step.target)].bounds

    i = 0
    while i < len(script.steps):
        step = script.steps[i]
        fn = fnames[step.frame]
        target = names.get((step.frame, step.target))
        if step.op in {'transition', 'wait'}:
            omitted_annotations.append({'index': step.index, 'op': step.op,
                                        'reason': 'action plist handles destination/delay; no extra production'})
            i += 1
            continue
        if step.op in {'point', 'click'} and widgets[(step.frame, step.target)].bounds != last_looked_bounds:
            look(step, target)
        if step.op == 'look_at':
            if step.duration_s is not None:
                raise ValueError('Source LookAt is a visual request without a supplied duration')
            # visit(LookAtScriptStep):2592 is unconditional, including repeated
            # same-location looks; only implicit insertion has that suppression.
            look(step, target)
        elif step.op == 'point':
            emit('find-location', f' ?frame> name {fn} status visible',
                 f' +visual-location> isa visual-location value {target}', prop(step),
                 next_state=state, spp=':u -1.0')
            emit('move-mouse', f' =visual-location> isa visual-location value {target}\n'
                 f' ?manual> preparation free execution free state free\n ?frame> name {fn} status visible',
                 ' +manual> isa move-cursor loc =visual-location\n =visual-location>', prop(step))
        elif step.op == 'click':
            emit('prepare-click', f' ?manual> preparation free\n ?frame> name {fn}',
                 ' +manual> isa prepare style punch hand right finger index', prop(step, target=target))
            emit('click-mouse', f' ?manual> execution free\n ?frame> name {fn}',
                 ' +manual> isa click-mouse', prop(step, target=target, transition=True))
        elif step.op == 'think':
            emit('think', ' ?manual> state free', '',
                 prop(step, extra=f':duration {step.duration_s}'), spp=f':at {step.duration_s}')
        elif step.op == 'home':
            if step.duration_s == 0:
                raise ValueError('Redundant explicit home is a baseline annotation, not a verified Java action')
            action = 'hand-to-home' if step.device == 'keyboard' else 'hand-to-mouse'
            emit('move-hand', ' ?manual> state free', ' +manual> isa ' + action,
                 prop(step, target="'" + step.device))
            home_pending = step.device == 'keyboard'
        elif step.op == 'key':
            sequence = []
            j = i
            while j < len(script.steps):
                s = script.steps[j]
                if s.op != 'key' or s.demo_index != step.demo_index or s.frame != step.frame:
                    break
                if s.key != 'DOWN' and (len(s.key) != 1 or s.key not in 'abcdefghijklmnopqrstuvwxyz0123456789'):
                    raise ValueError('Integrated writer supports lowercase ASCII letters, digits and source DOWN only; no modifier aliases')
                sequence.append(s)
                j += 1
            from cogtool_py.models import LEFT_KEYS
            chars = ''.join('\ue00d' if s.key=='DOWN' else s.key for s in sequence)
            # ACTRPredictionAlgo WORD: digits/punctuation break words. Each
            # matching substring gets one production at its actual index.
            words = {m.start():m.group() for m in re.finditer(r'[^ -@\[-`\{-~\s]{2,}',chars)}
            execution_free = not (home_pending and chars[0] in LEFT_KEYS)
            previous_left = None
            for index, s in enumerate(sequence):
                if index in words:
                    word=words[index]
                    # LispUtil.makeSymbol:157-176 then outputModel US-ASCII:
                    # private-use key chars form a word but print as '?' within
                    # escaped symbols. Never treat the four letters DOWN as keys.
                    symbol=word if word.isascii() else '|' + word.encode('ascii','replace').decode('ascii') + '|'
                    emit('get-spelling-' + symbol, f' ?frame> name {fn}\n ?manual> preparation free'
                         + (' execution free' if execution_free else ''), '', prop(s))
                    execution_free = True
                left = s.key in LEFT_KEYS
                same_hand = previous_left is not None and previous_left == left
                emit('press-key', f' ?frame> name {fn}\n ?manual> preparation free'
                     + (' execution free' if same_hand else ''), f' +manual> isa press-key key {"slash" if s.key=="DOWN" else s.key.upper()}',
                     prop(s, transition=index == len(sequence) - 1,
                          extra=f':key {quoted("(DOWN)" if s.key=="DOWN" else s.key)} :hand ' + ("'LEFT" if left else "'RIGHT")))
                previous_left = left
            i = j
            continue
        i += 1
    text.append(f'''(p stop-{count}
 =goal> isa klm state {state}
 ==>
 !eval! (set-cogtool-plist)
 +goal> isa stop)
(spp stop-{count} :at 0.0)
)
(format t "~&REFERENCE_STAGE model-defined~%")
(format t "~&REFERENCE_INITIAL_SLOTS ~S~%"
 (list :auto-attend (auto-attend (get-module :vision))
       :eye-feature-prep-s (feat-prep-time (get-module :vision))
       :eye-initiation-s (init-time (get-module :vision))
       :key-closure-s (key-closure-time (current-device-interface))
       :initial-eye (eye-loc (get-module :vision))))
(setq *cogtool-result* (cogtool-run-model))
(format t "~&REFERENCE_RETURNED_TIME ~S~%" *cogtool-result*)
(format t "~&REFERENCE_FINAL_MP_TIME ~S~%" (mp-time))
(format t "~&REFERENCE_GOAL ~S~%" (buffer-read 'goal))
(format t "~&~S~%" *cogtool-result*)
''')
    provenance = {'case_id': task.id, 'classification': 'ported_reference_backend',
                  'writer_scope': 'ordinary_text_widgets_source_look_at_unmodified_alphanumeric_and_down_keys_typed_input_device_transitions',
                  'shared_generator': True, 'independent_backend': True,
                  'java_frontend_executed': False, 'python_predictor_used': False,
                  'archived_trace_or_value_used': False, 'source_commit': COMMIT,
                  'input_sha256': sha(input_path.read_bytes()),
                  'shared_generator_source_sha256': sha((ROOT / 'cogtool_py/generator.py').read_bytes()),
                  'shared_generated_steps': [asdict(s) for s in script.steps],
                  'source_action_metadata': data['tasks'][0]['demonstration']['steps'],
                  'input_device_transition_contracts': [asdict(t) for t in project.design.transitions
                                                       if getattr(t,'source_type','widget')=='input_device'],
                  'omitted_annotations': omitted_annotations,
                  'writer_source_rules': ['ACTRPredictionAlgo.java:660-734,808-865,901-999,1007-1020',
                      'ACTRPredictionAlgo.java:1233-1270,1484-1636,1640-1741,1742-1805',
                      'ACTRPredictionAlgo.java:1997-2039,2074-2120,2197-2238,2491-2496,2502-2628'],
                  'parameter_assignments': {k: {'lisp': v, 'value': values[k]} for k, v in mapping.items()},
                  'not_used_parameters': ['click_s', 'key_s', 'homing_s'],
                  'source_default_slots': {k: {'source_default': v, 'observed': None} for k, v in
                       [('eye_feature_prep_s', .05), ('eye_initiation_s', .05), ('motor_key_closure_s', .01)]},
                  'limitations': ['Shared KLM generator and input: no independent Java frontend in this route',
                      'Unmodified left click including true Text, lowercase ASCII letters/digits plus source DOWN, homing, Think and explicit duration-free LookAt; no groups',
                      'DOWN is one U+E00D source character, backend slash/right-hand alias and (DOWN) display label; no real host keyboard action',
                      'is_command is retained as action metadata and only affects shared KLM generation; it never inserts a modifier or extra Enter here',
                      'InputDevice transitions carry destination on the last physical key only; no geometric Keyboard widget is invented',
                      'All input frames/widgets/click transitions retained; input may be an explicitly recorded reachable subset of the original design',
                      'Positive transition delays require explicit input delay_label; missing original labels are not invented',
                      'Source default *system-wait-blocks-only-vision*=nil; no preference override',
                      'SBCL source-loading compatibility port, not original CLISP binary',
                      '2009 source/runtime equivalence remains unverified']}
    return '\n\n'.join(text), provenance


def model_text(input_path: Path) -> tuple[str, dict]:
    # Freeze the already-validated NP menu path byte-for-byte. Other admitted
    # tasks use the separate source-transcribed ordinary writer.
    data = json.loads(input_path.read_text())
    steps = data.get('tasks', [{}])[0].get('demonstration', {}).get('steps', [])
    if steps and all(s.get('op') == 'menu_select' for s in steps):
        return _menu_model_text(input_path)
    return _ordinary_model_text(input_path)


def run(input_path: Path, out: Path) -> dict:
    if out.exists():
        raise FileExistsError(f'Refusing existing evidence directory: {out}')
    if Path('/tmp/act-r-kludge.lisp').exists():
        raise ValueError('Refusing unreviewed /tmp/act-r-kludge.lisp override')
    out.mkdir(parents=True)
    (out / 'input.json').write_bytes(input_path.read_bytes())
    (out / 'writer_executed.py').write_bytes(Path(__file__).read_bytes())
    source_copy = out / 'source'
    manifest = verified_copy(source_copy)
    write_json(out / 'upstream_sources.json', {'commit': COMMIT, 'files': manifest})
    patch = patch_loader(source_copy / LOADER)
    (out / 'loader_compatibility.patch').write_text(patch)
    model, provenance = model_text(input_path)
    (out / 'model.lisp').write_text(model)
    write_json(out / 'input_mapping.json', provenance)
    driver = '\n'.join([f'(load {quoted(str(source_copy / LOADER))})',
                        '(format t "~&REFERENCE_STAGE actr-loaded~%")',
                        f'(load {quoted(str(source_copy / RESOURCE / "emma.lisp"))})',
                        '(format t "~&REFERENCE_STAGE emma-loaded~%")',
                        f'(load {quoted(str(source_copy / RESOURCE / "cogtool-actr.lisp"))})',
                        '(format t "~&REFERENCE_STAGE cogtool-loaded~%")',
                        f'(load {quoted(str(out / "model.lisp"))})']) + '\n'
    (out / 'driver.lisp').write_text(driver)
    binary = shutil.which('sbcl')
    if not binary:
        raise ValueError('SBCL runtime unavailable')
    command = [binary, '--noinform', '--disable-debugger', '--script', str(out / 'driver.lisp')]
    record = {'command': command, 'cwd': str(out), 'timeout_s': 90,
              'started_at_utc': datetime.now(timezone.utc).isoformat(),
              'runtime': subprocess.check_output([binary, '--version'], text=True).strip(),
              'platform': platform.platform(), 'machine': platform.machine(),
              'route': 'source_only_public_defconstant_loader_port',
              'loader_patch_sha256': sha(patch.encode()), 'model_sha256': sha(model.encode()),
              'classification': 'ported_reference_backend', 'shared_generator': True}
    start = time.perf_counter()
    try:
        result = subprocess.run(command, cwd=out, capture_output=True, timeout=90)
        stdout, stderr = result.stdout, result.stderr
        record.update(returncode=result.returncode, outcome='completed')
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = exc.stdout or b'', exc.stderr or b''
        record.update(returncode=None, outcome='timeout')
    except OSError as exc:
        stdout, stderr = b'', str(exc).encode()
        record.update(returncode=None, outcome='launch_error')
    record['wall_clock_runtime_s'] = time.perf_counter() - start
    (out / 'stdout.txt').write_bytes(stdout)
    (out / 'stderr.txt').write_bytes(stderr)
    record.update(stdout_sha256=sha(stdout), stderr_sha256=sha(stderr))
    write_json(out / 'process.json', record)
    output = stdout.decode(errors='replace')
    matches = re.findall(r'^REFERENCE_RETURNED_TIME (.+)$', output, re.M)
    success = record['returncode'] == 0 and len(matches) == 1
    summary = {'status': 'BACKEND_EXECUTED' if success else 'NOT_RUN',
               'reference_kind': 'ported_reference_backend', 'shared_generator': True,
               'original_rerun_s': None, 'returned_time_text': matches[0] if matches else None,
               'ported_reference_s': float(matches[0]) if success else None,
               'input_sha256': provenance['input_sha256'], 'source_commit': COMMIT,
               'stage_markers': re.findall(r'^REFERENCE_STAGE (.+)$', output, re.M),
               'process': record, 'limitations': provenance['limitations']}
    write_json(out / 'summary.json', summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    summary = run(args.input.resolve(), args.out.resolve())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary['status'] == 'BACKEND_EXECUTED' else 1


if __name__ == '__main__':
    raise SystemExit(main())

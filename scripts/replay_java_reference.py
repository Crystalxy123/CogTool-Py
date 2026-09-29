#!/usr/bin/env python3
"""Run one complete Java-exported CogTool model on the frozen Lisp backend.

This launcher does not parse .cgt files, generate steps or construct Lisp rules.
It loads the previously validated ACT-R loader, then the byte-preserved complete
Java export (which embeds its own resources and calls cogtool-run-model).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time

COMMIT = 'a91d91e8dcf95d762b6e08020029a36ea079bbba'
FROZEN_PACKAGE_SHA256 = 'd932c55ca8eb3813de6ef59f0ac1683dc62d2732721a968a0b32d71287af23af'
FROZEN_LOADER_SHA256 = 'e29b6056dc5c6c7512eca53fdb25a1b9ec983b478263ac24a33cb1fb7c6357bd'
RESOURCE = 'java/edu/cmu/cs/hcii/cogtool/resources/'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def quote(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def normalize_lines(data: bytes) -> str:
    # FileUtil.copyReaderToWriter preserves each line, uses platform line ends.
    return '\n'.join(data.decode('ascii').splitlines()) + '\n'


def verify_backend(package: Path) -> tuple[Path, dict]:
    raw = (package / 'package_manifest.json').read_bytes()
    if sha(raw) != FROZEN_PACKAGE_SHA256:
        raise ValueError('The supplied package is not the frozen successful backend package')
    manifest = json.loads(raw)
    if manifest['source_commit'] != COMMIT:
        raise ValueError('Backend source commit mismatch')
    for rel, digest in manifest['files'].items():
        path = (package / rel).resolve()
        if package not in path.parents or sha(path.read_bytes()) != digest:
            raise ValueError(f'Frozen package path/hash mismatch: {rel}')
    source = package / manifest['source_directory']
    actual_sources = {p.relative_to(package).as_posix() for p in source.rglob('*') if p.is_file()}
    expected_sources = {p for p in manifest['files'] if p.startswith(manifest['source_directory'] + '/')}
    if actual_sources != expected_sources:
        raise ValueError('Unexpected or missing backend source files')
    loader = source / 'lisp/actr6/load-act-r-6.lisp'
    if sha(loader.read_bytes()) != FROZEN_LOADER_SHA256:
        raise ValueError('Loader differs from the already validated compatibility port')
    return source, {'package_manifest_sha256': sha(raw), 'loader_sha256': sha(loader.read_bytes()),
                    'package_files_verified': len(manifest['files']),
                    'source_file_count': len(actual_sources), 'source_commit': COMMIT,
                    'backend_patch_scope': 'D: unchanged source-only/public-DEFCONSTANT loader compatibility port',
                    'formula_or_rule_patch': False}


def audit_model(raw: bytes, source: Path) -> dict:
    text = normalize_lines(raw)
    resource_matches = []
    end_of_wrapper = None
    for filename in ('emma.lisp', 'cogtool-actr.lisp'):
        data = (source / RESOURCE / filename).read_bytes()
        expected = normalize_lines(data)
        count = text.count(expected)
        if filename == 'cogtool-actr.lisp' and count != 1:
            raise ValueError('Java export must contain the complete unchanged CogTool resource exactly once')
        if count > 1:
            raise ValueError(f'Resource embedded more than once: {filename}')
        start = text.index(expected) if count else None
        end = start + len(expected) if start is not None else None
        resource_matches.append({'resource': RESOURCE + filename, 'source_sha256': sha(data),
                                 'line_end_normalized_sha256': sha(expected.encode('ascii')),
                                 'full_text_match_count': count,
                                 'start_line': text[:start].count('\n') + 1 if start is not None else None,
                                 'end_line': text[:end].count('\n') if end is not None else None})
        if filename == 'cogtool-actr.lisp':
            end_of_wrapper = end
    if resource_matches[0]['start_line'] is not None and resource_matches[0]['start_line'] >= resource_matches[1]['start_line']:
        raise ValueError('Embedded resource order differs from original Java outputModel')
    tail = text[end_of_wrapper:]
    entry = '(setq *cogtool-result* (cogtool-run-model))'
    if not tail.rstrip().endswith(entry) or tail.count(entry) != 1:
        raise ValueError('Java output must retain the single original final run entry')
    if '(defun define-design ()' not in tail or '(define-cogtool-model ' not in tail:
        raise ValueError('Complete design/script forms missing after embedded resources')
    return {'java_export_sha256': sha(raw), 'java_export_bytes': len(raw),
            'full_export_preserved': True, 'path_patch_applied': False,
            'resources': resource_matches,
            'execution_order': ['frozen ACT-R loader', 'complete Java export: optional EMMA',
                                'complete Java export: CogTool wrapper', 'Java design', 'Java script/model',
                                'Java final cogtool-run-model entry', 'launcher read-only observations'],
            'effective_configuration_policy': 'Java export unchanged; no Python parameter, scene, rule or termination override',
            'original_entry': entry,
            'generated_pref_assignments_text': re.findall(r'^\(setq \*overridden-global-parameters\*.*$', tail, re.M),
            'generated_model_start_text': re.findall(r'^\(define-cogtool-model .*$', tail, re.M),
            'generated_production_definition_order': re.findall(r'^\(p\s+(\S+)', tail, re.M),
            'comparison_note': 'Static integrity audit only; no Lisp forms sorted or rewritten'}


def capture(argv: list[str], out: Path, timeout: int = 90) -> tuple[dict, str]:
    record = {'command': argv, 'cwd': str(out), 'timeout_s': timeout,
              'started_at_utc': datetime.now(timezone.utc).isoformat()}
    start = time.perf_counter()
    try:
        done = subprocess.run(argv, cwd=out, capture_output=True, timeout=timeout)
        stdout, stderr = done.stdout, done.stderr
        record.update(returncode=done.returncode, outcome='completed')
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = exc.stdout or b'', exc.stderr or b''
        record.update(returncode=None, outcome='timeout')
    except OSError as exc:
        stdout, stderr = b'', str(exc).encode()
        record.update(returncode=None, outcome='launch_error')
    record.update(wall_clock_runtime_s=time.perf_counter() - start,
                  stdout_sha256=sha(stdout), stderr_sha256=sha(stderr))
    (out / 'stdout.txt').write_bytes(stdout)
    (out / 'stderr.txt').write_bytes(stderr)
    write_json(out / 'process.json', record)
    return record, stdout.decode(errors='replace')


def parse_observations(output: str) -> dict:
    returned = re.findall(r'^REFERENCE_RETURNED_TIME (.+)$', output, re.M)
    value = None
    if len(returned) == 1:
        literal = returned[0].replace('d', 'e').replace('D', 'e')
        try:
            parsed = Decimal(literal)
        except InvalidOperation:
            parsed = None
        if parsed is not None and parsed.is_finite():
            value = float(parsed)
    events = []
    parameters = []
    phase = 'original_java_model_parameter_print'
    for number, line in enumerate(output.splitlines(), 1):
        if line == 'REFERENCE_EFFECTIVE_PARAMETERS_BEGIN':
            phase = 'post_run_read_only_parameter_query'
        match = re.match(r'^\s*(\d+\.\d+)\s+(\S+)\s+(.*)$', line)
        if match:
            events.append({'stdout_line': number, 'time_text': match[1], 'time_s': float(match[1]),
                           'module': match[2], 'action': match[3]})
        parameter = re.match(r'^(:[\w-]+)\s+(.+?)\s+default:\s+(.+?)\s+:\s+(.*)$', line)
        if parameter:
            parameters.append({'name': parameter[1], 'value_text': parameter[2],
                               'default_text': parameter[3], 'description': parameter[4],
                               'stdout_line': number, 'phase': phase})
    def last(pattern, module=None):
        matches = [event for event in events if (module is None or event['module'].upper() == module)
                   and re.search(pattern, event['action'], re.I)]
        return matches[-1] if matches else None
    return {'returned_time_text': returned[0] if len(returned) == 1 else None,
            'prediction_s': value, 'raw_returned_time_rational': next(iter(re.findall(r'^REFERENCE_RETURNED_TIME_RATIONAL (.+)$', output, re.M)), None),
            'stop_event': last(r'^PRODUCTION-FIRED STOP-', 'PROCEDURAL'),
            'last_device_output': last(r'^DEVICE-(?:CLICK|MOVE-CURSOR-TO|PRESS-KEY|SPEAK-STRING|EMIT-GRAFFITI)\b', 'COGTOOL'),
            'last_manual_release': last(r'^FINISH-MOVEMENT\b', 'MOTOR'),
            'queue_end_event': last(r'^Stopped because no events left to process'),
            'post_run_goal_text': next(iter(re.findall(r'^REFERENCE_FINAL_GOAL (.+)$', output, re.M)), None),
            'runtime_parameters': parameters, 'events': events,
            'full_resource_snapshots': None, 'unprinted_synchronous_events': None}


def replay(model: Path, generation_record: Path, package: Path, out: Path, case_id: str) -> dict:
    model, generation_record, package, out = [p.resolve() for p in (model, generation_record, package, out)]
    if out.exists():
        raise FileExistsError(f'Refusing existing evidence directory: {out}')
    if Path('/tmp/act-r-kludge.lisp').exists():
        raise ValueError('Refusing unreviewed /tmp/act-r-kludge.lisp override')
    generation = json.loads(generation_record.read_text())
    for key in ('java_generation_executed', 'fresh_regeneration_verified'):
        if generation.get(key) is not True:
            raise ValueError(f'Fresh Java generation not verified: {key}')
    for key in ('raw_reader_shared', 'step_generator_shared', 'lisp_writer_shared'):
        if generation.get(key) is not False:
            raise ValueError(f'This main J-L route requires independently verified {key}=false')
    if generation.get('case_id') != case_id or generation.get('source_commit') != COMMIT:
        raise ValueError('Java generation case/version mismatch')
    raw = model.read_bytes()
    if generation.get('model_sha256') != sha(raw):
        raise ValueError('Java generation record does not identify the supplied complete model bytes')
    source, backend = verify_backend(package)
    audit = audit_model(raw, source)
    binary = shutil.which('sbcl')
    if binary is None:
        raise ValueError('Previously available SBCL missing; no recovery attempted')
    out.mkdir(parents=True)
    original = out / 'java_export_original.lisp'
    original.write_bytes(raw)
    (out / 'generation_record.json').write_bytes(generation_record.read_bytes())
    (out / 'launcher_executed.py').write_bytes(Path(__file__).read_bytes())
    write_json(out / 'model_integrity.json', audit)
    write_json(out / 'backend_identity.json', backend)
    loader = source / 'lisp/actr6/load-act-r-6.lisp'
    observations = []
    if audit['resources'][0]['full_text_match_count'] == 1:
        observations.append('(format t "~&REFERENCE_FINAL_SLOTS ~S~%" (list :auto-attend (auto-attend (get-module :vision)) :eye-feature-prep-s (feat-prep-time (get-module :vision)) :eye-initiation-s (init-time (get-module :vision)) :key-closure-s (key-closure-time (current-device-interface)) :eye-location (eye-loc (get-module :vision))))')
    driver = '\n'.join([
        f'(load {quote(str(loader))})',
        '(format t "~&REFERENCE_STAGE frozen-actr-loaded~%")',
        f'(load {quote(str(original))})',
        '(format t "~&REFERENCE_STAGE complete-java-export-loaded-and-run~%")',
        '(format t "~&REFERENCE_RETURNED_TIME ~S~%" *cogtool-result*)',
        '(format t "~&REFERENCE_RETURNED_TIME_RATIONAL ~S~%" (rational *cogtool-result*))',
        '(format t "~&REFERENCE_FINAL_MP_TIME ~S~%" (mp-time))',
        '(format t "~&REFERENCE_FINAL_GOAL ~S~%" (buffer-read \'goal))',
        '(format t "~&REFERENCE_EFFECTIVE_PARAMETERS_BEGIN~%")',
        '(sgp)',
        '(format t "~&REFERENCE_EFFECTIVE_PARAMETERS_END~%")',
        *observations, '(format t "~&~S~%" *cogtool-result*)']) + '\n'
    (out / 'driver.lisp').write_text(driver)
    command = [binary, '--noinform', '--disable-debugger', '--script', str(out / 'driver.lisp')]
    process, output = capture(command, out)
    observed = parse_observations(output)
    write_json(out / 'runtime_observations.json', observed)
    complete = (process['returncode'] == 0 and observed['prediction_s'] is not None
                and observed['stop_event'] is not None and observed['queue_end_event'] is not None)
    summary = {'case_id': case_id, 'pipeline': 'J-L',
               'frontend_route': generation.get('frontend_route'),
               'raw_reader_shared': False, 'step_generator_shared': False, 'lisp_writer_shared': False,
               'java_generation_executed': True, 'fresh_regeneration_verified': True,
               'frontend_generation_status': 'fresh_java_export_verified',
               'backend_kind': 'ported_reference_backend', 'backend_patch_scope': backend['backend_patch_scope'],
               'frontend_patch_scope': generation.get('frontend_patch_scope'),
               'execution_status': 'complete' if complete else ('error' if process['returncode'] != 0 else 'partial'),
               'prediction_s': observed['prediction_s'], 'original_rerun_s': None,
               'returned_time_text': observed['returned_time_text'],
               'model_sha256': sha(raw), 'source_commit': COMMIT,
               'path_patch_applied': False, 'full_java_export_loaded': True,
               'wall_clock_runtime_s': process['wall_clock_runtime_s'],
               'runtime': subprocess.check_output([binary, '--version'], text=True).strip(),
               'generation_comparison_status': 'not_run_by_this_launcher',
               'trace_comparison_status': 'not_run_by_this_launcher',
               'first_difference': None,
               'reason': 'Actual Java export on unchanged compatibility-ported backend; comparisons require separate evidence'}
    write_json(out / 'summary.json', summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True, type=Path)
    parser.add_argument('--generation-record', required=True, type=Path)
    parser.add_argument('--backend-package', required=True, type=Path)
    parser.add_argument('--case-id', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    summary = replay(args.model, args.generation_record, args.backend_package, args.out, args.case_id)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary['execution_status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())

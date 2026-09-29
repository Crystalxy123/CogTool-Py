#!/usr/bin/env python3
"""Bounded upstream-only Lisp smoke probes and NP-B1 source-version audit.

No Java generator, converted Python model, archived time, or archived trace is
used to compute a reference answer. Source copies alone may receive Lisp fasls.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.convert_phone_case import CODE_COMMIT, read_phone, field, scalar, classname

SOURCE = ROOT / 'reference/upstream-cogtool'
REPO = ROOT / 'cogtool'
JAVA = 'java/edu/cmu/cs/hcii/cogtool/'
LISP_RESOURCE = JAVA + 'resources/cogtool-actr.lisp'
FIRST_IMPORT = '8318aaa19000ccfbdb2f08131da2593a374c6a99'
RELEASE12_IMPORT = 'ec5ccdf9a43b2b053bf62276b16af2064d59af42'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def capture(argv: list[str], cwd: Path, folder: Path, timeout: int = 60) -> dict:
    folder.mkdir(parents=True, exist_ok=False)
    before = time.perf_counter()
    record = {'command': argv, 'cwd': str(cwd), 'timeout_s': timeout,
              'started_at_utc': datetime.now(timezone.utc).isoformat()}
    try:
        done = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=timeout)
        stdout, stderr = done.stdout, done.stderr
        record.update(returncode=done.returncode, outcome='completed')
    except subprocess.TimeoutExpired as exc:
        stdout, stderr = exc.stdout or b'', exc.stderr or b''
        record.update(returncode=None, outcome='timeout')
    except OSError as exc:
        stdout, stderr = b'', str(exc).encode()
        record.update(returncode=None, outcome='launch_error')
    record['wall_clock_runtime_s'] = time.perf_counter() - before
    (folder / 'stdout.txt').write_bytes(stdout)
    (folder / 'stderr.txt').write_bytes(stderr)
    record.update(stdout_sha256=digest(stdout), stderr_sha256=digest(stderr))
    write(folder / 'process.json', record)
    return record


def git(*args: str) -> str:
    return subprocess.check_output(['git', '-C', str(REPO), *args], text=True).strip()


def snippets(text: str, markers: tuple[str, ...], margin: int = 3) -> list[dict]:
    lines = text.splitlines()
    return [{'marker': marker, 'line': i + 1,
             'snippet_first_line': max(1, i + 1 - margin),
             'text': '\n'.join(lines[max(0, i-margin): i+margin+1])}
            for marker in markers for i, line in enumerate(lines) if marker in line]


def failure_summary(error: str) -> str | None:
    if 'The function SB-C::%DEFCONSTANT is undefined.' in error:
        return 'Original loader references missing SB-C::%DEFCONSTANT; process-local package unlock does not restore the old internal API.'
    if 'Lock on package SB-C violated when interning %DEFCONSTANT' in error:
        return 'Original loader line 269 cannot read SB-C::%DEFCONSTANT because the modern SBCL package is locked.'
    if error.strip():
        return '\n'.join(error.strip().splitlines()[:5])
    return None


def version_audit() -> dict:
    graph, provenance = read_phone()
    result = graph.index['307']
    trace = [scalar(n) for n in graph.get(result, 'traceLines')]
    parameters = []
    for number, line in enumerate(trace, 1):
        match = re.match(r'^(:[A-Za-z0-9-]+)\s+(.+?)\s+default:\s+(.+?)\s+:\s+(.*)$', line)
        if match:
            parameters.append({'trace_line_1based': number, 'parameter': match[1],
                               'observed_value_text': match[2], 'printed_default_text': match[3],
                               'description': match[4], 'raw': line,
                               'value_category': 'archived_reference',
                               'used_as_current_input': False})
    alg = graph.index['306']
    flags = {key: {'class': classname(graph.index[key]),
                   'invalidCount': scalar(field(graph.index[key], 'invalidCount')),
                   'obsoleteCount': scalar(field(graph.index[key], 'obsoleteCount'))}
             for key in ('284', '287', '294', '297', '300', '302')}
    queries = {
        'shallow': git('rev-parse', '--is-shallow-repository'),
        'reachable_commit_count': int(git('rev-list', '--all', '--count')),
        'log': git('log', '--all', '--format=%H %ad %s', '--date=iso-strict').splitlines(),
        'tags': git('show-ref', '--tags').splitlines(),
        'release_1_2_2_peeled_commit': git('rev-parse', '1.2.2^{commit}'),
        'r3035_log_matches': git('log', '--all', '--grep=3035', '--format=%H %s'),
        'year_2009_log_matches': git('log', '--all', '--since=2009-01-01', '--until=2009-12-31', '--format=%H %s'),
    }
    source_checks = [
        (LISP_RESOURCE, ('(set-cursor-position 0 0)', '(cursor-x :initform 0', ':visual-encoding-factor', '*default-global-parameters*', '(defun frame-vis-loc-template')),
        (JAVA + 'model/KLMCognitiveGenerator.java', ('produceMenuSteps(', 'WidgetType.ContextMenu', 'WidgetAttributes.RIGHT_CLICK', 'produceItemSteps(')),
        (JAVA + 'model/WidgetAttributes.java', ('CONTEXT_MENU_ACTION_ATTR', 'RIGHT_CLICK', 'SUBMENU_DELAY_ATTR')),
        (JAVA + 'model/ACTR6PredictionAlgo.java', ("Nothing to save", 'return ONLY;')),
        (JAVA + 'model/APredictionResult.java', ('IS_COMPUTED = 1',)),
        (JAVA + 'model/Demonstration.java', ('boolean isInvalid()', 'boolean isObsolete()')),
    ]
    versions = []
    for commit, label in ((FIRST_IMPORT, 'earliest_available_2013_import'),
                          (RELEASE12_IMPORT, 'release_1_2_imported_2013'),
                          (CODE_COMMIT, 'fixed_2014_reference')):
        files = []
        for path, markers in source_checks:
            proc = subprocess.run(['git', '-C', str(REPO), 'show', f'{commit}:{path}'], capture_output=True)
            if proc.returncode:
                files.append({'path': path, 'available': False, 'error': proc.stderr.decode(errors='replace')})
                continue
            data = proc.stdout
            files.append({'path': path, 'available': True, 'git_blob': git('rev-parse', f'{commit}:{path}'),
                          'sha256': digest(data), 'matches': snippets(data.decode(), markers)})
        versions.append({'commit': commit, 'label': label, 'files': files,
                         'is_proven_2009_r3035_source': False})
    fixed_text = (SOURCE / LISP_RESOURCE).read_text()
    # A textual correspondence, not a simulation or a transfer of defaults.
    parameter_correspondence = []
    for name, value in ((':ESC', 't'), (':LF', '0'), (':MOTOR-FEATURE-PREP-TIME', '0.001'),
                        (':VISUAL-ENCODING-FACTOR', '0.006'), (':VISUAL-ENCODING-EXPONENT', '0.4')):
        observed = next(p for p in parameters if p['parameter'] == name)
        matches = snippets(fixed_text, (name.lower() + ' ' + value,), margin=2)
        parameter_correspondence.append({'parameter': name, 'archived_observed_value_text': observed['observed_value_text'],
                                         'archived_trace_line_1based': observed['trace_line_1based'],
                                         'fixed_2014_declaration_value_text': value, 'fixed_2014_source': LISP_RESOURCE,
                                         'fixed_2014_matches': matches,
                                         'interpretation': 'Textual agreement only; not proof of identical complete model/parameters/runtime',
                                         'used_as_current_input': False})
    return {
        'case_id': 'NP-B1', 'provenance': provenance,
        'value_categories': ['published_reference', 'archived_reference', 'original_rerun', 'diagnostic_python'],
        'archive_flags': {'result_object_id': '307', 'result_class': classname(result),
                          'resultState': scalar(field(result, 'resultState')),
                          'traceVersion': scalar(field(result, '__ACTRPredictionAlgo.traceVersion')),
                          'script_object_id': '291', 'algorithm_object_id': '306',
                          'algorithm_class': classname(alg), 'algorithm_version': alg.get('version'),
                          'algorithm_persisted_parameter_fields': [n.attrib for n in alg.iter() if n.get('var')],
                          'demonstration_and_steps': flags,
                          'archived_prediction_s': scalar(field(result, 'taskTime')),
                          'state_interpretation': 'Saved internal computed state, not an independent current validation'},
        'archive_trace_header': trace[:4], 'saved_trace_parameters': parameters,
        'parameter_correspondence': parameter_correspondence,
        'initial_state_saved': {n.get('var'): scalar(n) for n in graph.index['285'] if n.get('var')},
        'initial_mouse_position_saved': None,
        'source_version_alignment': {
            'saved_version': '1.0.4', 'saved_revision': '3035', 'source_2009_commit': None,
            'nearest_available_source_commit': FIRST_IMPORT,
            'nearest_available_source_date': '2013-12-02',
            'fixed_reference_commit': CODE_COMMIT, 'git_history_evidence': queries,
            'source_snapshots': versions,
            'default_transfer_2009_to_2014_verified': False,
            'mouse_0_0_status': 'conditional_2014_source_default_only; not stored in 2009 model and not verified against r3035',
            'generation_rules_status': '2009 archived generated sequence agrees at coarse action labels; exact r3035 generation semantics unverified',
            'parameters_status': '2009 trace prints archived parameters; 2014 source defaults and baseline input parameters are separate evidence, not interchangeable'},
        'staleness_assessment': {
            'saved_invalid_or_obsolete_flag_detected': False,
            'saved_validity_does_not_establish_current_validity': True,
            'unresolved': ['r3035 source unavailable in local full Git history',
                           'algorithm singleton stores no parameter fields',
                           'traceVersion 2 identifies trace format, not runtime/source equivalence',
                           'opening old files in new Java code may migrate serialized models',
                           'cached trace and taskTime were not produced in this run'],
            'reference_status': 'archived_reference_only'},
        'original_rerun_s': None, 'current_original_prediction_computed': False,
    }


def copy_verified_sources(destination: Path) -> list[dict]:
    files = sorted((SOURCE / 'lisp/actr6').rglob('*'))
    files = [p for p in files if p.is_file() and p.suffix == '.lisp']
    files += [SOURCE / (JAVA + 'resources/emma.lisp'), SOURCE / LISP_RESOURCE]
    git_entries = {}
    for line in git('ls-tree', '-r', CODE_COMMIT).splitlines():
        desc, path = line.split('\t', 1)
        git_entries[path] = desc.split()[2]
    records = []
    for path in files:
        relative = path.relative_to(SOURCE)
        data = path.read_bytes()
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        if git_entries.get(str(relative)) != blob:
            raise ValueError(f'Pinned source differs from fixed Git blob: {relative}')
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        records.append({'path': str(relative), 'git_blob': blob, 'sha256': digest(data), 'bytes': len(data)})
    return records


def second_route(out: Path, copies: Path, binary: str, first: dict) -> dict | None:
    """At most one evidence-driven follow-up, with no source or model patch."""
    error = (out / 'route1/stderr.txt').read_text()
    driver = out / 'route2-driver.lisp'
    if first['success']:
        driver.write_text('(load "lisp/actr6/load-act-r-6.lisp")\n'
                          '(load "' + JAVA + 'resources/emma.lisp")\n'
                          '(load "' + LISP_RESOURCE + '")\n'
                          '(format t "~&UPSTREAM_COGTOOL_SUPPORT_LOAD_COMPLETE~%")\n')
        route_id = 'sbcl_unmodified_cogtool_support'
        shim = None
        marker = 'UPSTREAM_COGTOOL_SUPPORT_LOAD_COMPLETE'
        basis = 'ACTRPredictionAlgo.java:556-562 loads EMMA before CogTool boilerplate'
    elif 'Lock on package SB-C violated when interning %DEFCONSTANT' in error:
        # Explicit bounded compatibility investigation. This unlocks only this
        # child Lisp process; it does not add/redefine missing functions.
        driver.write_text('; Runtime compatibility shim: process-local SB-C package unlock only.\n'
                          '(sb-ext:unlock-package :sb-c)\n'
                          '(load "lisp/actr6/load-act-r-6.lisp")\n'
                          '(format t "~&UPSTREAM_ACTR_LOAD_WITH_PACKAGE_UNLOCK_COMPLETE~%")\n')
        route_id = 'sbcl_actr_loader_process_local_package_unlock'
        shim = {'type': 'runtime_compatibility_shim', 'form': '(sb-ext:unlock-package :sb-c)',
                'scope': 'child SBCL process only', 'upstream_source_modified': False,
                'cognitive_rules_modified': False, 'missing_functions_replaced': False}
        marker = 'UPSTREAM_ACTR_LOAD_WITH_PACKAGE_UNLOCK_COMPLETE'
        basis = 'Route 1 observed SB-C package lock at original loader line 269; test only whether package access is the blocker'
    else:
        return None
    second = capture([binary, '--noinform', '--disable-debugger', '--script', str(driver)], copies, out / 'route2', 60)
    second.update(route_id=route_id, purpose='engine_only_load_smoke',
                  upstream_support_evidence=basis, runtime_compatibility_shim=shim,
                  uses_python_model=False, produces_np_b1_prediction=False,
                  success=second['returncode'] == 0 and marker in (out / 'route2/stdout.txt').read_text())
    second['failure_summary'] = failure_summary((out / 'route2/stderr.txt').read_text()) if not second['success'] else None
    return second


def probe(out: Path) -> dict:
    out = out.resolve()
    if out.exists():
        raise ValueError(f'Output already exists; choose a new evidence directory: {out}')
    if out == ROOT or not out.is_relative_to(ROOT / 'reports'):
        raise ValueError('Probe outputs must be a new directory below workspace reports/')
    out.mkdir(parents=True)
    write(out / 'npb1_version_audit.json', version_audit())
    binaries = {name: shutil.which(name) for name in ('sbcl', 'clisp', 'ccl', 'ecl', 'abcl', 'java', 'docker', 'qemu-system-i386', 'qemu-i386', 'wine')}
    inventory = {'platform': platform.platform(), 'machine': platform.machine(), 'binaries': binaries,
                 'installed_or_downloaded_anything': False, 'network_used': False,
                 'previous_failed_routes_not_repeated': ['java -d32', 'Java source/target 1.5 compilation', 'i386 CLISP binary']}
    routes = []
    if binaries['sbcl']:
        inventory['sbcl_version_probe'] = capture([binaries['sbcl'], '--version'], ROOT, out / 'environment/sbcl', 10)
        copies = out / 'source_copy'
        manifest = copy_verified_sources(copies)
        write(out / 'source_copy_manifest.json', {'commit': CODE_COMMIT, 'files': manifest})
        first = out / 'route1-driver.lisp'
        first.write_text('(load "lisp/actr6/load-act-r-6.lisp")\n(format t "~&UPSTREAM_ACTR_LOAD_COMPLETE~%")\n')
        r1 = capture([binaries['sbcl'], '--noinform', '--disable-debugger', '--script', str(first)], copies, out / 'route1', 60)
        r1.update(route_id='sbcl_unmodified_actr_loader', purpose='engine_only_load_smoke',
                  upstream_support_evidence='lisp/actr6/load-act-r-6.lisp:268-270,337-338,351',
                  uses_python_model=False, produces_np_b1_prediction=False,
                  success=r1['returncode'] == 0 and 'UPSTREAM_ACTR_LOAD_COMPLETE' in (out / 'route1/stdout.txt').read_text())
        r1['failure_summary'] = failure_summary((out / 'route1/stderr.txt').read_text()) if not r1['success'] else None
        routes.append(r1)
        r2 = second_route(out, copies, binaries['sbcl'], r1)
        if r2 is not None:
            routes.append(r2)
        inventory['reference_sources_unchanged'] = all(digest((SOURCE / r['path']).read_bytes()) == r['sha256'] for r in manifest)
    inventory['second_route_policy'] = 'At most one follow-up: CogTool support if base loading succeeds, or process-local SB-C unlock if the exact observed SB-C %DEFCONSTANT package lock occurs. No source patches or later fixes.'
    write(out / 'environment.json', inventory)
    # The pinned phone example contains only README, paper, and serialized model.
    # No generated Lisp model is obtained by treating the cached trace as code.
    phone_files = sorted(str(p.relative_to(ROOT)) for p in (ROOT / 'reference/upstream-documentation/examples/phone-number-lookup').iterdir() if p.is_file())
    summary = {'status': 'ENGINE_ONLY_NO_ORIGINAL_PREDICTION', 'case_id': 'NP-B1',
               'original_rerun_s': None, 'original_model_executed': False,
               'backend_execution_attempts': len(routes), 'maximum_attempts': 2,
               'routes': routes, 'phone_example_files': phone_files,
               'official_np_b1_generated_lisp_available': False,
               'source_2009_commit': None, 'fixed_reference_commit': CODE_COMMIT,
               'blockers': ['No exact 2009 r3035 source commit in local full history',
                            'No official NP-B1 generated Lisp in pinned phone example',
                            'Java model loading/generation remains unavailable in current environment'],
               'rerun_command': ['.venv/bin/python', 'scripts/probe_reference_routes.py', '--out', '<new reports/.../reference_routes directory>']}
    write(out / 'summary.json', summary)
    write_report(out, summary)
    return summary


def write_report(out: Path, summary: dict) -> None:
    audit = json.loads((out / 'npb1_version_audit.json').read_text())
    routes = summary['routes']
    lines = ['# NP-B1 上游运行路线与版本核查', '',
             '本轮最多两次后端尝试，均只加载固定上游源码；未生成或执行 NP-B1 原版模型，original_rerun_s=null。未安装软件、未访问网络，未重复旧失败路线。', '',
             '## 版本与缓存', '',
             '官方 .cgt 保存版本为 1.0.4 r3035（2009-05-06）。本地非浅 Git 仓库仅 16 个可达提交，最早为 2013-12-02 的初始导入；1.2.2 标签指向同日导入的 1.2 分支。无法把这些快照认定为 r3035，所以 source_2009_commit=null。', '',
             '对象 307 的 resultState=1、traceVersion=2；算法 306 是 ACTR6PredictionAlgo，未保存参数字段。演示 284 和步骤 287/294/297/300/302 的 invalidCount 与 obsoleteCount 都是 0。这些仅是保存时内部标记，不能排除版本迁移及运行环境变化造成的陈旧风险。', '',
             '模型未保存鼠标坐标。候选输入 (0,0) 来自固定 2014 源码，必须改标为 **2014 条件默认**，不能声称是 2009 模型的已验证初态。模型保存的右手 M、左手 K、mouseHand=true 则是原始字段。', '',
             f'旧 trace 解析出 {len(audit["saved_trace_parameters"])} 条参数打印记录；全部分类 archived_reference，未用于设定当前输入。2014 源码默认值、当前基线参数和这些旧参数分开列示，不相互替代。', '',
             '其中 ESC=t、LF=0、motor-feature-prep-time=0.001、visual-encoding-factor=0.006、visual-encoding-exponent=0.4 在旧 trace 与固定 2014 参数声明上文字一致。该局部一致不足以证明完整参数、模型、算法和运行时一致；未据此修改当前输入。', '',
             '## 本机路线', '']
    for r in routes:
        lines += [f'- {r["route_id"]}: outcome={r["outcome"]}, returncode={r["returncode"]}, success={r["success"]}；仅后端加载检查。']
        if r.get('runtime_compatibility_shim'):
            lines += ['  第二次仅使用 runtime compatibility shim `(sb-ext:unlock-package :sb-c)`，作用于该子进程；不改源文件、不替换函数、不改认知规则。']
        folder = 'route1' if r is routes[0] else 'route2'
        error = (out / folder / 'stderr.txt').read_text()
        if r['returncode'] != 0:
            lines += ['', failure_summary(error) or 'See raw stderr for failure.', '',
                      '```text', '\n'.join(error.splitlines()[:10]), '```', '']
    lines += ['', 'SBCL 支持有原 loader 的 #+:sbcl 分支依据。所有可编译源文件先验证固定 Git blob，再复制到本目录 source_copy；产生的编译文件不会写入参考目录。两层加载均无 Python 模型或旧 trace 回放。', '',
              '固定电话示例没有可直接运行的官方 NP-B1 生成 Lisp；Java 生成链也没有可用的新运行依据。本次后端加载不产生任何新的原版预测值。运行命令、实耗、退出码、stdout/stderr 与源码哈希均随报告保留。', '',
              '重跑：`.venv/bin/python scripts/probe_reference_routes.py --out reports/validation/<new-run>/reference_routes`；必须指定新目录，已有证据拒绝覆盖。']
    (out / 'REPORT_zh.md').write_text('\n'.join(lines) + '\n')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = probe(args.out)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'Probe could not finish: {exc}', file=sys.stderr)
        return 2
    print(json.dumps({'status': summary['status'], 'backend_execution_attempts': summary['backend_execution_attempts'],
                      'original_rerun_s': None}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

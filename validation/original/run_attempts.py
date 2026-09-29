"""Collect truthful local prerequisites/build/runtime attempts for the fixed source.

This does not create reference predictions or mark any differential test passed.
Only build output inside validation/original is allowed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'reference/upstream-cogtool'
OUT = ROOT / 'validation/original/attempts'
SOURCE_SHA = 'a91d91e8dcf95d762b6e08020029a36ea079bbba'
OUT.mkdir(parents=True, exist_ok=True)
(ROOT / 'validation/original/build').mkdir(exist_ok=True)
(ROOT / 'validation/original/dist').mkdir(exist_ok=True)

def run(name: str, args: list[str], timeout: int = 30) -> dict:
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    record = {'id': name, 'command': args, 'cwd': str(ROOT / 'validation/original'),
              'started_at_utc': started, 'timeout_seconds': timeout}
    try:
        completed = subprocess.run(args, cwd=ROOT / 'validation/original',
                                   capture_output=True, text=True, timeout=timeout,
                                   errors='replace', check=False)
        record.update(returncode=completed.returncode, outcome='completed')
        stdout, stderr = completed.stdout, completed.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        record.update(returncode=None, outcome=type(exc).__name__, exception=str(exc))
        stdout, stderr = '', ''
    for stream, content in [('stdout', stdout), ('stderr', stderr)]:
        target = OUT / f'{name}.{stream}.txt'
        target.write_text(content, encoding='utf-8')
        record[f'{stream}_path'] = str(target.relative_to(ROOT))
        record[f'{stream}_sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
    record['finished_at_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    (OUT / f'{name}.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    return record

commands = [
    ('01_os', ['/usr/bin/sw_vers']),
    ('02_architecture', ['/usr/bin/uname', '-a']),
    ('03_java_installations', ['/usr/libexec/java_home', '-V']),
    ('04_java_version', ['/usr/bin/java', '-version']),
    ('05_javac_version', ['/usr/bin/javac', '-version']),
    ('06_ant_version', ['/bin/zsh', '-c', 'ant -version']),
    ('07_binary_architectures', ['/usr/bin/file', str(SOURCE / 'clisp-mac-intel/lisp.run'),
       str(SOURCE / 'lisp/clisp/mac-intel/base/lisp.run'),
       *map(str, sorted((SOURCE / 'lib/macintosh').glob('*.jnilib'))),
       str(SOURCE / 'jre/bin/java.exe')]),
    ('08_compile_fixed_source', ['/bin/zsh', '-c', 'exec ant "$@"', 'ant',
       '-f', str(SOURCE / 'build.xml'),
       '-Dbuilddir=' + str(ROOT / 'validation/original/build'),
       '-Ddistdir=' + str(ROOT / 'validation/original/dist'), 'compile']),
    ('09_run_bundled_clisp', ['/bin/zsh', '-c', 'exec "$@"', 'original-clisp',
       str(SOURCE / 'clisp-mac-intel/lisp.run'),
       '-M', str(SOURCE / 'clisp-mac-intel/actr6.mem'),
       '-x', '(progn (print :cogtool-validation-runtime-started) (ext:quit))']),
]
records = [run(name, args) for name, args in commands]
artifacts = []
for rel in ['reference/upstream-cogtool/build.xml',
            'reference/upstream-cogtool/clisp-mac-intel/lisp.run',
            'reference/upstream-cogtool/clisp-mac-intel/actr6.mem',
            'reference/upstream-cogtool/lib/macintosh/cogtoolstart',
            'reference/upstream-documentation/Processes/configuring-development-machines.txt',
            'reference/upstream-documentation/Processes/building-lisp-memory-images.txt',
            'CogTool.dmg']:
    p = ROOT / rel
    artifacts.append({'path': rel, 'bytes': p.stat().st_size,
                      'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
manifest = {'schema_version': '1', 'source_repository': 'https://github.com/cogtool/cogtool',
            'source_commit': SOURCE_SHA, 'status': 'unverified',
            'differential_tests': 'not_executed',
            'note': 'No original task prediction was obtained; commands are prerequisites/build/runtime attempts only.',
            'collected_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'platform': platform.platform(), 'machine': platform.machine(),
            'python': platform.python_version(),
            'tools_on_path': {x: shutil.which(x) for x in ['java', 'javac', 'ant', 'clisp']},
            'attempts': records, 'artifacts': artifacts}
(OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'status': manifest['status'], 'differential_tests': manifest['differential_tests'],
                  'attempts': [{'id': r['id'], 'returncode': r['returncode'], 'outcome': r['outcome']} for r in records]}, indent=2))

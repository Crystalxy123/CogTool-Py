#!/usr/bin/env python3
"""Replay a hashed, self-contained 2014 Lisp reference package in modern SBCL.

No cogtool_py dependency. The package contains a compatibility-ported loader,
unchanged upstream computational source and a previously generated Lisp model.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def quote(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def replay(package: Path, out: Path, case: str | None = None) -> dict:
    package = package.resolve()
    if out.exists():
        raise FileExistsError(f'Refusing existing evidence directory: {out}')
    if Path('/tmp/act-r-kludge.lisp').exists():
        raise ValueError('Refusing unreviewed /tmp/act-r-kludge.lisp override')
    manifest = json.loads((package / 'package_manifest.json').read_text())
    for rel, expected in manifest['files'].items():
        path = (package / rel).resolve()
        if package not in path.parents or sha(path.read_bytes()) != expected:
            raise ValueError(f'Package path/hash mismatch: {rel}')
    cases = manifest['cases']
    if case is None:
        if len(cases) != 1:
            raise ValueError('Select one --case from this multi-model package')
        case = next(iter(cases))
    if case not in cases:
        raise ValueError(f'Unknown package case {case}')
    model = package / cases[case]['model']
    if model.relative_to(package).as_posix() not in manifest['files']:
        raise ValueError('Selected model is not covered by package manifest')
    source = package / manifest['source_directory']
    loader = source / 'lisp/actr6/load-act-r-6.lisp'
    resource = source / 'java/edu/cmu/cs/hcii/cogtool/resources'
    for path in (loader, resource / 'emma.lisp', resource / 'cogtool-actr.lisp'):
        if path.relative_to(package).as_posix() not in manifest['files']:
            raise ValueError('Runtime entry is not covered by package manifest')
    binary = shutil.which('sbcl')
    if not binary:
        raise ValueError('SBCL runtime unavailable; no installation attempted')
    out.mkdir(parents=True)
    driver = '\n'.join([f'(load {quote(str(loader))})',
                        '(format t "~&REFERENCE_STAGE actr-loaded~%")',
                        f'(load {quote(str(resource / "emma.lisp"))})',
                        '(format t "~&REFERENCE_STAGE emma-loaded~%")',
                        f'(load {quote(str(resource / "cogtool-actr.lisp"))})',
                        '(format t "~&REFERENCE_STAGE cogtool-loaded~%")',
                        f'(load {quote(str(model))})']) + '\n'
    (out / 'driver.lisp').write_text(driver)
    command = [binary, '--noinform', '--disable-debugger', '--script', str((out / 'driver.lisp').resolve())]
    record = {'command': command, 'cwd': str(out.resolve()), 'timeout_s': 90,
              'started_at_utc': datetime.now(timezone.utc).isoformat(),
              'package_manifest_sha256': sha((package / 'package_manifest.json').read_bytes()),
              'case': case, 'runtime': subprocess.check_output([binary, '--version'], text=True).strip(),
              'reference_kind': 'ported_reference_backend', 'shared_generator': True}
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
    (out / 'process.json').write_text(json.dumps(record, indent=2) + '\n')
    output = stdout.decode(errors='replace')
    values = re.findall(r'^REFERENCE_RETURNED_TIME (.+)$', output, re.M)
    success = record['returncode'] == 0 and len(values) == 1
    summary = {'status': 'BACKEND_EXECUTED' if success else 'NOT_RUN',
               'reference_kind': 'ported_reference_backend', 'shared_generator': True,
               'original_rerun_s': None, 'ported_reference_s': float(values[0]) if success else None,
               'returned_time_text': values[0] if values else None,
               'termination': 'queue_exhausted' if 'Stopped because no events left to process' in output else None,
               'process': record}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True, type=Path)
    parser.add_argument('--case')
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    summary = replay(args.package, args.out.resolve(), args.case)
    print(json.dumps(summary, indent=2))
    return 0 if summary['status'] == 'BACKEND_EXECUTED' else 1


if __name__ == '__main__':
    raise SystemExit(main())

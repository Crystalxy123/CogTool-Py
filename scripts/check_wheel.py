"""Install candidate wheel and rebuilt sdist in external clean environments.

Only local candidate archives are consumed. No editable install, developer-tree
imports, network installs, or reference backend calls occur in this R1 acceptance.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def extract(archive, directory):
    with tarfile.open(archive) as tar:
        for m in tar.getmembers():
            if not (m.isfile() or m.isdir()) or Path(m.name).is_absolute() or not (directory/m.name).resolve().is_relative_to(directory.resolve()):
                raise ValueError('unsafe distribution archive member: '+m.name)
        tar.extractall(directory, filter='data')


def run_path(kind, args, external):
    cwd=external/(kind+' 安装 with spaces');cwd.mkdir()
    evidence=args.out/kind;evidence.mkdir(parents=True)
    commands=[]
    env={k:v for k,v in os.environ.items() if not k.startswith(('PYTHON','PIP_')) and k!='VIRTUAL_ENV'}
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PIP_CONFIG_FILE=os.devnull,
               PIP_DISABLE_PIP_VERSION_CHECK='1', SOURCE_DATE_EPOCH=str(args.source_date_epoch))
    def cmd(label, command, expected=0, timeout=180):
        start=time.perf_counter()
        try:
            p=subprocess.run([str(x) for x in command],cwd=cwd,env=env,text=True,capture_output=True,timeout=timeout)
            code,stdout,stderr=p.returncode,p.stdout,p.stderr
        except subprocess.TimeoutExpired as exc:
            code=124;stdout=exc.stdout or '';stderr=exc.stderr or ''
            if isinstance(stdout,bytes):stdout=stdout.decode(errors='replace')
            if isinstance(stderr,bytes):stderr=stderr.decode(errors='replace')
        logs=evidence/'logs';logs.mkdir(exist_ok=True)
        (logs/(label+'.stdout.txt')).write_text(stdout);(logs/(label+'.stderr.txt')).write_text(stderr)
        record={'label':label,'command':list(map(str,command)),'cwd':str(cwd),'returncode':code,
                'expected_returncode':expected,'timeout_s':timeout,'wall_clock_runtime_s':time.perf_counter()-start,
                'recorded_at_utc':datetime.now(timezone.utc).isoformat(),
                'environment_policy':'drop inherited PYTHON*, PIP*, VIRTUAL_ENV; disable user site and pip config; no global environment changes',
                'stdout':'logs/'+label+'.stdout.txt','stderr':'logs/'+label+'.stderr.txt'}
        commands.append(record);write(evidence/'commands.json',commands)
        print(kind+'/'+label+': exit '+str(code),flush=True)
        if code!=expected:raise RuntimeError(f'{kind}/{label}: expected {expected}, got {code}; original logs retained')
        return stdout
    dist=cwd/'dist';dist.mkdir()
    shutil.copy2(args.wheel,dist/args.wheel.name);shutil.copy2(args.sdist,dist/args.sdist.name)
    shutil.copytree(args.wheelhouse,cwd/'wheelhouse')
    extract(args.examples,cwd);extract(args.benchmarks,cwd)
    python=cwd/'.venv/bin/python'
    cmd('create_environment',[sys.executable,'-m','venv',cwd/'.venv'])
    if kind=='sdist':
        cmd('install_build_tools',[python,'-I','-m','pip','install','--no-index','--no-deps',
            cwd/'wheelhouse/setuptools-80.9.0-py3-none-any.whl',cwd/'wheelhouse/wheel-0.45.1-py3-none-any.whl'])
        cmd('rebuild_from_sdist',[python,'-I','-m','pip','wheel','--no-index','--no-deps','--no-build-isolation',
            '--no-cache-dir','--wheel-dir',cwd/'rebuilt',dist/args.sdist.name],timeout=180)
        wheels=list((cwd/'rebuilt').glob('cogtool_py-*.whl'));assert len(wheels)==1
        install=wheels[0]
        shutil.copy2(install,evidence/install.name)
    else: install=Path('dist')/args.wheel.name
    cmd('install_candidate',[python,'-m','pip','install','--no-index','--no-deps',install])
    cmd('pip_check',[python,'-I','-m','pip','check'])
    cmd('pip_show_files',[python,'-I','-m','pip','show','-f','cogtool-py'])
    cmd('version',[python,'-I','-m','cogtool_py','--version'])
    cmd('help',[python,'-I','-m','cogtool_py','--help'])
    cmd('console_script_help',[cwd/'.venv/bin/cogtool-py','--help'])
    cmd('info',[python,'-m','cogtool_py','info','--json'])
    cmd('example',[python,'-m','cogtool_py','example','--out','示例 输出'])
    cmd('validate',[python,'-m','cogtool_py','validate','示例 输出/single_click.json'])
    cmd('baseline',[python,'-m','cogtool_py','predict','示例 输出/single_click.json','--out','复跑 输出/baseline'])
    cmd('roundtrip_example',[python,'-m','cogtool_py','roundtrip','示例 输出/single_click.json','--out','复跑 输出/single_click.saved.json'])
    cmd('API',[python,'-I','examples/installed_api.py','示例 输出/single_click.json','复跑 输出/API'])
    api_code='from cogtool_py.io import load_project, export_result\nfrom cogtool_py.runtime import require_configuration\nfrom cogtool_py.engine import predict\nproject=load_project("示例 输出/single_click.json")\nrequire_configuration(project, engine="klm_baseline")\nresult=predict(project)\nexport_result(result,"复跑 输出/API_documented")\n'
    cmd('API_documented',[python,'-I','-c',api_code])
    manifest=Path('LOCAL_ONLY/benchmarks/manifest.json');base=cwd/manifest.parent
    integrated=Path('LOCAL_ONLY/benchmarks/inputs/PR-CF-K.json')
    cmd('integrated',[python,'-m','cogtool_py','predict',integrated,'--engine','cogtool_control_prefix_experimental',
        '--scope','integrated_task','--run-policy','reference_2014','--out','复跑 输出/PR-CF-K'])
    cmd('benchmark',[python,'-m','cogtool_py','benchmark',manifest,'--out','复跑 输出/benchmark'])
    helper=[python,'-I','examples/verify_installation.py']
    common=['--forbidden-root',ROOT]
    cmd('inventory',helper+['inventory',*common,'--out','acceptance/inventory'])
    cmd('override',helper+['override',*common,'--input','示例 输出/single_click.json','--out','acceptance/override'])
    cmd('prepare_negatives',helper+['prepare-negatives',*common,'--input','示例 输出/single_click.json','--out','acceptance/negative'])
    cmd('invalid', [python,'-I','-m','cogtool_py','validate','acceptance/negative/invalid.json'],expected=2)
    cmd('missing_resource',[python,'-I','-m','cogtool_py','validate','no such input.json'],expected=2)
    cmd('wrong_engine',[python,'-I','-m','cogtool_py','predict',integrated,'--engine','klm_baseline','--out','acceptance/wrong_engine'],expected=2)
    cmd('partial',[python,'-I','-m','cogtool_py','predict','acceptance/negative/prefix.json','--out','acceptance/partial'],expected=3)
    cmd('timeout',[python,'-I','-m','cogtool_py','predict','LOCAL_ONLY/benchmarks/diagnostics/PR-CF-K-legacy-10.json',
        '--scope','integrated_task','--run-policy','legacy_bounded','--out','acceptance/timeout'],expected=3)
    partial=read(cwd/'acceptance/partial/result.json');timeout=read(cwd/'acceptance/timeout/result.json')
    assert partial['completion_status']=='partial' and partial['predicted_time_s'] is None
    assert timeout['completion_status']=='time_limit' and timeout['predicted_time_s'] is None
    cmd('guarded_benchmarks',helper+['guarded-benchmark',*common,'--manifest',manifest,'--out','acceptance/guarded'])
    # An incorrect frozen expectation with a correctly resealed file must produce
    # comparison-failure exit 4; never allow a total-time-only success.
    badbase=cwd/'acceptance/mismatch_bundle';shutil.copytree(base,badbase)
    m=read(badbase/'manifest.json');case=m['cases'][0];target=badbase/case['expected']['path'];expected=read(target)
    expected['predicted_time_s']+=1;write(target,expected);case['expected']['sha256']=sha(target);m['cases']=[case]
    write(badbase/'manifest.json',m)
    cmd('comparison_failure',[python,'-I','-m','cogtool_py','benchmark',badbase/'manifest.json','--out','acceptance/mismatch_result'],expected=4)
    official=[case for case in read(base/'manifest.json')['cases'] if case['case_id'] in {'NP-B1','NP-B2','PR-CF-E','PR-CF-M','PR-CF-K'}]
    repeat_checks={}
    if kind=='wheel':
        for i,case in enumerate(official):
            cid=case['case_id'];source=base/case['input']['path'];results=[]
            config=['--engine',case['engine']['name'],'--scope',case['scope'],'--run-policy',case['run_policy']]
            for n in range(1,4):
                out=cwd/'acceptance/repro'/cid/f'repeat_{n}'
                cmd(f'{cid}_repeat_{n}',[python,'-I','-m','cogtool_py','predict',source,*config,'--out',out])
                results.append(read(out/'result.json'))
            norm=lambda d:{k:v for k,v in d.items() if k!='program_runtime_s'}
            assert all(norm(x)==norm(results[0]) for x in results)
            restored=cwd/'acceptance/repro'/cid/'saved.json'
            cmd(cid+'_save',[python,'-I','-m','cogtool_py','roundtrip',source,'--out',restored])
            cmd(cid+'_restored',[python,'-I','-m','cogtool_py','predict',restored,*config,'--out',restored.parent/'roundtrip'])
            assert norm(read(restored.parent/'roundtrip/result.json'))==norm(results[0])
            other=base/official[(i+1)%len(official)]['input']['path']
            cmd(cid+'_ABA',helper+['aba',*common,'--input',source,'--other',other,'--out',restored.parent/'ABA'])
            repeat_checks[cid]={'independent_processes':3,'all_fields_except_wall_time_equal':True,'roundtrip_equal':True,'ABA':'PASS'}
    # Copy actual acceptance output/logs to the permanent report, retaining the
    # external environment for auditable R2 use; no borrowed source file is copied.
    shutil.copytree(cwd/'acceptance',evidence/'acceptance')
    shutil.copytree(cwd/'复跑 输出',evidence/'documented_outputs')
    shutil.copytree(cwd/'示例 输出',evidence/'example')
    installed=read(cwd/'acceptance/inventory/identity.json')
    summary={'status':'PASS','installation_path':kind,'external_directory':str(cwd),'installed_python':str(python),
        'source_tree_used_for_prediction':False,'wheel_sha256':sha(cwd/install) if not install.is_absolute() else sha(install),
        'installed_identity':installed,'benchmark':read(cwd/'复跑 输出/benchmark/summary.json'),
        'reproducibility':repeat_checks,'negative_results':{'invalid':2,'missing_resource':2,'wrong_engine':2,'partial':3,'timeout':3,'comparison_failure':4},
        'offline_install_flags':['--no-index','--no-deps'],'offline_runtime_evidence':'acceptance/guarded/guard.json',
        'physically_disconnected_network':False,'original_rerun_s':None}
    write(evidence/'summary.json',summary)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('wheel','sdist','wheelhouse','examples','benchmarks','out'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--source-date-epoch',type=int,required=True)
    args=p.parse_args()
    for name in ('wheel','sdist','wheelhouse','examples','benchmarks','out'):
        setattr(args,name,getattr(args,name).resolve())
    if args.out.exists():raise FileExistsError('Choose new install evidence directory')
    args.out.mkdir(parents=True)
    external=Path(tempfile.mkdtemp(prefix='cogtool candidate 安装 ',dir='/private/tmp')).resolve()
    write(args.out/'external_directory.json',{'path':str(external),'development_root_forbidden':str(ROOT),
        'candidate_inputs':{k:{'path':str(getattr(args,k)),'sha256':sha(getattr(args,k))} for k in ('wheel','sdist','examples','benchmarks')}})
    results={kind:run_path(kind,args,external) for kind in ('wheel','sdist')}
    write(args.out/'summary.json',{'status':'PASS','paths':{k:{'status':v['status'],'python':v['installed_python'],'cwd':v['external_directory']} for k,v in results.items()}})
    print('Both clean installation paths: PASS')


if __name__=='__main__':main()

"""Executed unified validation: original Java generation, Lisp and frozen Python.

The Java subprocess receives only the original project, original task selector,
explicit source-default preferences and output paths. Python-generated files are
used exclusively by P-P/P-L and subsequent read-only comparisons.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import datetime,hashlib,json,os,subprocess,time
from pathlib import Path
import shutil,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_reference_validation import run_command
from scripts.prepare_python_phone_inputs import prepare
from scripts.run_ported_reference import model_text
from scripts.compare_java_generation import compare as compare_model
from scripts.compare_java_task import compare as compare_task
from scripts.compare_semantic_trace import compare as compare_trace
from cogtool_py.io import implementation_fingerprint, load_project, save_project, input_hash
from scripts.convert_official_task import convert, ConversionError
from scripts.build_synthetic_inputs import construct

CASES={'NP-B1':'Pop-Up::Look up one number','NP-B2':'Pop-Up::Look up two numbers'}
def read(p):return json.loads(Path(p).read_text())
def write(p,d):Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


INSTALLED_API_WORKER = r'''
import importlib, importlib.metadata, json, hashlib, os, site, sys
from pathlib import Path
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
import cogtool_py
from cogtool_py.engine import predict
from cogtool_py.io import load_project, save_project, input_hash, export_result, implementation_fingerprint

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

def snapshot(value):
    if is_dataclass(value):
        return {f.name: snapshot(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {k: snapshot(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [snapshot(v) for v in value]
    return value

def identity():
    for name in ("models", "generator", "engine", "io", "control_prefix", "task_control", "motor_subset", "vision"):
        importlib.import_module("cogtool_py." + name)
    dist = importlib.metadata.distribution("cogtool-py")
    direct = dist.read_text("direct_url.json")
    cfg = Path(sys.prefix) / "pyvenv.cfg"
    return {"executable": sys.executable, "prefix": sys.prefix, "base_prefix": sys.base_prefix,
            "cwd": os.getcwd(), "sys_path": sys.path, "isolated": sys.flags.isolated,
            "no_user_site": sys.flags.no_user_site, "enable_user_site": site.ENABLE_USER_SITE,
            "pythonpath_present": "PYTHONPATH" in os.environ,
            "pyvenv_cfg": cfg.read_text() if cfg.exists() else None,
            "package_file": cogtool_py.__file__,
            "module_files": {k: v.__file__ for k, v in sorted(sys.modules.items())
                             if (k == "cogtool_py" or k.startswith("cogtool_py.")) and getattr(v, "__file__", None)},
            "distribution": {"name": dist.metadata["Name"], "version": dist.version,
                             "root": str(dist.locate_file("")),
                             "files": [str(x) for x in (dist.files or [])],
                             "direct_url": json.loads(direct) if direct else None},
            "implementation": implementation_fingerprint()}

def stable(result):
    return {k: v for k, v in result.items() if k != "program_runtime_s"}

mode, *args = sys.argv[1:]
if mode == "identity":
    record = identity()
    output = Path(args[0])
elif mode == "save":
    original, saved, output = map(Path, args)
    project = load_project(original)
    before = input_hash(project)
    save_project(project, saved)
    record = {"input_hash_before": before, "input_hash_after": input_hash(load_project(saved)),
              "identity": identity()}
    if record["input_hash_before"] != record["input_hash_after"]:
        raise ValueError("Installed API roundtrip changed the effective input")
elif mode == "aba":
    a, b, directory = map(Path, args)
    if directory.exists():
        raise FileExistsError("Refusing to overwrite ABA evidence")
    directory.mkdir(parents=True)
    models = {"A": load_project(a), "B": load_project(b)}
    hashes_before = {k: input_hash(v) for k, v in models.items()}
    effective_before = {k: digest(snapshot(v)) for k, v in models.items()}
    records, results = [], []
    for i, name in enumerate(("A", "B", "A"), 1):
        result = predict(models[name])
        export_result(result, directory / (str(i) + "_" + name))
        results.append(result.to_dict())
        records.append({"position": i, "model": name,
                        "stable_result_sha256": digest(stable(result.to_dict())),
                        "effective_project_hashes_after_prediction": {k: digest(snapshot(v)) for k, v in models.items()}})
    effective_after = {k: digest(snapshot(v)) for k, v in models.items()}
    unchanged = effective_before == effective_after and all(x["effective_project_hashes_after_prediction"] == effective_before for x in records)
    equal = stable(results[0]) == stable(results[2])
    record = {"evidence_kind": "synthetic_software_validation", "process_mode": "same_process_reused_Project_objects",
              "identity": identity(), "sequence": records, "input_hashes_before": hashes_before,
              "input_hashes_after": {k: input_hash(v) for k, v in models.items()},
              "effective_project_hashes_before": effective_before, "effective_project_hashes_after": effective_after,
              "effective_project_snapshot_method": "Canonical recursive actual dataclass fields and Mapping contents, including all parameters/provenance",
              "identical_A_results": equal, "inputs_unmodified": unchanged,
              "excluded_from_result_comparison": ["program_runtime_s"], "status": "PASS" if equal and unchanged else "FAIL"}
    output = directory / "summary.json"
else:
    raise ValueError("Unknown installed API worker mode")
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
if mode == "aba" and record["status"] != "PASS":
    raise SystemExit(1)
'''


def installed_command(destination,label,argv,*,cwd,timeout=180):
    """Run outside the source tree; log only deliberate environment changes."""
    logs=destination/'logs';logs.mkdir(parents=True,exist_ok=True)
    if any((logs/(label+'.'+suffix)).exists() for suffix in ('json','stdout.txt','stderr.txt')):
        raise FileExistsError('Refusing to overwrite installed-process evidence')
    removed=sorted(k for k in os.environ if k.startswith('PYTHON') or k=='VIRTUAL_ENV')
    env={k:v for k,v in os.environ.items() if k not in removed}
    start=time.perf_counter()
    try:
        p=subprocess.run(list(map(str,argv)),cwd=cwd,env=env,text=True,capture_output=True,timeout=timeout)
        code,stdout,stderr=p.returncode,p.stdout,p.stderr
    except subprocess.TimeoutExpired as exc:
        code=124
        stdout=exc.stdout.decode(errors='replace') if isinstance(exc.stdout,bytes) else (exc.stdout or '')
        stderr=exc.stderr.decode(errors='replace') if isinstance(exc.stderr,bytes) else (exc.stderr or '')
        stderr+='\nTIMEOUT after '+str(timeout)+' seconds'
    except OSError as exc:
        code,stdout,stderr=127,'',type(exc).__name__+': '+str(exc)
    record={'command':list(map(str,argv)),'cwd':str(cwd),'returncode':code,'timeout_s':timeout,
            'wall_clock_runtime_s':time.perf_counter()-start,'recorded_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'environment_removed_keys':removed,'environment_overrides':{},'execution_environment':'installed_isolated_python'}
    for stream,value in [('stdout',stdout),('stderr',stderr)]:
        file=logs/(label+'.'+stream+'.txt');file.write_text(value)
        record[stream+'_path']=str(file.relative_to(destination));record[stream+'_sha256']=sha(file)
    write(logs/(label+'.json'),record)
    print(label+': exit '+str(code),flush=True)
    return record


def validate_installed_identity(identity,workdir):
    prefix=Path(identity['prefix']).resolve()
    if identity['isolated']!=1 or identity['no_user_site']!=1 or identity['enable_user_site'] is not False:
        raise ValueError('Installed Python must use isolated mode without user site')
    if prefix==Path(identity['base_prefix']).resolve() or 'include-system-site-packages = false' not in (identity['pyvenv_cfg'] or '').lower():
        raise ValueError('Installed Python must be a venv without system site packages')
    if identity['pythonpath_present'] or Path(identity['cwd']).resolve()!=workdir:
        raise ValueError('Installed execution inherited PYTHONPATH or wrong working directory')
    forbidden=[ROOT.resolve(),(ROOT/'scripts').resolve(),(ROOT/'cogtool_py').resolve()]
    if any(Path(x).resolve() in forbidden for x in identity['sys_path']):
        raise ValueError('Development source directory leaked into installed sys.path')
    for file in identity['module_files'].values():
        path=Path(file).resolve()
        if not path.is_relative_to(prefix) or path.is_relative_to(ROOT/'cogtool_py'):
            raise ValueError('Prediction module was not loaded from the installed environment: '+str(path))
    direct=identity['distribution']['direct_url'] or {}
    if direct.get('dir_info',{}).get('editable'):
        raise ValueError('Editable installations cannot establish installed-wheel validation')


def run(build,backend_package,source_model,policy_input,plan,out,suite_manifest=None,*,installed_python=None,installed_workdir=None):
    if (installed_python is None)!=(installed_workdir is None):
        raise ValueError('installed_python and installed_workdir must be supplied together')
    installed=installed_python is not None
    if installed:
        installed_python=Path(installed_python).absolute() # preserve venv executable symlink
        installed_workdir=Path(installed_workdir).resolve()
        if not installed_python.is_file() or not installed_workdir.is_dir() or installed_workdir.is_relative_to(ROOT):
            raise ValueError('Installed Python must exist and its working directory must exist outside the source workspace')
        out=out.resolve()
    if out.exists():raise FileExistsError('Choose a fresh validation output directory')
    before=implementation_fingerprint();backend_manifest=sha(backend_package/'package_manifest.json');source_hash=sha(source_model)
    out.mkdir(parents=True)
    commands=[]
    def cmd(label,args,timeout=180,*,product=False):
        record=(installed_command(out,label,[installed_python,'-I','-B',*map(str,args)],cwd=installed_workdir,timeout=timeout)
                if product and installed else run_command(out,label,[sys.executable,*map(str,args)],timeout=timeout))
        commands.append(record)
        write(out/'commands.json',commands)
        if record['returncode']!=0:raise RuntimeError(label+' failed; original output is retained')
    def api(label,mode,*paths):
        cmd(label,['-c',INSTALLED_API_WORKER,mode,*[Path(p).resolve() for p in paths]],30,product=True)
    installed_before=None
    if installed:
        (out/'installed_software').mkdir()
        (out/'installed_software/api_worker.py').write_text(INSTALLED_API_WORKER)
        api('installed_identity_before','identity',out/'installed_software/before.json')
        installed_before=read(out/'installed_software/before.json')
        validate_installed_identity(installed_before,installed_workdir)
    def predict_cmd(label,path,directory):
        cmd(label,['-m','cogtool_py','predict',Path(path).resolve(),'--out',Path(directory).resolve()],30,product=True)
        if installed and read(directory/'result.json').get('implementation')!=installed_before['implementation']:
            raise RuntimeError('P-P result implementation differs from the installed package identity')
    def save_cmd(label,path,saved):
        if installed:
            evidence=saved.with_suffix('.installed_save.json');api(label,'save',path,saved,evidence)
            record=read(evidence);validate_installed_identity(record['identity'],installed_workdir)
            if record['identity']['implementation']!=installed_before['implementation']:
                raise RuntimeError('Installed serialization implementation changed')
            return record['input_hash_before']==record['input_hash_after']
        save_project(load_project(path),saved)
        return input_hash(load_project(saved))==input_hash(load_project(path))
    def aba_cmd(label,a,b,directory):
        if installed:
            # Data is copied for auditability; no script/import from examples is executed.
            data=out/'installed_api_inputs';data.mkdir(exist_ok=True)
            copied=data/(sha(b)+'.json')
            if not copied.exists():shutil.copyfile(b,copied)
            api(label,'aba',a,copied,directory)
            record=read(directory/'summary.json');validate_installed_identity(record['identity'],installed_workdir)
            if record['identity']['implementation']!=installed_before['implementation']:
                raise RuntimeError('Installed ABA implementation changed')
        else:cmd(label,['scripts/reference_validation_worker.py','--a',a,'--b',b,'--out',directory],30)
        return read(directory/'summary.json')['status']
    configs = (read(suite_manifest)['cases'] if suite_manifest else [
        {'case_id':case,'origin':'official','adapter':'phone','source_model':str(source_model),
         'selector':selector,'repetitions':3,'development_role':'regression'} for case,selector in CASES.items()])
    ids=[c['case_id'] for c in configs]
    if len(ids)!=len(set(ids)) or any(not c or '/' in c or '..' in c for c in ids):
        raise ValueError('Unique simple case identifiers required')
    write(out/'suite_manifest.json',{'cases':configs,'source_manifest':str(suite_manifest) if suite_manifest else None})
    inputs={};conversion_status={};source_identities={}
    if any(c['adapter']=='phone' for c in configs):
        prepare(source_model,policy_input,out/'phone_conversion')
    for config in configs:
        case=config['case_id'];folder=out/'python_conversion'/case
        case_policy=Path(config.get('policy_input',policy_input)).resolve()
        source_identities[str(case_policy)]=sha(case_policy)
        original=Path(config.get('source_model',source_model)).resolve()
        if config['adapter']=='phone':
            shutil.copytree(out/'phone_conversion'/case,folder)
        elif config['adapter']=='ordinary_official':
            design,task=config['selector'].split('::',1)
            try:
                convert(original,design,task,case,case_policy,folder)
            except ConversionError as exc:
                conversion_status[case]={'status':'unsupported_conversion','reason':str(exc)}
        elif config['adapter']=='synthetic':
            spec=Path(config['spec']).resolve();original=spec
            data,record=construct(spec,read(case_policy));folder.mkdir(parents=True)
            write(folder/'input.json',data);write(folder/'conversion.json',record)
        else:raise ValueError('Unknown conversion adapter '+config['adapter'])
        source_identities[str(original)]=sha(original)
        if (folder/'input.json').exists():
            inputs[case]=folder/'input.json'
            project=load_project(inputs[case])
            conversion_status[case]={'status':'converted','input_content_sha256':input_hash(project),
                'parameter_sha256':hashlib.sha256(json.dumps(project.parameters.input_dict(),sort_keys=True,separators=(',',':')).encode()).hexdigest()}
    write(out/'conversion_status.json',conversion_status)
    # Reuse the frozen computational source and loader bytes once for the P-L
    # package; only the shared Python model content is freshly regenerated.
    package=out/'python_lisp_package';package.mkdir()
    old_manifest=read(backend_package/'package_manifest.json')
    for rel,expected in old_manifest['files'].items():
        if sha(backend_package/rel)!=expected:raise ValueError('Frozen backend artifact changed: '+rel)
    shutil.copytree(backend_package/'source',package/'source')
    for filename in ('LICENSE.txt','copyright.txt','loader_compatibility.patch'):
        shutil.copy2(backend_package/filename,package/filename)
    model_cases={}
    for case in inputs:
        directory=package/'models'/case;directory.mkdir(parents=True)
        model,mapping=model_text(inputs[case])
        (directory/'model.lisp').write_text(model);write(directory/'input_mapping.json',mapping)
        shutil.copy2(inputs[case],directory/'input.json')
        model_cases[case]={'model':str((directory/'model.lisp').relative_to(package))}
    files={str(p.relative_to(package)):sha(p) for p in sorted(package.rglob('*')) if p.is_file()}
    write(package/'package_manifest.json',{'package_version':1,'source_commit':before['upstream_commit'],'source_directory':'source','cases':model_cases,'files':files,'shared_generator':True,'reference_kind':'ported_reference_backend','frozen_source_package_manifest_sha256':backend_manifest})
    summaries={}
    for config in configs:
        case=config['case_id'];selector=config.get('selector')
        repetitions=config.get('repetitions',3)
        if not isinstance(repetitions,int) or not 1<=repetitions<=3:raise ValueError('repetitions must be 1..3')
        gen=out/'java_generation'/case
        java_input=(['generate-synthetic','--spec',config['spec']] if config['adapter']=='synthetic'
                    else ['generate','--original',config.get('source_model',source_model),'--selector',selector])
        cmd('java_'+case,['scripts/run_java_generation.py',*java_input,'--build',build,
             '--case-id',case,'--preference-policy','source_defaults','--out',gen,'--repetitions',str(config.get('java_repetitions',2))])
        first=gen/'generation_1';pp_results=[];jl_results=[]
        for i in range(1,repetitions+1):
            if case in inputs:
                pp=out/'P-P'/case/f'repeat_{i}'
                predict_cmd(f'PP_{case}_{i}',inputs[case],pp)
                pp_results.append(read(pp/'result.json'))
                if installed and pp_results[-1]['input_sha256']!=conversion_status[case]['input_content_sha256']:
                    raise RuntimeError('Installed input identity differs from the reference-tool conversion')
            jl=out/'J-L'/case/f'repeat_{i}'
            cmd(f'JL_{case}_{i}',['scripts/replay_java_reference.py','--model',first/'model.lisp','--generation-record',first/'generation_record.json','--backend-package',backend_package,'--case-id',case,'--out',jl],timeout=120)
            jl_results.append(read(jl/'summary.json'))
        if case not in inputs:
            summaries[case]={'execution_status':'unsupported_conversion','conversion':conversion_status[case],
                'case_origin':config['origin'],'development_role':config['development_role'],
                'java_generations':read(gen/'summary.json'),'JL_predictions_s':[v['prediction_s'] for v in jl_results],
                'PP_predictions_s':[],'PL_prediction_s':None,'comparison_status':'not_comparable','original_rerun_s':None}
            write(out/'partial_summary.json',summaries)
            continue
        pl=out/'P-L'/case
        cmd('PL_'+case,['scripts/replay_ported_reference.py','--package',package,'--case',case,'--out',pl],timeout=120)
        comparison=out/'comparison'/case;comparison.mkdir(parents=True)
        structure=compare_model(first/'model.lisp',package/'models'/case/'model.lisp',comparison/'ordered_lisp_structure')
        task=compare_task(first,inputs[case],out/'P-P'/case/'repeat_1/result.json',comparison/'input_and_steps')
        traced=compare_trace(inputs[case],out/'P-P'/case/'repeat_1/result.json',out/'J-L'/case/'repeat_1/stdout.txt',plan,comparison/'JL_PP_trace','ported_reference_backend')
        trace_pl=compare_trace(inputs[case],out/'P-P'/case/'repeat_1/result.json',pl/'stdout.txt',plan,comparison/'PL_PP_trace','ported_reference_backend')
        normalized=[]
        for result in pp_results:
            value=deepcopy(result);value.pop('program_runtime_s',None);normalized.append(value)
        summaries[case]={'case_origin':config['origin'],'development_role':config['development_role'],'execution_status':pp_results[0].get('completion_status'),'input_identity':conversion_status[case],'java_generations':read(gen/'summary.json'),'PP_predictions_s':[v['predicted_time_s'] for v in pp_results],'PP_all_deterministic_fields_equal':all(v==normalized[0] for v in normalized),'PL_prediction_s':read(pl/'summary.json')['ported_reference_s'],'JL_predictions_s':[v['prediction_s'] for v in jl_results],'fresh_actions':task['fresh_action_sequence_status'],'bounded_task_comparison_status':task['bounded_task_comparison_status'],'transition_commit_contract_status':task['transition_commit_contract_status'],'production_structure':structure['layers']['productions']['status'],'SPP_structure':structure['layers']['spp']['status'],'ordered_model_forms':structure['layers']['ordered_model_forms'],'model_options':structure['layers']['model_options'],'JL_PP_observed_event_status':traced['observed_paired_events_status'],'JL_PP_matched_event_count':traced['mapped_time_matches'],'JL_PP_total_status':traced['raw_total_comparison_status'],'PL_PP_observed_event_status':trace_pl['observed_paired_events_status'],'PL_PP_total_status':trace_pl['raw_total_comparison_status'],'JL_PP_required_mechanisms_status':traced.get('required_mechanisms_status','not_observed'),'PL_PP_required_mechanisms_status':trace_pl.get('required_mechanisms_status','not_observed'),'complete_export_equivalence':None,'full_resource_state_equivalence':None,'original_rerun_s':None}
        # Check serialization and A->B->A using the same real API and separate
        # CLI, not an expected total. All deterministic fields must survive.
        restored=out/'roundtrip'/case;restored.mkdir(parents=True)
        content_equal=save_cmd('roundtrip_save_'+case,inputs[case],restored/'input.json')
        predict_cmd('roundtrip_'+case,restored/'input.json',restored/'prediction')
        saved=read(restored/'prediction/result.json');saved.pop('program_runtime_s',None)
        summaries[case]['roundtrip']={'result_equal':saved==normalized[0],
            'content_hash_equal':content_equal}
        other=(next((v for k,v in inputs.items() if k!=case),ROOT/'examples/single_click.json')
               if installed else ROOT/'examples/single_click.json')
        summaries[case]['ABA_status']=aba_cmd('ABA_'+case,inputs[case],other,out/'ABA'/case)
        write(out/'partial_summary.json',summaries)
    locals_summary={}
    for entry in (read(suite_manifest).get('local_examples',[]) if suite_manifest else []):
        path=Path(entry['input']).resolve();case=path.stem;results=[]
        for i in range(1,4):
            folder=out/'local_regression'/case/f'repeat_{i}'
            predict_cmd(f'local_{case}_{i}',path,folder)
            value=read(folder/'result.json');value.pop('program_runtime_s',None);results.append(value)
        saved=out/'local_regression'/case/'saved.json';save_cmd('local_save_'+case,path,saved)
        roundtrip=out/'local_regression'/case/'roundtrip'
        predict_cmd('local_roundtrip_'+case,saved,roundtrip)
        restored=read(roundtrip/'result.json');restored.pop('program_runtime_s',None)
        aba=out/'local_regression'/case/'ABA'
        other=ROOT/'examples'/('text_entry.json' if case=='single_click' else 'single_click.json')
        aba_status=aba_cmd('local_ABA_'+case,path,other,aba)
        before_result=read(entry['before_result'])
        fields=['predicted_time_s','input_sha256','parameters','steps','trace','demonstration']
        comparison={k:results[0].get(k)==before_result.get(k) for k in fields if k in results[0] or k in before_result}
        locals_summary[case]={'predictions_s':[x['predicted_time_s'] for x in results],
            'before_result':entry['before_result'],'before_prediction_s':before_result['predicted_time_s'],
            'before_after_fields_equal':comparison,'repetitions_equal':all(x==results[0] for x in results),
            'roundtrip_equal':restored==results[0],'ABA_status':aba_status}
    write(out/'local_regression_summary.json',locals_summary)
    installed_after=None
    if installed:
        api('installed_identity_after','identity',out/'installed_software/after.json')
        installed_after=read(out/'installed_software/after.json');validate_installed_identity(installed_after,installed_workdir)
        if installed_before!=installed_after:
            raise RuntimeError('Installed package/environment identity changed during validation')
    reference_unchanged=before==implementation_fingerprint()
    summary={'local_regressions':locals_summary,'run_status':'EXECUTED_COMPARISONS_SAVED','cases':summaries,'implementation':installed_before['implementation'] if installed else before,'implementation_unchanged':installed_before==installed_after if installed else reference_unchanged,'reference_tool_implementation':before,'reference_tool_implementation_unchanged':reference_unchanged,'PP_execution_mode':'installed_isolated_python' if installed else 'development_source','installed_software_identity':{'before':installed_before,'after':installed_after} if installed else None,'original_source_unchanged':sha(source_model)==source_hash,'frozen_backend_manifest_unchanged':sha(backend_package/'package_manifest.json')==backend_manifest,'source_model_sha256':source_hash,'all_source_files_unchanged':all(sha(p)==v for p,v in source_identities.items()),'source_identities':source_identities,'backend_manifest_sha256':backend_manifest,'numeric_plan_sha256':sha(plan),'unified_launcher_sha256':sha(__file__),'java_generation_count_per_case':2,'PP_and_JL_independent_process_count_per_case':{c['case_id']:c.get('repetitions',3) for c in configs},'no_total_time_target':True,'no_accuracy_or_full_original_program_claim':True}
    write(out/'summary.json',summary)
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','backend-package','source-model','policy-input','plan'):p.add_argument('--'+name,type=Path)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--suite-manifest',type=Path,help='Explicit ordered tasks: original selector or shared synthetic specification')
    p.add_argument('--installed-python',type=Path,help='Non-editable installed-wheel venv executable for P-P and public API checks')
    p.add_argument('--installed-workdir',type=Path,help='Existing working directory outside the source workspace for installed P-P')
    p.add_argument('--config',type=Path,help='Saved path configuration for the same unified runner; CLI paths override it')
    a=p.parse_args();config=read(a.config) if a.config else {}
    names=('build','backend_package','source_model','policy_input','plan','suite_manifest','installed_python','installed_workdir')
    if not isinstance(config,dict) or set(config)-set(names):p.error('configuration must contain only documented path fields')
    for name in names:
        if getattr(a,name) is None and name in config:
            if not isinstance(config[name],str):p.error('configuration paths must be strings')
            setattr(a,name,Path(config[name]))
        if getattr(a,name) is None and name not in ('suite_manifest','installed_python','installed_workdir'):p.error('missing path '+name)
    if (a.installed_python is None)!=(a.installed_workdir is None):p.error('installed-python and installed-workdir are required together')
    print(json.dumps(run(*[getattr(a,x).resolve() for x in ('build','backend_package','source_model','policy_input','plan','out')],suite_manifest=a.suite_manifest.resolve() if a.suite_manifest else None,installed_python=a.installed_python.absolute() if a.installed_python else None,installed_workdir=a.installed_workdir.resolve() if a.installed_workdir else None),ensure_ascii=False,indent=2))
if __name__=='__main__':main()

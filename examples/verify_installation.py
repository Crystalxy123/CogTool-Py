"""Local acceptance helper using only the installed package and supplied inputs.

No sys.path changes, development scripts, external runtime, or reference execution.
This checks software installation, not behavioral prediction accuracy.
"""
from __future__ import annotations
import argparse
from dataclasses import replace
import hashlib
import importlib
import importlib.abc
import importlib.metadata
import json
from pathlib import Path
import platform
import site
import sys

from cogtool_py.engine import predict
from cogtool_py.io import export_result, input_hash, load_project, save_project, write_json
from cogtool_py.models import CONTROL_ENGINE, DemonstrationStep


def read(path):
    return json.loads(Path(path).read_text())


def normalized(result):
    # In a single installed version even distribution identity must be identical.
    return json.loads(json.dumps({k:v for k,v in result.items() if k != 'program_runtime_s'}))


def inventory(forbidden_root):
    import cogtool_py
    from cogtool_py.io import implementation_fingerprint
    package = Path(cogtool_py.__file__).resolve().parent
    dist = importlib.metadata.distribution('cogtool-py')
    modules = {}
    for path in sorted(package.glob('*.py')):
        if path.name == '__main__.py':
            continue
        name = 'cogtool_py' if path.stem == '__init__' else 'cogtool_py.'+path.stem
        module = importlib.import_module(name)
        modules[name] = str(Path(module.__file__).resolve())
    assert package.is_relative_to(Path(sys.prefix).resolve())
    assert all(not Path(path).resolve().is_relative_to(forbidden_root) for path in sys.path if path)
    assert all(not Path(path).is_relative_to(forbidden_root) for path in modules.values())
    assert site.ENABLE_USER_SITE is False
    cfg = (Path(sys.prefix)/'pyvenv.cfg').read_text()
    assert 'include-system-site-packages = false' in cfg
    pth = {str(p):p.read_text() for p in (Path(sys.prefix)/'lib').rglob('*.pth')}
    assert all(str(forbidden_root) not in text for text in pth.values())
    return {'python_executable':sys.executable, 'python_version':sys.version, 'platform':platform.platform(),
        'prefix':sys.prefix, 'base_prefix':sys.base_prefix, 'isolated':sys.flags.isolated,
        'user_site_enabled':site.ENABLE_USER_SITE, 'sys_path':sys.path,
        'loaded_modules':modules, 'metadata':dict(dist.metadata.items()),
        'installed_files':[{'path':str(p),'located':str(dist.locate_file(p)),
            'hash':str(p.hash) if p.hash else None,'size':p.size} for p in dist.files or []],
        'installed_packages':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()},
        'pyvenv_cfg':cfg,'pth_files':pth,'implementation':implementation_fingerprint(),
        'development_directory_loaded':False}


def guard(forbidden_root, attempts):
    class NoReferenceImports(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path, target=None):
            if fullname.split('.')[0] in {'scripts','jpype','jnius','tkinter'}:
                attempts.append({'kind':'forbidden_import','name':fullname})
                raise RuntimeError('Reference/GUI import during product calculation: '+fullname)
    sys.meta_path.insert(0, NoReferenceImports())
    def audit(event,args):
        if event.startswith('socket.') or event in {'subprocess.Popen','os.system','os.posix_spawn','os.exec'}:
            attempts.append({'kind':event})
            raise RuntimeError('Network/process operation forbidden during prediction: '+event)
        if event == 'open' and isinstance(args[0],(str,bytes)):
            path=Path(args[0].decode() if isinstance(args[0],bytes) else args[0]).resolve()
            if path.is_relative_to(forbidden_root):
                attempts.append({'kind':'development_tree_read','path':str(path)})
                raise RuntimeError('Read from original development tree during installed calculation')
    sys.addaudithook(audit)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['inventory','guarded-benchmark','prepare-negatives','override','aba'])
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--forbidden-root',type=Path,required=True)
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--input',type=Path)
    parser.add_argument('--other',type=Path)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    if args.mode=='inventory':
        write_json(args.out/'identity.json',inventory(args.forbidden_root.resolve()))
    elif args.mode=='guarded-benchmark':
        from cogtool_py.benchmark import run_benchmarks
        before=inventory(args.forbidden_root.resolve());attempts=[]
        guard(args.forbidden_root.resolve(),attempts)
        result=run_benchmarks(args.manifest,args.out/'actual_predictions')
        write_json(args.out/'guard.json',{'guard_type':'Python audit/import hooks, not physical network disconnection',
            'forbidden_operations':['network sockets','child processes','reference/GUI imports','development tree reads'],
            'attempts':attempts,'executed_benchmarks_status':result['status'],'inventory':before})
        if not result['passed']:raise SystemExit(4)
    elif args.mode=='override':
        original=load_project(args.input)
        modified=replace(original,parameters=original.parameters.override('think_s',2.4,source='Synthetic installation override check'))
        save_project(modified,args.out/'saved.json');restored=load_project(args.out/'saved.json')
        a=predict(modified).to_dict();b=predict(restored).to_dict()
        assert normalized(a)==normalized(b)
        assert input_hash(original)!=input_hash(restored)
        assert original.parameters.value('think_s')!=modified.parameters.value('think_s')
        export_result(a,args.out/'direct');export_result(b,args.out/'restored')
        write_json(args.out/'summary.json',{'status':'PASS','original_input_hash':input_hash(original),
            'override_input_hash':input_hash(restored),'all_result_fields_except_wall_time_equal':True})
    elif args.mode=='prepare-negatives':
        from cogtool_py.control_models import ControlConfig
        project=load_project(args.input);bad=project.to_dict()
        bad['tasks'][0]['demonstration']['steps'][0]['op']='unknown_operation'
        write_json(args.out/'invalid.json',bad)
        task=project.tasks[0]
        task=replace(task,demonstration=replace(task.demonstration,
            steps=(DemonstrationStep('point',target=project.design.frames[0].widgets[0].id),)))
        prefix=replace(project,engine=CONTROL_ENGINE,parameters=project.parameters.with_control_defaults(),
            control=ControlConfig.source_2014(provenance='Explicit synthetic prefix-only installation negative'),tasks=(task,))
        save_project(prefix,args.out/'prefix.json')
    elif args.mode=='aba':
        # One interpreter, fresh invocation of the public API, no fixture helpers.
        for label,path in [('1_A',args.input),('2_B',args.other),('3_A',args.input)]:
            export_result(predict(load_project(path)),args.out/label)
        a=read(args.out/'1_A/result.json');b=read(args.out/'3_A/result.json')
        assert normalized(a)==normalized(b)
        write_json(args.out/'summary.json',{'status':'PASS','all_fields_except_wall_time_equal':True})
    print(args.mode+': PASS')


if __name__=='__main__':
    main()

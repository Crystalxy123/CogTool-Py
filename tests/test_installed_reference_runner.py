"""Harness routing tests; mocked reference runs are not cognitive evidence."""
import ast
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import validate_java_phone_chain as runner


def identity(tmp_path):
    prefix = tmp_path / "installed venv"
    work = tmp_path / "外部工作"
    return {"prefix": str(prefix), "base_prefix": "/base-python", "cwd": str(work),
            "isolated": 1, "no_user_site": 1, "enable_user_site": False,
            "pyvenv_cfg": "include-system-site-packages = false\n",
            "pythonpath_present": False, "sys_path": [str(prefix / "site-packages")],
            "module_files": {"cogtool_py.engine": str(prefix / "site-packages/cogtool_py/engine.py")},
            "distribution": {"direct_url": {"url": "file:///candidate.whl"}},
            "implementation": {"sha256": "installed-package"}}


def test_isolated_process_records_cwd_and_removes_python_environment(tmp_path, monkeypatch):
    work = tmp_path / "中文 空格"
    work.mkdir()
    monkeypatch.setenv("PYTHONPATH", str(runner.ROOT))
    monkeypatch.setenv("PYTHONSTARTUP", "/must-not-run")
    code = "import os,sys,json; print(json.dumps(dict(cwd=os.getcwd(),isolated=sys.flags.isolated,pythonpath='PYTHONPATH' in os.environ,path=sys.path)))"
    record = runner.installed_command(tmp_path / "out", "isolation", [sys.executable, "-I", "-B", "-c", code], cwd=work, timeout=5)
    assert record["returncode"] == 0
    output = json.loads((tmp_path / "out" / record["stdout_path"]).read_text())
    assert output["cwd"] == str(work) and output["isolated"] == 1
    assert output["pythonpath"] is False and str(runner.ROOT) not in output["path"]
    assert "PYTHONPATH" in record["environment_removed_keys"]
    assert "PYTHONSTARTUP" in record["environment_removed_keys"]


def test_timeout_and_prior_evidence_are_not_success(tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 2, output=b"partial", stderr=b"problem")
    monkeypatch.setattr(runner.subprocess, "run", timeout)
    record = runner.installed_command(tmp_path, "timeout", ["python", "-I"], cwd=tmp_path, timeout=2)
    assert record["returncode"] == 124
    assert (tmp_path / record["stdout_path"]).read_text() == "partial"
    assert "TIMEOUT" in (tmp_path / record["stderr_path"]).read_text()
    with pytest.raises(FileExistsError):
        runner.installed_command(tmp_path, "timeout", ["python"], cwd=tmp_path)


@pytest.mark.parametrize("corruption", ["source_module", "source_path", "editable", "system_site", "user_site", "not_isolated", "pythonpath", "wrong_cwd"])
def test_source_leaks_and_unisolated_installations_are_rejected(tmp_path, corruption):
    data = identity(tmp_path)
    work = Path(data["cwd"])
    runner.validate_installed_identity(data, work)
    if corruption == "source_module":
        data["module_files"]["cogtool_py.engine"] = str(runner.ROOT / "cogtool_py/engine.py")
    elif corruption == "source_path":
        data["sys_path"].append(str(runner.ROOT))
    elif corruption == "editable":
        data["distribution"]["direct_url"] = {"dir_info": {"editable": True}}
    elif corruption == "system_site":
        data["pyvenv_cfg"] = "include-system-site-packages = true"
    elif corruption == "user_site":
        data["enable_user_site"] = True
    elif corruption == "not_isolated":
        data["isolated"] = 0
    elif corruption == "pythonpath":
        data["pythonpath_present"] = True
    else:
        data["cwd"] = str(tmp_path / "wrong")
    with pytest.raises(ValueError):
        runner.validate_installed_identity(data, work)


def test_worker_compiles_without_development_import_or_path_mutation():
    tree = ast.parse(runner.INSTALLED_API_WORKER)
    compile(tree, "installed-api-worker", "exec")
    assert "scripts." not in runner.INSTALLED_API_WORKER
    assert "sys.path.insert" not in runner.INSTALLED_API_WORKER
    assert "sys.path.append" not in runner.INSTALLED_API_WORKER
    assert "from cogtool_py.engine import predict" in runner.INSTALLED_API_WORKER
    assert 'if k != "program_runtime_s"' in runner.INSTALLED_API_WORKER
    assert "effective_project_hashes_after_prediction" in runner.INSTALLED_API_WORKER


def test_optional_installed_paths_are_paired_and_cwd_is_external(tmp_path):
    args = [tmp_path] * 5 + [tmp_path / "out"]
    with pytest.raises(ValueError, match="together"):
        runner.run(*args, installed_python=Path(sys.executable))
    with pytest.raises(ValueError, match="outside"):
        runner.run(*args, installed_python=Path(sys.executable), installed_workdir=runner.ROOT)
    assert not (tmp_path / "out").exists()


def test_config_accepts_installed_paths_and_cli_override(tmp_path, monkeypatch, capsys):
    config = {key: str(tmp_path / key) for key in ("build", "backend_package", "source_model", "policy_input", "plan", "installed_python", "installed_workdir")}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    captured = {}
    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return {"test_only": True}
    monkeypatch.setattr(runner, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["runner", "--config", str(path), "--out", str(tmp_path / "out"), "--installed-workdir", str(tmp_path / "override")])
    runner.main()
    assert captured["installed_python"] == Path(config["installed_python"]).absolute()
    assert captured["installed_workdir"] == (tmp_path / "override").resolve()
    assert json.loads(capsys.readouterr().out) == {"test_only": True}


@pytest.mark.parametrize("wrong_product_identity", [False, True])
def test_installed_routing_separates_reference_identity_and_public_api(tmp_path, monkeypatch, wrong_product_identity):
    """Mock orchestration only: this does not claim a wheel/reference execution."""
    software = identity(tmp_path)
    work = Path(software["cwd"])
    work.mkdir()
    exe = tmp_path / "installed venv/bin/python"
    exe.parent.mkdir(parents=True)
    exe.touch()
    backend = tmp_path / "backend"
    (backend / "source").mkdir(parents=True)
    for name in ("LICENSE.txt", "copyright.txt", "loader_compatibility.patch"):
        (backend / name).write_text("mock fixture")
    runner.write(backend / "package_manifest.json", {"files": {}})
    model = tmp_path / "original.cgt"
    model.write_bytes(b"original mock fixture")
    policy = tmp_path / "policy.json"
    policy.write_text("{}")
    plan = tmp_path / "plan.json"
    plan.write_text("{}")
    manifest = tmp_path / "suite.json"
    runner.write(manifest, {"cases": [{"case_id": "C", "origin": "official", "adapter": "ordinary_official", "selector": "Design::Task", "repetitions": 2, "development_role": "regression"}]})
    fixture = json.loads((runner.ROOT / "examples/single_click.json").read_text())
    reference_identity = {"sha256": "reference-source", "upstream_commit": "fixed-source"}
    monkeypatch.setattr(runner, "implementation_fingerprint", lambda: reference_identity)
    def convert(original, design, task, case, case_policy, folder):
        folder.mkdir(parents=True)
        runner.write(folder / "input.json", fixture)
    monkeypatch.setattr(runner, "convert", convert)
    monkeypatch.setattr(runner, "model_text", lambda path: ("mock Lisp", {}))
    monkeypatch.setattr(runner, "compare_model", lambda *args: {"layers": {k: {"status": "test_only"} for k in ("productions", "spp", "ordered_model_forms", "model_options")}})
    monkeypatch.setattr(runner, "compare_task", lambda *args: {k: "test_only" for k in ("fresh_action_sequence_status", "bounded_task_comparison_status", "transition_commit_contract_status")})
    monkeypatch.setattr(runner, "compare_trace", lambda *args: {"observed_paired_events_status": "test_only", "mapped_time_matches": 0, "raw_total_comparison_status": "test_only"})
    def forbidden_save(*args):
        raise AssertionError("Roundtrip must not use reference-source save_project")
    monkeypatch.setattr(runner, "save_project", forbidden_save)
    calls = []
    def reference_command(out, label, command, **kwargs):
        calls.append(("reference", label, command))
        if label.startswith("java_"):
            g = Path(command[command.index("--out") + 1]);(g / "generation_1").mkdir(parents=True)
            (g / "generation_1/model.lisp").write_text("mock Lisp")
            runner.write(g / "summary.json", {"status": "mock_only"})
        elif label.startswith(("JL_", "PL_")):
            d = Path(command[command.index("--out") + 1]);d.mkdir(parents=True)
            runner.write(d / "summary.json", {"prediction_s": 1, "ported_reference_s": 1})
        else:
            raise AssertionError("Product execution leaked to reference environment: " + label)
        return {"returncode": 0}
    def installed_command(out, label, command, *, cwd, **kwargs):
        calls.append(("installed", label, command))
        assert command[:3] == [exe, "-I", "-B"] and cwd == work
        if "-m" in command:
            path = Path(command[command.index("predict") + 1]);d = Path(command[command.index("--out") + 1]);d.mkdir(parents=True)
            runner.write(d / "result.json", {"predicted_time_s": 1, "completion_status": "complete", "input_sha256": runner.input_hash(runner.load_project(path)), "implementation": reference_identity if wrong_product_identity else software["implementation"]})
        else:
            mode = command[5];args = list(map(Path, command[6:]))
            if mode == "identity":
                runner.write(args[0], software)
            elif mode == "save":
                original, saved, evidence = args
                saved.write_bytes(original.read_bytes())
                runner.write(evidence, {"identity": software, "input_hash_before": "same", "input_hash_after": "same"})
            elif mode == "aba":
                args[-1].mkdir(parents=True)
                runner.write(args[-1] / "summary.json", {"status": "PASS", "identity": software})
            else:
                raise AssertionError(mode)
        return {"returncode": 0}
    monkeypatch.setattr(runner, "run_command", reference_command)
    monkeypatch.setattr(runner, "installed_command", installed_command)
    if wrong_product_identity:
        with pytest.raises(RuntimeError, match="P-P result implementation"):
            runner.run(tmp_path / "build", backend, model, policy, plan, tmp_path / "out", manifest, installed_python=exe, installed_workdir=work)
        return
    result = runner.run(tmp_path / "build", backend, model, policy, plan, tmp_path / "out", manifest, installed_python=exe, installed_workdir=work)
    assert result["implementation"] == software["implementation"]
    assert result["reference_tool_implementation"] == reference_identity
    assert result["implementation_unchanged"] and result["reference_tool_implementation_unchanged"]
    assert result["cases"]["C"]["roundtrip"] == {"result_equal": True, "content_hash_equal": True}
    product_labels = {label for kind, label, command in calls if kind == "installed"}
    assert {"PP_C_1", "PP_C_2", "roundtrip_save_C", "roundtrip_C", "ABA_C", "installed_identity_before", "installed_identity_after"} == product_labels
    assert all("reference_validation_worker.py" not in str(command) for _, _, command in calls)

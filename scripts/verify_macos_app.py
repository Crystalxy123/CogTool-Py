#!/usr/bin/env python3
"""Check a moved .app without Python or project paths in its runtime environment."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cogtool_py.control_models import ControlConfig
from cogtool_py.engine import predict
from cogtool_py.io import load_project, save_project
from cogtool_py.models import CONTROL_ENGINE, DemonstrationStep


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    checks = []
    with tempfile.TemporaryDirectory(prefix="CogTool 独立运行 ") as temp:
        work = Path(temp)
        app = work / "软件 空格" / args.app.name
        shutil.copytree(args.app.resolve(), app, symlinks=True)
        engine = app / "Contents/Resources/engine/cogtool-engine"
        env = {key: value for key, value in os.environ.items()
               if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}}
        env["PATH"] = "/usr/bin:/bin"

        def invoke(*argv, status=0):
            run = subprocess.run([str(engine), *map(str, argv)], cwd=work,
                                 env=env, text=True, capture_output=True, timeout=60)
            assert run.returncode == status, (argv, run.returncode, run.stdout, run.stderr)
            return json.loads(run.stdout)

        def compare(source, task, label, status=0):
            project = load_project(source)
            expected = json.loads(json.dumps(predict(project, task).data))
            output = work / "计算 结果" / label
            payload = invoke("predict", source, "--task", task, "--out", output, status=status)
            actual = payload["result"]
            actual.pop("program_runtime_s")
            expected.pop("program_runtime_s")
            assert actual == expected, label
            assert actual["implementation"]["files"], "Frozen source identity is missing"
            assert (output / "input.json").is_file()
            checks.append({"case": label, "status": "passed", "exit_code": status,
                           "predicted_time_s": actual["predicted_time_s"]})
            return output

        for source in sorted((app / "Contents/Resources/Examples").glob("*.json")):
            project = invoke("inspect", source)["project"]
            for task in project["tasks"]:
                compare(source, task["id"], source.stem + "-" + task["id"])
        baseline = load_project(app / "Contents/Resources/Examples/single_click.json")
        integrated = replace(baseline, engine=CONTROL_ENGINE,
            parameters=baseline.parameters.with_vision_defaults(),
            control=replace(ControlConfig.source_2014(provenance="desktop portable validation"),
                            execution_scope="integrated_task"))
        source = work / "集成模型.json"
        save_project(integrated, source)
        compare(source, integrated.tasks[0].id, "integrated")

        task = baseline.tasks[0]
        partial = replace(baseline, engine=CONTROL_ENGINE,
            parameters=baseline.parameters.with_control_defaults(),
            control=ControlConfig.source_2014(provenance="desktop portable partial validation"),
            tasks=(replace(task, demonstration=replace(task.demonstration,
                   steps=(DemonstrationStep("point", target="button"),))),))
        source = work / "部分执行.json"
        save_project(partial, source)
        output = compare(source, task.id, "partial", status=3)
        before = (output / "result.json").read_bytes()
        error = invoke("predict", source, "--task", task.id, "--out", output, status=2)
        assert error["ok"] is False
        assert (output / "result.json").read_bytes() == before
        checks.append({"case": "existing output is preserved", "status": "passed"})
        invalid = work / "错误模型.json"
        invalid.write_text('{"schema_version": 2, "schema_version": 1}', encoding="utf-8")
        assert invoke("inspect", invalid, status=2)["ok"] is False
        checks.append({"case": "invalid input reports an error", "status": "passed"})
        example_run = subprocess.run([str(engine), "--cli", "example", "--out", str(work / "CLI 示例")],
                                     cwd=work, env=env, capture_output=True, text=True, timeout=60)
        assert example_run.returncode == 0, example_run.stderr
        checks.append({"case": "bundled CLI resources", "status": "passed"})
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)], check=True)
        checks.append({"case": "moved app signature", "status": "passed"})
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"status": "passed", "checks": checks},
                                     ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Passed {len(checks)} portable application checks; report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

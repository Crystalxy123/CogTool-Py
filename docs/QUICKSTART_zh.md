CogTool-Py读取其自身schema的JSON模型，校验后生成步骤并导出预测JSON与真实事件CSV。先按 [INSTALLATION.md](INSTALLATION.md) 安装本次本地wheel；下列命令都在便携发行目录执行，不需要原开发目录。

查看身份并生成、计算最小自建案例：

```sh
.venv/bin/python -m cogtool_py info --json
.venv/bin/python -m cogtool_py example --out "示例 输出"
```

第二条命令写入 `示例 输出/single_click.json` 与 `示例 输出/prediction/{result.json,events.csv,steps.csv}`。它使用 `klm_baseline`。示例中的点击/按键/Home时长是注明来源的建模假设，不是用户行为测量或官方通用默认值。

需要分别检查、重新计算或保存重载时：

```sh
.venv/bin/python -m cogtool_py validate "示例 输出/single_click.json"
.venv/bin/python -m cogtool_py predict "示例 输出/single_click.json" --out "复跑 输出/baseline"
.venv/bin/python -m cogtool_py roundtrip "示例 输出/single_click.json" --out "复跑 输出/single_click.saved.json"
```

JSON明确保存引擎。CLI不覆写输入选择，内置入门案例仍是默认串行基线。集成计算使用保存了正确策略的输入，并以参数严格核验选择：

```sh
.venv/bin/python -m cogtool_py predict LOCAL_ONLY/benchmarks/inputs/PR-CF-K.json --engine cogtool_control_prefix_experimental --scope integrated_task --run-policy reference_2014 --out "复跑 输出/PR-CF-K"
.venv/bin/python -m cogtool_py benchmark LOCAL_ONLY/benchmarks/manifest.json --out "复跑 输出/benchmark"
```

`--engine`、`--scope`、`--run-policy` 是断言：若与已保存的模型不一致就报错，不修改配置、不改参数，也不自动回退。批量入口从每个输入重新计算，冻结参考只由比较器使用。该 `LOCAL_ONLY` 包是本地研究复跑材料；不表示任意 `.cgt` 导入已经公开支持。

最小Python API同样使用安装包的公开入口。先运行上述 `example`，再执行：

```python
from cogtool_py.io import load_project, export_result
from cogtool_py.runtime import require_configuration
from cogtool_py.engine import predict

project = load_project("示例 输出/single_click.json")
require_configuration(project, engine="klm_baseline")
result = predict(project)
export_result(result, "复跑 输出/API")
```

集成API读取已保存的集成输入后，可以向 `require_configuration` 同时传入 `engine="cogtool_control_prefix_experimental"`、`scope="integrated_task"`、`run_policy="reference_2014"`。也可使用公开的 `runtime.run_project(path, ...)`，其选择参数遵循相同的严格断言规则。多任务输入必须指定task。

检查 `result.json` 的发行版本、实际engine/scope/policy、参数/输入身份、completion_status和termination_reason，再读取任务预测时间。`program_runtime_s`是计算机运行时间；`predicted_time_s`是模型任务时间。不完整、超时或未支持路径保留已执行轨迹，完整任务时间为null。输入错误、模式不符与比较失败不能当作成功。为保留历史结果，每次选择新的输出目录。

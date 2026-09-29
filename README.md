# CogTool-Py

CogTool-Py 是可离线运行、可检查计算轨迹的研究软件候选包。输入为本项目 schema 的 JSON 模型；输出为预测任务时间、生成步骤、状态与事件的 JSON/CSV。普通预测仅使用 Python 标准库，不需要 Java、Lisp、图形会话或研究目录。

**发行候选版 0.2.1rc1；默认串行基线 klm_baseline 0.2.0；显式集成范围 integrated_task 0.6.0。** 后者实现固定 CogTool 2014 源码的受限规则，没有声称完整 ACT-R、任意 CogTool 工程兼容或真人预测准确性。各版本、支持范围和运行政策分别显示，不自动更换输入保存的引擎。

## 从 GitHub 源码开始

本仓库保存 Python 计算引擎、英文 Mac 界面、构建脚本、自建示例、测试和许可证。安装包由源码构建后生成；`dist/`、本地研究结果、论文和外部参考材料不随 Git 上传。下面的历史交付说明提到的本地文件需自行构建或另行取得。

```sh
git clone https://github.com/Crystalxy123/CogTool.git
cd CogTool
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip install --no-build-isolation --no-deps -e .
.venv/bin/python -m cogtool_py example --out outputs/first-example
.venv/bin/python -m pytest
```

首次安装开发依赖需要访问包索引；安装后普通预测可以离线运行。缺少原版 CogTool 外部资料时，依赖这些资料的测试明确跳过，不能视为参考对照通过。英文 Mac 软件的构建步骤见 [English user guide](docs/MAC_APP_en.md#rebuild-from-source)。专用 Java/Lisp 参考脚本需要各自文档列出的外部环境和资料。

## Mac 窗口版

英文版位于 `dist/macos-en/CogTool.app`，可直接双击打开；同目录提供带 `English` 标识的 DMG 安装包和 ZIP。先前中文版保留在 `dist/macos/`。窗口版自带 Python 运行环境，无需先安装 Python、Java 或 Lisp。适用于 Apple Silicon Mac，本次在 macOS 15.6 验证。英文安装与重建说明见 [English user guide](docs/MAC_APP_en.md)。

在窗口中打开本项目 JSON 模型或内置示例，选择任务后运行预测，即可查看时间、步骤及原始结果，并打开导出文件夹。每次运行保存新的目录；模型中的引擎、参数和政策保持原样。窗口版是现有计算引擎的操作界面，不包含原版 CogTool 可视化建模编辑器或通用 `.cgt` 导入。安装、签名状态和重建说明见 [Mac 软件使用说明](docs/MAC_APP_zh.md)。

## 安装与第一次计算

实际验收范围是 macOS 15.6 arm64、Python 3.11.15；包声明 Python >=3.11，其他系统与版本尚未验证。请使用本次交付的本地文件，不按名称从公共索引安装同名软件。下面在便携发行目录执行：

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install --no-index --no-deps dist/cogtool_py-0.2.1rc1-py3-none-any.whl
.venv/bin/python -m cogtool_py example --out "示例 输出"
```

最后一条复制内置自建输入 `示例 输出/single_click.json` 并实际计算，写入 `示例 输出/prediction/`。其中点击/按键/Home时长是明确注明的示例假设，不是官方通用默认或人体实验数据。需要检查版本和输入时：

```sh
.venv/bin/python -m cogtool_py info --json
.venv/bin/python -m cogtool_py validate "示例 输出/single_click.json"
```

普通安装和预测没有第三方运行依赖。提供的 sdist 可用锁定的 setuptools/wheel 重新构建；开发测试和独立参考工具的依赖不属于普通运行环境。步骤见 [安装说明](docs/INSTALLATION.md)。

## 选择引擎与复跑

引擎、初态、参数和运行政策保存在输入中。下列参数严格核对保存的配置；不匹配会报错，不会隐式换引擎、补参数或回退：

```sh
.venv/bin/python -m cogtool_py predict LOCAL_ONLY/benchmarks/inputs/PR-CF-K.json --engine cogtool_control_prefix_experimental --scope integrated_task --run-policy reference_2014 --out "复跑 输出/PR-CF-K"
.venv/bin/python -m cogtool_py benchmark LOCAL_ONLY/benchmarks/manifest.json --out "复跑 输出/benchmark"
```

该命令需要另行展开本地基准材料包。每项从输入重新计算，再由比较器读取冻结参考，不把参考时间喂给引擎。基准含5个官方完整任务、27个合成机制条件和4个本地基线。官方派生输入及轨迹的再分发授权未完整确认，因此材料标为 `LOCAL_ONLY`，没有混入核心 wheel 或 sdist。

PR-CF-K 明确采用 reference_2014 的600秒模拟上限；旧案例和旧10秒政策原样保留。模拟时间、Python事件数限制与子进程墙钟超时是不同概念。结果中的 `distribution_identity` 显示包版本、引擎、scope、政策、参数/输入身份和执行状态；`predicted_time_s` 与 `program_runtime_s` 分别是模型任务时间和程序运行耗时。

完整结果在 `result.json`；`events.csv` 保留实际控制事件字段，集成结果另有 `motor_events.csv`、`vision_events.csv`，生成步骤在 `steps.csv`。每次选择新输出目录保留证据。输入/资源/选择错误退出2；未完成、超时或unsupported退出3并保留null任务总时间；已执行比较不符退出4。未观测状态不会因总时间相同被判定等价。

## API、证据和边界

[快速开始](docs/QUICKSTART_zh.md)给出经过安装环境执行的公开 Python API 示例；`examples/installed_api.py` 只使用安装包公开接口。读取兼容schema 1/2，保存使用schema 2；有效参数不可变，通过经过验证的覆盖接口返回新参数集。

当前只接收本项目JSON。提供转换后的官方输入，不等于通用 `.cgt` 导入；开发目录中的受限转换器和 Java/Lisp 工具归独立验证层。官方参考是固定 commit `a91d91e8dcf95d762b6e08020029a36ea079bbba` 的真实Java生成链加装载兼容移植后端。R1是与冻结记录的软件回归；R2是重新执行参考工具，二者分开记录。

- [支持范围](docs/SUPPORTED_FEATURES.md)：明确区分实现、独立检查与未支持功能。
- [验证说明](docs/VALIDATION.md)：任务族、开发角色、比较范围与证据局限。
- [限制](docs/LIMITATIONS.md)：集成范围的UP/其他功能键与组合键、层级菜单、双击、完整视觉搜索及活动注意力换页重编码尚未支持；DOWN仅指已验证的固定映射。
- [变更记录](CHANGELOG.md)、[许可证](LICENSE)、[来源与第三方声明](NOTICE.md)。代码沿用 LGPL-2.1-or-later；没有改称MIT或公开发布。

本候选包没有复杂GUI、通用Vim实现、原版完整GUI等价或人体预测精度结论。安装隔离验收不称为第三方复现或跨系统验证。本轮统计与真实日志在独立交付报告中，历史706项测试不是本轮预设答案。

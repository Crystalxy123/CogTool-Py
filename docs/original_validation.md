# 原版运行尝试与差分证据

本轮状态：**unverified；三个原版差分案例均未执行（not_executed）**。没有取得原版任务预测时间、生成步骤或 ACT-R 轨迹。原版运行失败不影响离线 Python 原型，但不能据此声明 Python 与 CogTool 一致。

## 固定参考与实际环境

源代码：`https://github.com/cogtool/cogtool`，commit `a91d91e8dcf95d762b6e08020029a36ea079bbba`，位于 `reference/upstream-cogtool`。原版命令与构建要求依据同目录 `README.txt`、`command-line-syntax.txt`、`build.xml`、`lib/macintosh/cogtoolstart`，以及 `reference/upstream-documentation/Processes/configuring-development-machines.txt`、`building-lisp-memory-images.txt`。文档 commit 与获取记录见 `source_audit.md`。

实际探测环境：macOS 15.6（24G84），Darwin 24.6.0，arm64；Oracle JDK 26（64 位 arm64）；Apache Ant 1.10.15。运行日期及所有命令、工作目录、返回码、标准输出/错误的 SHA-256 均在 `validation/original/attempts/manifest.json` 和逐项 JSON/TXT 中。脚本只将构建输出写入 `validation/original/build` / `dist`，未修改参考源码或用户已有 `cogtool`、`code`、`documentation`。

执行记录可复现：

```sh
python3 validation/original/run_attempts.py
```

注意：重新运行会更新该目录下的本机尝试记录；要保留历史请先复制 `attempts`。

## 实際失败与停止位置

| 尝试 | 实际结果 | 证据 |
|---|---|---|
| 固定源码 `ant ... compile`，保留其 source/target 1.5 设置 | 返回码 1；JDK 26 拒绝 source 5 / target 5。461 个源文件进入编译步骤，没有成功生成可运行原版 | `attempts/08_compile_fixed_source.stdout.txt` 与 `.stderr.txt` |
| 直接启动固定源码附带 `clisp-mac-intel/lisp.run -M .../actr6.mem -x ...` | 返回码 127；`bad CPU type in executable`，Lisp 表达式未执行 | `attempts/09_run_bundled_clisp.stderr.txt` |
| 检查附带 CLISP 架构 | 发布用和构建镜像用的两个 `lisp.run` 均为 `Mach-O executable i386` | `attempts/07_binary_architectures.stdout.txt` |

没有修改 Java 目标版本、替换 ACT-R/CLISP、重建内存镜像或调参来绕过失败。当前机器未完成同版本原版 GUI/CLI 的实际任务计算。

工作区原有 `CogTool.dmg` 只记录文件大小和 SHA-256，未挂载或运行，也未证明它由上述 commit 构建。其文件名和发布时间均不足以建立版本对应关系，不能把其中潜在运行结果作为本 commit 的验证证据。

## 后续所需环境

上游开发文档要求 32 位 JVM，并说明其构建环境使用 JDK 1.5；`build.xml:11` 固定 Java 1.5。文档中的 Windows 构建还依赖 Cygwin、Ant 和 NSIS（最后者用于打包）。Mac 启动器优先选用系统 Java 1.5，并使用旧 SWT/Carbon 相关配置；源码附带的 CLISP 是 Intel 32 位二进制。

下一步应在能够执行该版本 32 位程序的隔离旧系统/虚拟机上重现构建，或取得有明确源码构建对应记录的原版程序。需要保存系统/JDK/Ant/CLISP 版本、构建命令、原版程序哈希和 ACT-R 内存镜像哈希。这里列的是待验证环境要求，**没有宣称已验证任何旧系统或 Windows 可运行**。不要仅安装现代 JDK 后就假定旧原版可运行。

## 三个待采集案例

1. `single_click`：一个页面，一个矩形按钮；显式鼠标起点和初始手部状态，已知按钮定位与单击。
2. `text_entry`：点击输入框，转换到键盘，输入指定物理按键序列；记录输入焦点、按键大小写/修饰键及设备切换。
3. `two_page_wait`：两个页面、指定转换、明确系统等待；记录等待相对于触发动作的起止边界以及其是否与模块活动重叠。

每例必须使用与 Python 输入一致的几何、单位、初始页面/鼠标/手/焦点、操作路径和参数。示例名相同不代表输入一致。Python 输出与原版原始文件须分开存放。

上游 `command-line-syntax.txt` 记录 `-f` 命令文件入口及 `import`、`trace`、`computeAllSkilled`、`exportResults`、`saveAs`、`quit`。这些命令仍需在目标旧环境验证；仅有 `exportResults` CSV 不够，还须另存生成的模型/步骤和原始完整轨迹。不得把 Python 自身结果复制成“原版输出”。

## 导入证据的检查内容

证据清单采用 JSON，必须记录：案例标识、完整上游 commit、Python 输入 SHA-256、原版生成的结果文件、原版输入、参数/初始状态配置、生成步骤、原始轨迹、运行方法及运行/构建身份。每个文件须有清单目录内相对路径和 SHA-256；路径不得逃出证据目录。原始输出必须保留，归一化结果只作为比较层。若使用人工归一化，须保留每条步骤/事件到原始输出的对应说明。

输入和证据哈希匹配只证明文件完整性，不能自动证明文件确由原版产生；操作者还必须审核版本对应、运行日志和转换过程。合成测试证据只测试导入/比较代码，绝不计入原版兼容证据。

比较以下项目：人工及自动步骤的类型/顺序/目标/页面；总任务时间；各事件的开始、结束、资源及步骤映射；初始状态、参数、计时边界。缺失的比较字段必须报错，不能忽略后给出“通过”。

### 数值容差先验

- `ACTRTraceParser.java:141` 的轨迹正则只接收三位小数的秒值；`:187` 转换为毫秒。
- `lisp/actr6/framework/events.lisp:127–139` 的 `format-event` 将 `evt-mstime` 分解为整数秒和毫秒。这是离散毫秒时间，并非允许误差的生理学依据。
- 对规范化的同一数值采用绝对容差 `1e-9 s`，相对容差为 0，仅容纳十进制 JSON/二进制浮点解析差异。序列、资源、目标、来源等必须精确匹配。
- 当前串行 `klm_baseline` 的连续公式与 ACT-R 时序不相同。其差异应原样报告；不能为了让基线通过而把阈值改到 0.1 s 或人体预测误差范围。
- 将来若证据只有四舍五入后的显示值，可另行预先定义显示分辨率比较（例如单次三位小数四舍五入最大 0.0005 s）。这只说明显示精度，不能认证底层 ACT-R 时序相容，也不能静默替代默认比较策略。

即使所有字段数值相符，结论也只能是“列出的案例和字段在所声明容差内一致”。本轮的 `klm_baseline` 不会因此升级为完整 CogTool/ACT-R 等价。

## 已实现的证据入口

接口：`cogtool_py.comparison.compare_results(python_result_path, manifest_path) -> dict`。命令行包装见 README 的 `compare` 命令。错误类型为 `EvidenceError`（继承 `ModelError`）；错误信息包含证据字段。它读取保存的结果，不运行 Java/CLISP，也不会根据总时间替你调参。

清单结构如下；所有 `null` 都是**待采集占位符**，不是原版事实，导入器会拒绝它们。应在完成真实运行后建立 `validation/original/cases/<case_id>/manifest.json`，而不是把此模板当作已通过案例。

```json
{
  "schema_version": "1.0",
  "evidence_kind": "original_run",
  "case_id": "single_click",
  "upstream": {
    "repository": "https://github.com/cogtool/cogtool",
    "commit": "a91d91e8dcf95d762b6e08020029a36ea079bbba"
  },
  "input_sha256": null,
  "files": {
    "original_input": {"path": null, "sha256": null},
    "configuration": {"path": null, "sha256": null},
    "generated_steps": {"path": null, "sha256": null},
    "raw_trace": {"path": null, "sha256": null},
    "run_instructions": {"path": null, "sha256": null},
    "runtime_identity": {"path": null, "sha256": null},
    "normalized_result": {"path": null, "sha256": null}
  }
}
```

- `input_sha256` 使用 Python 结果记录的输入模型哈希（不是原版 XML/CGT 字节哈希）；原版模型文件的字节哈希单独保存在 `original_input.sha256`。操作者需据原始项目核对几何与语义是否相同，当前入口并不解析原版项目。
- `configuration` 必须是 JSON，对齐 `input_sha256`、`parameters`、`initial_state`、`task_id`、`timing_boundary`；它们必须与两端规范化结果相同。差异会阻止比较。
- `runtime_identity` 必须是 JSON，包含 `source_commit`、`version`、`platform`、`java_version`、`lisp_version`、`build_method`、`binary_sha256`、`memory_image_sha256`。前六项中的文本须非空，commit 必须是本轮固定版本，两个二进制哈希须是完整 SHA-256。
- `generated_steps` 必须是 JSON 数组，并且与 `normalized_result.steps` 一致。`raw_trace`、`original_input`、`run_instructions` 保留实际采集文件；不得只留摘要或从 Python 反推的数字。
- `normalized_result` 至少含 `engine{name,version}`、`upstream{commit}`、`input_sha256`、`task_id`、`parameters`、`initial_state`、`timing_boundary`、`predicted_time_s`、`steps`、`events`。真实原版结果的规范引擎名是 `cogtool_actr`。每个步骤至少含 `op, origin, demo_index, target, frame`；每个事件至少含 `op, start_s, end_s, resource, step_index`。规范化的步骤/事件附加字段也会比较，不能静默丢弃按键、时长等细节。

返回报告分开给出 `evidence_integrity`（哈希完整性）、`provenance_authenticity`（仍须人工审核）、`comparison_status`（`different` 或 `matched_reported_fields`）、逐字段差异和固定容差。**任何返回值均保持 `original_validation_status: unverified` 与 `equivalence_claim: false`**。这个阶段提供可审计比较机制，不能自动给一个串行基线盖上 CogTool 兼容印章。

`tests/test_comparison.py` 使用标记为 `synthetic_test` 的临时人工小数据检查哈希、版本/输入绑定、配置、路径约束、数值有效性、字段缺失和容差。它们是 A 类独立机制测试。`tests/differential/test_original_cases.py` 则只接受 `original_run`，分别检查上述三个真实案例；缺少清单时逐案 skip。真实清单存在而 Python 结果缺失时测试失败，要求先保存对应 `validation/python/<case_id>/result.json`，不会把缺少对照静默跳过。

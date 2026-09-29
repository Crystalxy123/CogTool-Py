# CogTool-Py 源码核查与来源映射

核查日期：2026-09-24。范围：支持首批鼠标、键盘与明确等待案例所需的模型对象、步骤生成和预测调用链。Python 引擎是 **`klm_baseline` 串行研究基线**；已读源码不等于已执行原版，也不等于完成 ACT-R 迁移。原版差分状态为 `unverified`。

## 1. 固定来源与获取方式

| 材料 | 固定标识 | 本地只读参考位置 |
|---|---|---|
| [CogTool 源码](https://github.com/cogtool/cogtool) | tag `1.3-2014-02-10`；commit `a91d91e8dcf95d762b6e08020029a36ea079bbba`；提交日期 2014-02-10 | `reference/upstream-cogtool/` |
| [官方文档仓库](https://github.com/cogtool/documentation) | commit `1f5fe10e2bebfb7544aa85a6db2c10078df9f9d3`；提交日期 2014-03-27 | `reference/upstream-documentation/` |
| 官网、教程、发布页面 | [官网](https://www.cogtool.org/)、[教程](https://www.cogtool.org/tutorial/)、[发布](https://github.com/cogtool/cogtool/releases) | 仅作为来源入口；可复查行为以固定提交源码为准 |

本轮从用户工作区已有 Git 对象按指定提交导出完整参考树，未把用户工作树中的改动带入参考版本。联网 `git ls-remote` 的实际尝试遇到 DNS 解析失败；不能据此声称获得了最新远程 HEAD。浏览工具能够只读访问官方来源入口。参考树与新 Python 包分开；原有 `cogtool/`、`documentation/`、`code/`、论文与安装包保留。

文档提交比代码 tag 晚约六周，并非同版本发布说明。代码 `build.xml:7–11` 仍写 `1.3trunk` 和 Java 1.5；本报告用 Git tag/完整 SHA 标识代码，不能把构建字符串误报成另一个精确二进制版本。未把现有 DMG 的运行行为当成这个提交的差分证据。

以下简写均展开为可追溯来源：

- `C` = `https://github.com/cogtool/cogtool@a91d91e8dcf95d762b6e08020029a36ea079bbba`。
- `M/` = `C:java/edu/cmu/cs/hcii/cogtool/model/`。
- `U/` = `C:java/edu/cmu/cs/hcii/cogtool/util/`。
- `R/` = `C:java/edu/cmu/cs/hcii/cogtool/resources/`。
- `L/` = `C:lisp/actr6/`。
- `D` = `https://github.com/cogtool/documentation@1f5fe10e2bebfb7544aa85a6db2c10078df9f9d3`。

行号指固定导出文件中的一基行号，包括版权头；可用 `C` 的 SHA 构建 GitHub `blob/<SHA>/<path>#L<line>` 链接，例如 [首个按钮的 Think 判定](https://github.com/cogtool/cogtool/blob/a91d91e8dcf95d762b6e08020029a36ea079bbba/java/edu/cmu/cs/hcii/cogtool/model/KLMCognitiveGenerator.java#L1616)。

后续允许联网的只读重试仍失败：代码仓库报 HTTP2 framing error，文档仓库连接 443 超时，因此没有远程 HEAD 更新声明。完整参考副本已逐文件核对 Git blob：代码 4,754 个、文档 195 个全部与固定提交一致，SHA-256 清单见 reference/manifest.json。macOS tar 起初把 155 个被上游跟踪的 AppleDouble 文件当作元数据处理；它们随后直接从同一提交补齐，记录见 reference/archive_restore.json。可用 scripts/audit_reference.py 重新核对，不依赖用户工作树当前修改。

## 2. 支持实现的源码映射

“实现”只指下表限定的 Python 子集；“源码核对”不代表执行原版验证。Python 自测的实际数量和日志另见测试记录。

| 功能 | 上游文件、符号、行号 | 已确认语义 | Python 对应 | 实现／验证状态 |
|---|---|---|---|---|
| 项目、设计与任务关联 | `M/Project.java:136,169–186`，`Design.java:113,131`，`Task.java:104`，`TaskApplication.java:114,227–237` | Project 有多个 Design、undertakings；TaskApplication 关联 task/design/demo | `models.py` 的 Project、Design、Task | 有界重建；不移植任务组、全部属性与 GUI 通知机制；原版未验证 |
| 页面、控件、转换 | `M/Frame.java:123,159`，`Widget.java:115`，`Transition.java:119,201` | Frame 持有控件；Widget 是转换源；Transition 包含动作、目的页与等待 | `models.py` 的 Frame、Widget、Transition | 矩形 button/link/textbox 与明确转换；原版未验证 |
| 示范和生成脚本分离 | `M/Demonstration.java:238–244`，`Script.java:130–142`，`CognitiveModelGenerator.java:134,151` | 示范有初始页、初始状态和步骤；Script 存生成状态列表及生成器 | `models.py` 的 Demonstration、DemonstrationStep；`generator.py` 的 ScriptStep | 实现独立对象；JSON 是本项目格式 |
| 初始手状态 | `M/DefaultModelGeneratorState.java:119–121,322–340` | 默认右手鼠标、左手键盘；state 保存手位置和最近操作对象 | `models.py` 的 InitialState；`generator.py` | 首版保留所需状态；不是完整上游状态机 |
| 自动 Think | `M/KLMCognitiveGenerator.java:addMental:616–628`、`addMentalForMouseTap:1747–1758`、`handleMouseTap:1616–1650` | 按控件类型/状态判断；相邻 mental 抑制；mouse-up 不加；按钮 terminator 有例外 | `generator.py` | 按钮、链接、文本框子集按源码改写；原版未验证 |
| 自动 Home 与定位 | `M/KLMCognitiveGenerator.java:addHome:634–655`、`addMoveMouse:683–714`；`Widget.java:sameLocation:867–871` | 手不在目标设备才 Home；同 bounds 抑制重复 Move；定位与点击分开 | `generator.py` | 子集规则；无菜单、modifier、tap 自动展开；原版未验证 |
| 键盘分段及换手 | `M/KLMCognitiveGenerator.java:handleKeyInput:776–883`；`U/KeyboardUtil.java` 的键类别/用手映射 | 普通、修饰、命令键分段；只有输入用到鼠标手时才回键盘 | `generator.py`、`models.py` 输入校验 | 限定 US 键序列；不移植中文输入法、组合键和全部命令状态机 |
| 显式 LookAt | `M/KLMCognitiveGenerator.java:1923–1983`；`LookAtScriptStep.java:101,170–184` | 显式注视更新 lastLookedAt；同位置有抑制/警告；通常再调用 addMental | `generator.py`、`engine.py` | 独立明确 duration 的 baseline LookAt；有意不同于上游自动 Think/视觉运行逻辑 |
| 预测层自动 LookAt | `M/ACTRPredictionAlgo.java:ScriptStepWriter.outputScriptStepState:1234–1269`、`ACTR6ScriptStepWriter.generateLookAt:2504` | 脚本层未必含 ACT-R 所需注视；writer 针对新目标生成视觉 productions，文本段除外 | 无 ACT-R writer 对应 | 未实现；不能把该层丢掉后称兼容 |
| 模型生成到预测接口 | `M/ACTRPredictionAlgo.java:prepareComputation:402–438`、`outputModel:441 起`、`outputScript:1328` | Script→Lisp 模型文件→`actr6.mem`→结果变量 | `engine.py` | 换成纯 Python `klm_baseline`；不调用 Java/Lisp |
| 定位几何与运动组成 | `R/cogtool-actr.lisp:frame-vis-loc-template:934–946`；`L/core-modules/vision.lisp:approach-width:3175`；`L/core-modules/motor.lisp:fitts:467–472`、`compute-exec-time(ply):612–615` | 中心坐标、视觉角度、方向宽度影响定位；Fitts 是运动组成部分 | `engine.py`、ParameterSet | 公式/几何组成有来源；完整 ACT-R prep/proc/exec 时间未移植 |
| 点击与按键计时 | `L/core-modules/motor.lisp:compute-exec-time(punch):482–487`、`compute-finish-time(punch):489–490`；`R/cogtool-actr.lisp:599–607,639–652` | 输出事件时间与动作彻底结束时间不同；不能取某个常数代替整个执行链 | `engine.py`、ParameterSet | 基线明确参数；未声称原版点击/按键总时长 |
| 转换等待 | `M/KLMCognitiveGenerator.java:handleTransitionDelay:1761–1776`、`handleAction:1850–1875`；`R/cogtool-actr.lisp:1037–1076` | 正等待变为步骤；Lisp 转换后调度等待，隐藏界面直到完成 | `generator.py`、`engine.py` | 首版串行阻塞等待；不复现模块重叠 |
| 原版轨迹与结果 | `M/ACTRPredictionAlgo.java:ACTRAnalysisOutput.completeWork:278–336`；`ACTRTraceParser.java:parseTrace:163`；`ResultStep.java` | 最后一行解析任务时间，trace 转资源步骤；有 timeout/error 状态 | `engine.py` 的 PredictionResult、`io.py` | 自身真实串行轨迹；不是原版 trace |
| 原版持久化 | `U/ObjectPersister.java:load:397 起,checkpoint:602 起,save:673`；`ObjectSaver.java:139`、`ObjectLoader.java:148`；`M/CogToolSerialization.java:227–234` | ZIP 中 PERSIST XML 对象图，带类名、对象引用及类版本 | `io.py` | 只支持带 schema_version 的本项目 JSON；不支持 .cgt |
| XML 交换格式 | `M/ImportCogToolXML.java:134–136,472,502,595`；`ExportCogToolXML.java:1497,1526` | 根 `cogtoolimport`，交换版本 `1`；与 PERSIST 对象序列化不同 | 无直接兼容模块 | 未实现；不根据 .xml 扩展名猜测格式 |
| 差分验证边界 | `M/ACTRTraceParser.java` 及上述预测调用链 | 同版本输入、配置、生成步骤和真实 trace 才能比较 | `comparison.py`、`validation/` | 提供证据导入与比较入口；真实原版差分未执行 |

## 3. 第一条完整路径核查结论

初始状态为右手在鼠标，首次单击普通 Button/Link：`generateScriptSteps` → `handleAction` → `handleMouseTap` → `addMentalForMouseTap` → `addMoveMouse` → 原单击。脚本层次序为 **Think → MoveMouse → Click**。右手初始在键盘时在 MoveMouse 前插入 HomeMouse。`addMental` 仅在之前不是 mental 时加入；`addHome` 仅在设备位置不同才加入；`Widget.sameLocation` 比較完整 shape bounds，既不是仅看 widget id，也不是仅看当前坐标点。

连续按钮点击还用 `isIdentical`（name、title、type、shape；`KLMCognitiveGenerator.java:1433–1444`）及 `isCompleteTerminator`/`isCancelTerminator`（482/496 行）抑制部分 Think，不能概括为“每次 click 加一个 Think”。文本框首次点击与重复点击另走 1643 行分支。勾选框、单选框、菜单和下拉框另有规则，首版不接受这些未实现类型。

LookAt 必须分层理解：上面的 Script 序列不含自动 LookAt，但 `ACTRPredictionAlgo.ScriptStepWriter` 可能在生成 Lisp productions 时补入。因此 Python 输出“无自动 LookAt 的 Script”不证明人眼活动为零，也不证明与 ACT-R 的总时间相同。源码 `STD_LOOKAT_DURATION = 0.15` 在 1201 行；调用 `decrAndFlushMentalStep(STD_LOOKAT_DURATION)` 在 1250 行已注释，实际调用的是 `flushMentalStep()`。不能仅搜索出 0.15 就将其当成在用的视觉常数，也不能自行把 Think 减掉 0.15。

显式 Think 默认 1.2 秒来自 `M/ThinkScriptStep.java:117`。基线中其他参数必须分别声明是借用的组成参数还是研究者明确给定的假设，不能把它们合称为 CogTool 默认操作总时长。核心参数及范围见 `model_semantics.md`。

## 4. Java/Lisp 边界与不可简化的部分

`ACTRAnalysisInput.compute`（361–389 行）通过 `U/Subprocess.java:execLisp:419–500` 执行独立 CLISP 进程：平台特定可执行文件、`-M actr6.mem`、`-i` 加载生成模型，`-x *cogtool-result*` 取结果。CLISP 用 `ISO-8859-1`（459–463 行）。该版本只显式分支 Windows 与 Intel macOS，不是“有 Java 就可以在任何当前系统运行”。

`D:Processes/building-lisp-memory-images.txt:1–16` 说明镜像包含 CLISP、ACT-R 和 EMMA，CogTool 运行时扩展另行加载。`R/cogtool-actr.lisp:prepare-movement:53–68`、`perform-movement:116–130` 等维护 prep/proc/exec 状态并安排事件。`L/core-modules/motor.lisp:467` 用 `max(min_fitts_time, coefficient × log2(D/W + 0.5))`；这不是常见的 `log2(D/W + 1)`。`ply` 再加 initiation，其他准备、production、视觉和 finish 阶段仍存在。

`R/cogtool-actr.lisp:1060–1076` 的等待通过事件完成且影响可见性；`frame-module-query:747–765` 还受 `*system-wait-blocks-only-vision*` 影响。`cogtool-run-model:1138–1165` 设起始鼠标在 (0,0)、运行 ACT-R、另打印处理器耗时。把各个事件 duration 相加既不自动得到原版任务时间，也不能把处理器耗时混进人的任务预测。

首版没有实现 production firing、EMMA、随机时长、资源竞争或并行调度器。选择串行基线是公开的范围缩减，不能作为完整迁移或验证通过的证据。

## 5. 文件格式的实物检查

除了读 `ObjectPersister`，本轮只读打开文档仓库中的 `end-user/archive/TutorialProject.cgt`：它确为 ZIP，成员为 `PERSIST`；内容以 `<persist version="1">` 开始，后续有 `edu.cmu.cs.hcii.cogtool.model.Project` 类名、类版本和对象 id。文件 SHA-256：`a3945f7df01d501c613a868bcab6299fb8ad90540053b084ae7489c67eb47a33`。这是较早示例，不是与当前 tag 配套的新差分输入；这里只用于核对真实容器形式。

`ExportCogToolXML` 写的 `<cogtoolimport version="1">` 是另一种交换格式。首版 JSON 不读取上述两类 XML，不执行用户输入，也不声称兼容 Java 类图、旧版本 loader 或图片附件。未来移植需分别处理安全 XML 解析、引用/版本迁移和 ZIP 解压边界，不能只改扩展名。

## 6. 构建、文档差异和许可核查

已读 `C:README.txt`、`LICENSE.txt`、`build.xml`、Java 文件版权头，以及 `D:README.txt`、`Processes/configuring-development-machines.txt`、`Processes/building-lisp-memory-images.txt`。历史构建文档 160–177 行要求 Windows、Cygwin、Subversion、JDK 1.5、Ant、NSIS；188–199 行自己注明 SVN 说明待迁移 Git。`build.xml` 使用 bundled SWT/Draw2D、平台本机库和 Launch4j。它们是历史环境记录，不能当作当前 macOS 的已验证安装步骤。原版实际尝试与失败输出保存于 `validation/original/attempts/`。

CogTool Java 文件头明确：CogTool 1.3，Copyright (c) 2005–2013 Carnegie Mellon University；LGPL 2.1 或更新版本。根 `LICENSE.txt` 是 LGPL 2.1 全文；README 提到 `LGPL.txt`，源码树还另有 `res/LGPL.TXT`。本项目根 `LICENSE` 保留完整上游许可证，`NOTICE.md` 保留版权、来源、修改日期及第三方边界，没有将项目整体改为 MIT。

| 类别 | 本轮处理 |
|---|---|
| 依据源码逐条改写的生成/状态规则 | 视为来源于上游的改写内容，以 LGPL-2.1-or-later 处理；文件与规则来源显式保留 |
| 从 motor/vision 模块借用的数学组成与参数 | 标识 ACT-R 来源和它们只代表组成部分；保留有关许可/作者声明 |
| 新 JSON、命令行、导出、验证框架 | 本项目新增实现，同样采用 LGPL-2.1-or-later，避免含混的整体重许可 |
| 自建示意案例和手算测试 | 本项目新材料；不伪称上游案例或实验数据 |
| 上游第三方组件和参考二进制 | 留在参考树，不作为 Python 运行依赖，不打入发行包；原有许可声明保留 |

ACT-R `motor.lisp:1–11` 另明确 Copyright (c) 1998–2010 Mike Byrne/Dan Bothell、GNU LGPL。Java 的整体第三方版权头还列 ACT-R 6.0 的 Dan Bothell、Mike Byrne、Christian Lebiere、John R Anderson；两种声明按各自原文件保留，不能把年份/作者合并成未经核实的新事实。

发布前仍需逐文件核对衍生内容、完整源代码分发与第三方许可清单；尤其是如果未来打包 JRE、CLISP、SWT、XULRunner 或上游文档/图片，不能只依据根 LGPL 文件判断所有内容的许可。本轮没有公开发布，不捏造论文许可，也不把未实际读取的论文用作模型或参数来源。

## 7. 下一步核查任务

1. 在能运行该固定版本的平台获取三个最小案例的生成脚本、原始 ACT-R trace、配置和哈希，再导入差分入口；不以 Python 自己的结果代替原版。
2. 在扩大键盘范围前逐项迁移 command/modifier 状态、键位映射、视觉编码和时间边界；TAB/IME/快捷键不能默默降级成普通字符。
3. 若实现 ACT-R 子集，先定义哪些 productions、模块状态及事件会移植；用事件起止和资源占用验证，不能只比较总时间。
4. XML/.cgt、菜单/触屏/语音、任务组与图形界面均须独立界定兼容范围和测试证据。

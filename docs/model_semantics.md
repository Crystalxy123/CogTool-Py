# CogTool-Py 模型语义与已知差异

默认预测引擎仍为 **`klm_baseline`**：有上游依据的部分步骤生成规则、鼠标定位动作组件和建模者明确给定的串行操作时长。它没有实现 ACT-R 的 production、视觉模块、运动准备队列或模块重叠，**不是完整 CogTool 兼容迁移**。另有显式选择的 `cogtool_motor_subset_experimental` 0.1.0，范围见本文件末节。未与原版实际输出完成逐案例对照的结果一律为 `unverified`。下文原有计时和操作说明均针对基线。

本文件所有上游定位都针对 `https://github.com/cogtool/cogtool@a91d91e8dcf95d762b6e08020029a36ea079bbba`。下表缩写 `J` = `java/edu/cmu/cs/hcii/cogtool/`，`L` = `lisp/actr6/`；因此 `J/resources/cogtool-actr.lisp:frame-vis-loc-template:941` 可展开为完整的 `repo@commit:path:函数:行号`。本地原文保存在 `reference/upstream-cogtool/`，版本与获取记录见 [source_audit.md](source_audit.md)。

## 1. 计时边界与状态

- 时间单位为秒；界面坐标及尺寸单位为像素。矩形坐标为左上角坐标，尺寸必须严格大于零；坐标允许有限的负值。
- 示范输入、生成后的脚本步骤、预测轨迹分别保存。自动步骤有所有者示范步骤及规则来源；它们不是建模者编辑界面所耗费的真实时间。
- Python 计时从给定初始页面、鼠标坐标和手部状态开始，初态本身不收费；从第一个生成操作的开始到最后一个操作或等待的结束，依次累加。
- 初始鼠标坐标是 Python 基线的显式扩展。2014 上游 `cogtool-run-model` 将其设为 `(0, 0)`，见 `J/resources/cogtool-actr.lisp:1138–1164`。NP-B1 的2009存档没有保存这个坐标，r3035源码未知，故该值只是2014条件默认，不能称为已对齐的2009初态。与原版对照必须确认初始位置。
- 本基线的点击与指向分别计时。点击 textbox 建立输入焦点，点击其他控件清除焦点；跳到不同页面后清空焦点，自环转换保留焦点。`keys` 必须有初始焦点或此前 textbox 点击，不能隐含对不存在的控件输入。
- `initial.mouse_hand` 指明使用鼠标的左手或右手；`initial.hand` 指明这只手位于鼠标还是键盘。另一只手按已在键盘处理。本版不会模拟手指位置，也不模拟按键对应用文本、选择区或导航的实际作用。
- Python 轨迹是串行轨迹，不显示虚构的认知、视觉与动作并行。程序计算墙钟耗时与所预测的人类任务时间是不同字段。

## 2. 鼠标定位动作组件

确认过的调用链为：

`ACTRPredictionAlgo` 发出 `move-cursor` → `motor.lisp:move-cursor` 计算距离、接近角与宽度 → `vision.lisp:approach-width` → `device-interface.lisp:pm-pixels-to-angle` → `motor.lisp:fitts` / `compute-exec-time(ply)`。

| 语义 | 固定版本源码位置 |
|---|---|
| 控件尺寸原样写入 Lisp | `J/model/ACTRPredictionAlgo.java:outputFrameElement:904–932` |
| 目标位置为 `x + floor(width / 2), y + floor(height / 2)` | `J/resources/cogtool-actr.lisp:frame-vis-loc-template:934–944` |
| 位移、方向、零距离跳过、距离转视觉角 | `L/core-modules/motor.lisp:move-cursor:721–763` |
| 沿接近方向的矩形截弦宽 | `L/core-modules/vision.lisp:approach-width:3175–3195` |
| 像素转视觉角 | `L/framework/device-interface.lisp:pixels->angle-mth:263–264` |
| 带下界的 Fitts 公式 | `L/core-modules/motor.lisp:fitts:467–472` |
| 动作执行时间包含一次 initiation | `L/core-modules/motor.lisp:compute-exec-time(ply):612–615` |

对鼠标位置 `(mx, my)` 与目标中心 `(tx, ty)`，令 `dx = tx - mx`，`dy = ty - my`，`Dpx = sqrt(dx² + dy²)`。非零距离时，沿位移方向的矩形有效宽度为：

```text
ux = abs(dx) / Dpx
uy = abs(dy) / Dpx
Wpx = min(width / ux, height / uy)
```

轴向分母为零的候选项视为无穷大，即水平移动取 width，垂直移动取 height。这是对原版分段三角公式的代数重写：既不是 `min(width, height)`，也不是矩形的投影宽度 `width*cos(theta) + height*sin(theta)`。

令 `A(p) = (180/pi) * atan(p / (ppi * viewing_distance_in))`。原版分别转换距离和宽度，所以 `D = A(Dpx)`、`W = A(Wpx)`；由于 atan 非线性，`D/W` 一般不等于 `Dpx/Wpx`。本基线抽取的定位时间为：

```text
Tpoint = motor_initiation_s + max(fitts_min_s,
                                 fitts_coefficient_s * log2(D / W + 0.5))
```

鼠标已在目标中心时整个定位为零，遵循原版 `move-cursor` 的零距离跳过行为。源代码的公式含 `+0.5`，不能悄悄换成常见的 Shannon `+1` 版本。非法几何直接拒绝；不沿用原版非正宽度退回“一像素”的容错行为。

**范围限制：**此式只表示已识别目标的 cursor-ply 执行组件。不包含查找或注意目标、production firing、运动特征准备、运动结束后的执行资源占用；也不提供完整点击或全任务的 CogTool 时长。默认鼠标设备的 control-order 为 0；其他指向设备、噪声与随机时序均未实现。

## 3. 参数来源与适用范围

| 参数/量 | 数值与单位 | 上游依据或来源政策 | 基线用途及覆盖 |
|---|---:|---|---|
| `think_s`：Think 默认时长 | 1.2 s | `J/model/ThinkScriptStep.java:DEFAULT_KLM_THINK_DURATION:117` | 自动 Think 及省略 duration_s 的显式 Think；允许显式配置或逐步指定 |
| `fitts_coefficient_s`：鼠标 Fitts 系数 | 0.1 s | `L/framework/device-interface.lisp:define-parameter :mouse-fitts-coeff:405–409` | 仅定位组件；允许覆盖 |
| `fitts_min_s`：最小 Fitts 动作时间 | 0.1 s | `L/core-modules/motor.lisp:define-parameter :min-fitts-time:1196–1200` | 仅定位组件；允许覆盖 |
| `motor_initiation_s`：动作 initiation | 0.05 s | `L/core-modules/motor.lisp:1206–1210`；`J/CogToolPref.java:MOTOR_INITIATION:130`；Java 写入时除以 1000，`ACTRPredictionAlgo.java:465–473` | 每个非零定位组件一次；允许覆盖 |
| `pixels_per_inch`：显示密度 | 72 px/in | `L/framework/device-interface.lisp:define-parameter :pixels-per-inch:382–386` | 视觉角换算；允许覆盖 |
| `viewing_distance_in`：观察距离 | 15 in | `L/framework/device-interface.lisp:define-parameter :viewing-distance:397–401` | 视觉角换算；允许覆盖 |
| `click_s`：单击总时长 | 无软件默认值，s | 模型必须明确给出 value、unit、source | 用户所选串行基线常数；不标称 CogTool 总点击时长 |
| `key_s`：单次按键总时长 | 无软件默认值，s | 模型必须明确给出 value、unit、source | 用户所选串行基线常数；每个明确按键一次 |
| `homing_s`：手部切换总时长 | 无软件默认值，s | 模型必须明确给出 value、unit、source | 用户所选串行基线常数；仅真正发生位置变化时 |
| 显式 LookAt | 无软件默认值，s | 每个操作明确提供 duration_s | 独立基线视觉操作；不等同于 EMMA |
| 系统响应等待 | 无推断值，s | 建模者提供步骤或转换 delay | 串行等待；不估计系统性能 |

上述“允许覆盖”不表示覆盖后的参数经过实验校准。输入来源文本是建模者声明，软件不会自动认证该声明。示例参数仅供软件与手算测试，不能据其输出推断人的真实表现。结果保存本次实际采用的参数值、单位和来源，而不只保存默认值。

## 4. 为什么不从 ACT-R 内部量拼出通用 K、B、H

鼠标单击在 `L/core-modules/motor.lisp:click-mouse:790–800` 中是右手食指 punch。punch 的“输出发生时间”为 `initiation + key_closure`（`483–486`），而“执行资源释放时间”为 `initiation + 2*burst`（`489–490`）；其前还有准备阶段。默认 key closure 为 0.010 s（`L/framework/device-interface.lisp:227`），burst 为 0.05 s（`L/core-modules/motor.lisp:1201–1205`）。这些都不是完整单击时间。Java 点击脚本还包含独立 `prepare-click` 与 `click-mouse` productions（`J/model/ACTRPredictionAlgo.java:1999–2040`）。

普通按键由 `J/resources/cogtool-actr.lisp:press-key:210–222` 查键盘映射，按键不同会产生 punch 或 peck-recoil 等运动。peck-recoil 的输出与资源释放时间不同，回位还要计入，见 `L/core-modules/motor.lisp:555–569`。相邻按键可能共享准备特征，见 `L/support/general-pm.lisp:compute-prep-time:650–655`。CogTool 将 ACT-R 每特征准备时间从模块默认 0.05 s 覆盖为 0.001 s（`J/resources/cogtool-actr.lisp:*default-global-parameters*:1118–1125`），这个数也不是按键常数。

手切换使用 `hand-to-mouse` / `hand-to-home`，硬编码鼠标和键盘位置 `(28, 2)`、`(7, 4)` 与宽度 4.0，调用 `point-hand`，见 `L/core-modules/motor.lisp:849–876` 和 CogTool override `J/resources/cogtool-actr.lisp:89–94`。其时间依赖这些运动组件和调度，不存在已核实的全局 `H = 0.4 s`。`KLMCognitiveGenerator.java:1135` 的 0.4 s 属于上下文菜单 tap-hold，不可借作 H。

本软件因此要求建模者为 click、key、homing 明确提供基线时长。不得把这些显式假设描述成“从 CogTool 移植的默认总时长”。

## 5. 自动步骤与显式 LookAt 的边界

已核实的生成依据包括：

- `J/model/KLMCognitiveGenerator.java:addMental:616–628`：上一个状态已经是 Mental 时，不再自动添加 Think；明确提供的 Think 本身仍是示范操作。
- `addHome:634–655`：仅当鼠标手不在目标设备时添加 Homing。
- `addMoveMouse:683–710`：先确保鼠标手在鼠标；根据 `sameLocation`，避免对同位置控件重复添加移动。
- 普通点击、输入框点击和连续键盘输入使用不同生成状态；Python 仅实现代码中明确列出的 button/textbox/link 子集，不推断菜单层级、子菜单、修饰键、拖动或复杂设备行为。

当前 `generator.generate` 的具体合同如下。表中的 Think 是自动步骤，示范中明确提供的 Think 不会被去重删除。

| 输入情形 | 生成语义 |
|---|---|
| 首次点击 button/link | Think → 必要的 Home(mouse) → 必要的 Point → Click |
| 连续点击同一 button/link | 第二次保留 Click；相同控件不重复 Think，相同 bounds 不重复 Point |
| 点击另一 button/link | 通常重新 Think；若两者同属完成终结词组或取消终结词组，则抑制这个 Think |
| 完成终结词组 | 名称或标签等于 `save/yes/done/ok`，不区分大小写；不是子串匹配 |
| 取消终结词组 | 名称或标签等于 `cancel/no/exit/quit/abort`，不区分大小写 |
| 点击 textbox | 与上次点击控件不 identical 时添加 Think；建立焦点；点击状态重置为 initial |
| ordinary `keys` | 不添加 Think；逐个明确按键生成 key；整段中只要有键需使用鼠标手，就在整段开头切回键盘 |
| `ENTER/BACKSPACE/DELETE/ESC/UP/DOWN/LEFT/RIGHT` | 非连续相同命令键时添加 Think；连续相同命令可跨 `keys` 示范段共享前一个 Think；ESC 用左手，其余本版命令键用右手 |
| 显式 Point | 不推断 Think；必要时 Home(mouse)；重复相同 bounds 的 Point 被抑制并记录 warning，原示范仍保留 |
| 显式 Home | 仅真实切换时使用 `homing_s`；重复要求同一设备记录零时长 no-op |
| 显式 Wait | 保留给定时长的串行屏障；本基线将点击状态重置为 initial |

终结词与 button/link 规则来源为 `KLMCognitiveGenerator.java:isCompleteTerminator/isCancelTerminator:482–508;handleMouseTap:1616–1650`。`identical` 比较控件 name、label、kind、bounds，不比较 id（`isIdentical:1435–1446`）；位置判等则只比较 bounds，不比较 id 或当前页面。键盘规则为 `handleKeyInput:800–883`，手分配为 `J/util/KeyboardUtil.java:243–336`。本版只允许列出的未按 Shift 的美式键盘字符与命令键，不把任意文本展开成键盘操作。`keys` 不承载 `KeyAction.isCommand()` 的整段命令标志；那一分支及 TAB、修饰键均不支持。

上游的 **KLM 脚本层 LookAt** 和 **预测脚本层视觉动作** 不应混为一谈：`KLMCognitiveGenerator.java:1923–1983` 对新的显式 LookAt 目标生成 LookAt 后还调用 addMental；同位置可能只尝试 Think。`ACTRPredictionAlgo.java:1233–1268` 又会为未注视的目标插入视觉 productions（输入段有例外）。其 `STD_LOOKAT_DURATION = 0.15`（1201）不是可靠的固定 LookAt 时长：从 Think 扣除这项的调用在 1250–1254 已被注释。

Python **刻意不复制这一视觉/心理复合语义**：显式 `look_at` 必须给出 duration_s，并作为独立基线步骤保留，不据此额外加 Think；紧接该步骤的自动 Think 也被抑制。它不执行 EMMA 眼动、搜索、注意转移或自动注视。上游 EMMA 默认启用（`J/CogToolPref.java:USE_EMMA:133`）；因此该差异即使在很简单的点击任务中也存在。

## 6. 等待、重叠与任务结束

上游系统等待在 `J/resources/cogtool-actr.lisp:system-wait-start:1060–1069` 将页面置为不可见并安排完成事件；`process-pending-wait:1052–1058` 处理排队等待；完成后恢复可见并更新显示（1071–1076）。`*system-wait-blocks-only-vision*` 默认 nil（23），`frame-module-query` 的 name 检查同时依赖页面可见性和这个选项（759）。这意味着“系统等待是否阻塞全部活动”取决于脚本的资源条件与配置，不能不加说明地把原版全部延迟相加。

Python 的明确合同是：**Click → 正时长的转换 Wait → 零时长 Transition 提交新页面**。Wait 开始于 Click 结束；等待期间仍保留原页面状态，所有后续基线操作暂停，完成后才提交新页面。零延迟直接提交，不凭空生成 wait。显式 wait 同样串行执行。没有后台系统响应、等待和用户活动的重叠，也没有虚构调度器。这是 `klm_baseline` 的定义，而非已验证的原版等待等价关系。

页面路径必须由建模者指定：点击已定义转换的控件时，示范 click 必须显式填写对应 transition id；不匹配即报错。每个页面/控件组合最多有一个点击转换。仅点击可触发本版页面转换；按键（包括 ENTER）不会隐式触发应用导航。

虽然 `cogtool-actr.lisp:36–42` 的旧注释称 productions 为顺序 lock-step，实际时间不能只按高层步骤串行相加。例如 `ACTRPredictionAlgo.java:1663–1715` 的键盘 productions 只对同手连续键要求 execution free，准备与执行可以重叠；点击先准备再执行；视觉还有独立资源。`perform-movement`、`initiation-complete`、`finish-movement`（`cogtool-actr.lisp:116–176`）分别调度输出和资源释放。只有完整实现这些机制并对照真实轨迹，才能宣称该范围的 ACT-R 时序兼容。

原版 `endScript` 发出零 firing 时长的 stop production（`ACTRPredictionAlgo.java:1786–1800`），Lisp 使用 `run *timeout*` 的结果（`cogtool-actr.lisp:1155–1161`）。本基线以最后一个串行操作的结束为边界；未来差分对照必须明确实际原版结果的收尾事件与时间提取方法。

## 7. 输入错误和未实现范围

0.2.0更新：新增menu_select仅支持每任务一次、初始关闭、已知目标的单层context_menu→menu_item。目标保持原菜单类型和parent引用；普通click不能绕过菜单语义，重复菜单选择和嵌套菜单明确拒绝。下文的“菜单层级未实现”指超出这一特例的通用层级。

根据固定KLMCognitiveGenerator.java的produceMenuSteps（1110–1190）和produceItemSteps（1210–1222），生成必要Home(mouse)→Point(parent)→RightClick(parent)→Think→Point(item)→Click(item)→原转换和等待。RightClick保留独立动作名，当前串行时间使用与现有点击同一个显式click_s假设，不冒充ACT-R点击准备、视觉或重叠时序。目标矩形不改，中心仍按原floor规则计算。原版isOpen对后续菜单有状态分支，本版通过拒绝第二次选择避免冒充支持。

此扩展用于固定NP-B1的原示范输入，输入提取不读取历史预测时间来产生动作或时长。NP-A1的多层菜单悬停和未给时长的LookAt仍阻塞。公开输入校验不再执行步骤生成；参数冻结、schema 2及规范内容哈希详见[迁移说明](parameter_migration_zh.md)。

负时长或非有限数值、非正矩形尺寸、未知页面/控件/转换、错误单位、未经支持的引擎或操作类型必须报错，并给出任务、步骤或字段定位，不能忽略该步骤继续声称完整预测。坐标可为有限负数，尺寸和时长分别校验。中文标识与标签不等于中文输入法；本版不将中文字符串长度当成按键数。键盘示例只使用明确、受支持的普通按键序列。

未实现：ACT-R 通用架构及资源调度、EMMA、视觉搜索、自动学习、错误率、认知负荷、中文输入法、复杂快捷键与修饰键组合、拖放、双击间隔语义、触屏、菜单层级、语音、原生 `.cgt` / CogTool XML 兼容。受限规则通过 Python 单元或集成测试不等于原版差分验证通过。

独立验证入口为 `tests/test_calculation.py` 与 `tests/test_generation.py`，标记 `independent`。其证据为手算角度与宽度案例、固定数值常数和上述源码规则；不是从原版导出的结果。数值用例包含 45°/15° 的距离宽度比、30×40 矩形的 50 px 对角截弦、非对角截弦、零距离、floor 中心、串行起止时间及转换屏障。原版差分状态另见 [compatibility.md](compatibility.md)。

## 7. 独立实验运动子集（0.1.0，显式选择）

`cogtool_motor_subset_experimental` 复用原输入校验、示范生成、不可变 ParameterSet、schema 2 和内容哈希。它没有替换 `klm_baseline`。通过 `dataclasses.replace(project, engine=MOTOR_ENGINE, parameters=project.parameters.with_motor_defaults())` 明确选择；只改引擎名而不给完整参数集会报错。保存后可用同一个 CLI `predict` 入口运行，不依赖 Java 或 Lisp。

新增参数为 feature preparation 0.001 s、burst 0.05 s、key closure 0.010 s，值、单位、来源、默认版本全部保存和参与输入哈希；可用原有验证覆盖接口。旧基线参数和内容哈希不变。新引擎不用基线的 click_s/key_s/homing_s，结果明确列出 unused_parameters。代码身份另外取执行包源码 SHA-256，实验引擎版本单独为0.1.0。

已实现右手已经在鼠标上的 cursor/punch：按前一 movement 的 style 和 r/theta 变化计算准备；启动、设备输出、execution 释放分别入队；输出时提交坐标或单击，释放时恢复资源。同一时刻按优先级和入队顺序处理；各相对延迟分别取最近毫秒、精确中点取偶数。Python binary64 与旧 Lisp 浮点在临界值的表示仍可能不同，不能凭时钟规则相同推断逐位一致。

任务采用明确的串行发起策略：当前步骤队列清空后发起下一步骤，最后没有待处理事件才结束。默认值下释放晚于输出；若合法覆盖使 punch closure 大于2倍 burst，则按公式允许先释放、后输出，任务仍等待输出。这一政策不等于完整 ACT-R 的 production/资源调度。不同资源的事件区间重叠，持续时间总和不等于任务总时间。

支持 point、single click/right_click、已支持的单层 menu_select、明确 Think/Wait、自环转换。键盘、Home、LookAt和换页明确拒绝，无静默回退。视觉初态保留 null；不实现 FIND/LOOK-AT/production/EMMA、提前 prepare-click、通用菜单搜索或上游 STOP 规则。共享生成步骤中的旧基线计时注释只作来源记录，实验事件来源与公式决定本引擎时间。详细公式、来源、未采用候选和测试映射见 [机制证据](mechanism_evidence_zh.md) 与 `tests/test_motor_subset.py`。

## 8. 保留的规则控制前缀（prefix_only，0.1.0，显式选择）

`cogtool_control_prefix_experimental` 只执行首个生成 Point 所需的初始化、FIND/LOOK/MOVE 规则，以及由首个鼠标请求实际启动的运动事件。默认引擎仍为输入显式指定的旧模式；此模式不替换前述两个引擎。旧运动模块现提取为可注入共享时钟的 `MotorModule`；原运动子集仍通过同一模块逐步请求、排空队列，0.1.0 的行为和参数保持不变。

控制配置为不可变 `ControlConfig`，与设计、任务、初态、全部有效参数一起保存到 schema 2 并参与内容哈希。使用 `parameters.with_control_defaults()` 显式增加 `production_action_s`，其默认值0.05秒来自选定版本的底层DAT、CogToolPref默认50ms和Java模型输出链。START和SUPPRESS自身的AT为0，不按高层动作统一加时。`override`、保存重载及代码身份仍使用原机制。新引擎的代码版本和execution fingerprint与输入内容身份分别记录。

两个初态类别互斥：`source_2014_defaults` 从空场景/空视觉缓冲区开始，由零AT的START激活页面并自动填充位置；`synthetic_controller_only` 可明确给定位置缓冲区、视觉忙闲与人工状态事件，只用于控制规则测试。源码默认配置不接受人工状态注入或非零初始鼠标坐标。NP-B1从真实对象提取10个控件和2个组位置；ordinary模式会导出关闭菜单的项目。唯一最左目标决定stuffing，不猜测无法还原的组符号或随机平局；平局明确unsupported。2014配置不能证明2009保存模型的初态。

位置缓冲区、已编码视觉内容和视觉preparation/processor/execution分开记录。匹配位置且视觉空闲时LOOK的效用0胜过FIND的−1；空或不匹配时走FIND。requested与unrequested只作为来源保留，因为这些模板没有相应query。MOVE查询manual，不查询visual free。选中与触发分开；触发不重新匹配，绑定保持选择时的chunk身份。事件按毫秒、优先级降序及同优先级入队顺序处理，支持 `:max`/`:min`，不是全局FIFO。

LOOK只实现有源码依据的请求入口和processor busy，不计算EMMA编码/眼动完成。随后MOVE可依据自身条件发出首次鼠标请求；运动输出与释放在共享时钟中真实执行，不能将其结束当作完整任务结束。正常前缀结果固定 `completion_status=partial`，`predicted_time_s`、`reported_task_time_s`、`task_stop_time_s` 均为null，视觉完成时间保持unknown。首目标规则与START规则单独记录。后续生成步骤完整保留但未执行；不把自动Think重新算入前缀。

无候选且仍等资源为waiting；无可进展条件为deadlock；未实现机制为unsupported；事件数或仿真时间上限单独返回状态和快照。即使规则已选中，后续模块也未必接受其请求：若manual在等待触发期间变忙，保留MOVE触发和请求，但不伪造尚未实现的排队执行。动态界面处理锁、视觉完成、后续click/Think、prepare-click重叠和完整STOP/队列结束仍是范围之外。正常prefix成功不代表完整任务或原版等价通过。

源码条件、有效参数及A–J矩阵推导见 [规则规格](control_prefix_procedural_zh.md)；场景提取和初始化链见 [2014视觉初态](visual_initialization_2014.md)。独立测试为 `test_control_rules.py`、`test_control_profile.py` 和 `test_control_validation_runner.py`，可复跑入口为 `scripts/run_control_prefix_validation.py`。历史轨迹只用于诊断，不进入计算或验收阈值。

## 9. 同一控制引擎的完整受限执行（integrated_task，0.3.0）

引擎名仍为 `cogtool_control_prefix_experimental`。明确设置 `control.execution_scope="integrated_task"` 并调用 `parameters.with_vision_defaults()` 才启用新范围；省略 scope 的旧文件仍是前节的 0.1.0 前缀。旧文件不自动增加视觉参数，输入哈希与默认行为保持原样。新范围的七个视觉参数及来源、单位、默认版本一起序列化；代码身份另列，不进入输入内容哈希。

这次从原始 Demonstration 只生成一次受限脚本，再按固定 Java 模板编译 FIND、LOOK、MOVE、prepare-click、click、Think 和 STOP 条件规则。控制、视觉与运动共享同一毫秒时钟与事件队列。规则选择受当前资源条件约束，触发保留选择时的绑定；不逐条阻塞执行旧串行动作。视觉请求按真实偏心角、字符串对象默认频率和有效参数计算编码、眼动及残余编码，并把真实状态更新送回规则竞争。正式输入拒绝人工完成更新或预置视觉内容。

已支持静态、唯一字符串目标、右手在鼠标上的指向/单击、一次单层菜单选择、Think、零延迟自环。prepare-click 可以与指向执行重叠；后续 click-mouse 再产生一个可为零时长的准备阶段。菜单状态在设备输出时提交；ordinary 固定场景中的菜单项不因此重新显示或重建。右键是原示范语义标记；上游设备命令本身仍为 generic punch/click-mouse。

编码提前完成不等于眼动尾事件取消。STOP 也不停止队列：结果分别记录 STOP、最后设备输出、运动/视觉释放、模拟结束及返回时间。只有真实 STOP、必要输出和模块事件全部完成、无 unsupported/保护触发，才按固定源码 run 包装器的模拟经过时间返回 `reported_task_time_s`。事件数和模拟时间保护产生未完成状态及 null 总时间。未知的动态场景、视觉重入、运动执行队列、键盘/Home/显式 LookAt/等待/换页分支明确保留不支持边界。

眼初态由 EMMA reset 独立取 `(0,0)`。完整 source profile 还执行 START 前的空页面 `proc-display`：固定包装器 1152→`build-vis-locs-for` 891–896→PM `clear` 284–292，实际将视觉 preparation 置 busy 并安排 50ms 释放。这不是给全程加补偿，而是改变规则可选性：即使 START 后已 stuff 匹配位置，初次 LOOK 仍不满足 visual free，先选 FIND。旧 prefix_only 0.1.0 保留原诊断快照，未执行这一副作用，因此不能把其 .100 首鼠标时刻视为已对齐的完整初始化答案。

synthetic 初态明确从初始化后的控制状态开始，可改眼位或位置缓冲区，但仍用真实视觉过程。固定配置关闭时间随机化，CogTool 眼动噪声覆盖返回均值；种子和此政策在结果中记录。这是固定 2014 源码范围下的完整诊断执行。2026-09-26 已取得独立 Lisp 后端新运行；该参考带装载兼容补丁并共享 Python 输入生成，归类 ported_reference_backend。可比较的事件和返回边界有新证据，原 Java 前端、完整资源快照及真人行为精度仍未验证，不能据此推断 2009 缓存的初态。

细节见 [视觉公式与生命周期](vision_mechanism_zh.md)、[后续 production 与结束依据](integrated_control_rules_zh.md)、[共享运动提前预备](motor_preparation_zh.md)。独立与集成测试见 `test_vision.py`、`test_shared_module_extensions.py`、`test_control_integration.py`、`test_visual_configuration.py`；复跑入口为 `scripts/run_visual_integration_validation.py`。

## 10. 连续不同父菜单的受限扩展（integrated_task 0.3.0）

冻结的 0.2.0 在真实 NP-B2 的第二条示范明确返回 unsupported；原始失败和 2 项最小回归失败已保留。0.3.0 只放开一个源码可证明的输入边界：整个示范连续使用 menu_select，每个单层 context_menu 父控件只访问一次，所有动作在同一页面且转换为零延迟自环或无转换。同一父菜单重复、跨页、正等待和交错其他动作继续拒绝；klm_baseline、motor 子集和 prefix_only 的原有边界不变。

固定 KLMCognitiveGenerator.java:isOpen:1023–1038 追溯上一点击的父链：前一项属于另一个父菜单时，新父菜单不在该链中，因此 produceMenuSteps:1051–1053 不提前返回，1110–1188 再产生父指向、打开和 Think，随后 produceItemSteps:1210–1216 保留本次选择。同父重复则走另一分支，不在此扩展范围。

这次没有添加新的时长或重写调度器；既有生成器循环和共享控制、视觉、运动模块可连续处理这些步骤。第二次查询继承鼠标、眼位、准备记忆、缓冲区和规则状态；只有任务开始的一次初始化与结束的一次 STOP。每个已生成的自动 Think 编译一次。代码身份与引擎范围版本更新，参数内容身份保持原样。NP-B2 的扩展后结果标为 development_after_extension，不再称为冻结新增验证案例。

对应证据与运行状态见 `reports/validation/20260926T111226Z_frozen_independent/REPORT_zh.md`；边界与连续状态回归见 `tests/test_distinct_context_menus.py`。

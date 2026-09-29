# NP-B1 首个轨迹差异与最小机制增量证据

本核查只读取固定源码和已归档轨迹，不执行原版、不以历史总时长拟合参数。代码依据为 `a91d91e8dcf95d762b6e08020029a36ea079bbba`（2014-02-10）。历史 NP-B1 轨迹自述为 CogTool `1.0.4 r3035 / 05/06/2009-04:34`。本地 `cogtool` 的全部 Git 历史只有 16 个提交，最早为 2013-12-02；未取得 2009 r3035 对应源码。以下源码映射不能证明两个版本逐事件等价。

核查运行：`reports/validation/20260926T055101Z_trace_increment`。原轨迹为该运行 `baseline/repair_validation/official/NP-B1/archived_traceLines.txt`；机器可读公式、行号与文件哈希见 `source_audit/mechanism_rules.json`。

## 已观察到的最早差异

历史轨迹第 169–210 行：SET-START-FRAME 在 0.000 秒选中并触发；FIND 在 0.000 秒选中、0.050 秒触发，填充 visual-location；LOOK-AT 在 0.050 秒选中、0.100 秒触发并请求视觉注意；MOVE-MOUSE 在 0.100 秒选中、0.150 秒触发，随后才请求 MOVE-CURSOR。原串行基线没有这些 production，直接开始 point。

历史轨迹也明确显示视觉与运动重叠：视觉请求在 0.100 秒，视觉编码完成在 0.380 秒，鼠标输出在 0.582 秒。不能把 0.280 秒视觉间隔加在 point 前，也不能由此认定视觉不耗时。

轨迹第 338–355 行：STOP 在 2.495 秒选中并触发，但最后鼠标输出在 2.555 秒、运动释放在 2.645 秒。队列清空才结束。2.6450002 是旧保存结果，不是本轮新原版结果。

## 本轮选定的最小范围

本轮选择 `cogtool_motor_subset_experimental`：移植已知目标鼠标运动和 punch 的准备、启动、输出、释放生命周期以及 movement feature memory。发起策略仍明确串行：上一操作 finish 之后才能发起下一操作；不实现 production、EMMA 或 prepare-click 提前准备的重叠。这是独立实验引擎，不是失败后回退，也不是完整 CogTool/ACT-R 模型。

最早观察差异仍是历史 FIND，**本增量不解释它**。第一处可独立实现的运动差异是历史首个 MOVE-CURSOR 在 0.150 秒请求、0.154 秒准备完成，即新 cursor 4 个 feature 各 0.001 秒。这是由源码公式说明的局部阶段，不是把 0.154 秒写进模型，也不以总时长更接近历史作为目标。

实施状态为 preparation、processor、execution 各 busy/free，last-prep movement 的 style/hand/finger/r/theta，实际 cursor 坐标、整数毫秒时钟和同刻事件序号。请求时占用 preparation 和 processor，计算与旧 last-prep 的差并立即更新 last-prep；准备完成时释放 preparation，并在 execution 空闲时开始执行；I 后释放 processor；输出只提交光标位置或按钮事件；finish 才释放 execution。整体 manual state 是三种 busy 的逻辑或。

计算时间必须从各自起点发出：`prepare_end=request+round_ms(P)`；`init_end=prepare_end+round_ms(I)`；cursor `output=prepare_end+round_ms(I+F)`，`finish=prepare_end+round_ms(I+F+B)`；punch `output=prepare_end+round_ms(I+K)`，`finish=prepare_end+round_ms(I+2B)`。不能将 output 当 finish，也不能重复加 baseline `click_s`。没有运动的零距离 point 不做准备、不更新 last-prep。

Think 和 Wait 不清除 movement memory。键盘和 Home 本身会改变 motor movement style；若本轮不实现其真实 style，实验引擎应明确拒绝这些输入，不能悄悄沿用上次 cursor/punch memory。串行已有 Think/Wait 保留自身明确时间，不能额外增加 production 默认时间。没有已实现事件和未释放 motor 资源才结束。

## 已排除的 FIND 最小候选及原因

原考虑 `cogtool_find_subset_experimental`，但它依赖下面的 buffer/ready 假设，不能直接覆盖历史 NP-B1，故本轮不实现。以下保留其审计边界，供后续正确实现时参考。

最小状态为当前 frame、目标身份 `(frame_id, widget_id)`、visual-location 缓冲区目标或空值、一个串行 goal 阶段、procedural busy/free、时钟和事件插入序号。目标的矩形位置属于 buffer 内容，但不能用“坐标相同”替代目标身份匹配。`Widget.sameLocation` 仅比较 bounds；它用于 writer 是否插入自动 LookAt，不能代替 Lisp production 中 `visual-location.value` 的目标名称匹配。

必须显式声明以下范围条件：目标已知且唯一、frame 可见、没有视觉位置自动 stuffing、无未建模视觉阻塞、串行下游可继续。初始空 buffer 和换 frame 后清空 buffer 是该子集的明确状态约定；不是所有原版运行的事实。原版 `stuff-visloc-buffer` 会在缓冲区为空等条件下自动填充，历史 NP-B1 的第 176 行就存在这种事件。

**触发：**实际请求目标且目标在当前可见 frame，goal 阶段允许请求，procedural 空闲，buffer 为空或目标不匹配。在上述子集 ready 条件下，匹配 buffer 时复用位置、不再计 FIND。不能对每个示范或生成步骤无条件加 0.05 秒。

**选中与时间：**选中 FIND 后占用 procedural；`fire_ms = selected_ms + round_even(action_time_s / 0.001)`。默认 action time 为 0.05 秒，来源是 `:dat`，不是从旧轨迹估计。不可由 duration、目标面积或移动距离反推该时间。

**触发后：**触发时推进本子集 goal，释放 procedural，发出同一时刻的位置请求；已知唯一目标匹配成功后，在同一时刻写入 buffer。原版 visual-location 请求自称始终 free，不能将这一步伪装成持续 0.05 秒的视觉占用。0.05 秒占用的是 procedural 选中到触发。

**同时事件：**按整数毫秒、优先级、插入序号排序。写 buffer 的优先级 10；普通 production fired/位置请求优先级 0；下一轮 conflict resolution 优先级 `:min`。同优先级先插入先执行。逻辑后继应在该时刻 buffer 更新之后继续。

**结束：**最后串行组件完成、没有待处理 FIND 或 buffer 写入事件、所有已实现资源释放后结束。LOOK_AT 请求/编码完成、眼动、motor prep/执行重叠没有建模；对应未知时间应保存 null。若结果保留 LOOK_AT_REQUEST 观察标记，它只能是明确未建模的请求标记，不能产生视觉完成事件或假称 visual free 已由模型证明。

## 为什么不能直接说“新位置必定 FIND”

`ACTRPredictionAlgo.java:1235–1256`：焦点是 widget、与上次 looked-at widget 的 bounds 不同、当前不是显式 LookAt 且不是文字段时，writer 插入自动 LookAt；pending Think 原时长被完整 flush，原先减去标准 LookAt 时长的语句已注释。

`generateLookAt:2513–2584` 同时生成以下分支：

|分支|选中条件|动作/优先级|
|---|---|---|
|FIND|goal=s，frame 名称一致且 visible|请求目标位置，goal=s+1，utility=-1|
|LOOK-AT 直接分支|goal=s，visual-location 匹配目标，visual.state=free，frame 可见|请求 move-attention，goal=s+2|
|LOOK-AT FIND 后分支|goal=s+1，其余条件同上|请求 move-attention，goal=s+2|

因此目标位置已存在且 LOOK-AT 的资源条件满足时，可以直接走 LOOK-AT，跳过 FIND。若 buffer 已匹配但 visual busy，不能仅凭匹配就宣称 FIND 一定被跳过。该文件 `2077–2117` 的移动模板也有 `find-location` fallback（utility=-1，保持 goal 状态）及直接 MOVE-MOUSE 分支；MOVE 要求匹配 buffer，且 manual preparation、execution 和整体 state 都 free。

本增量若只实现串行 point 的 location fallback，依赖的是后一个更窄分支。它能测试缺失的请求机制，但不应把其事件名称或调度结果当作完整复现旧版 FIND→LOOK→MOVE。

## 具体源码定位

所有路径相对 `reference/upstream-cogtool/`。

|规则|路径与行号|
|---|---|
|自动 LookAt 条件及完整 Think flush|`java/edu/cmu/cs/hcii/cogtool/model/ACTRPredictionAlgo.java:1235–1267`|
|sameLocation 仅 bounds|`java/edu/cmu/cs/hcii/cogtool/model/Widget.java:867–872`|
|FIND 与两条 LOOK-AT 分支|`java/edu/cmu/cs/hcii/cogtool/model/ACTRPredictionAlgo.java:2513–2584`|
|point find-location/MOVE 的竞争分支|同文件 `2075–2117`|
|默认 production action time|`lisp/actr6/core-modules/procedural.lisp:1968–1969`；`lisp/actr6/modules/utility-and-reward-1.lisp:166–179,190–191`|
|selected 占用、延迟 fired|`lisp/actr6/core-modules/procedural.lisp:1856–1887`|
|fired 执行动作、后续最低优先级 conflict resolution、释放|同文件 `1894–1925`|
|位置请求 0 延迟；成功写 buffer 0 延迟、priority 10|`lisp/actr6/core-modules/vision.lisp:2773–2795,2429–2449`|
|位置请求始终 free；自动 stuffing|同文件 `2669–2675,891–910`|
|每个相对延迟转整数毫秒|`lisp/actr6/framework/misc-utils.lisp:349–355`；`lisp/actr6/framework/scheduling.lisp:936–980`|
|同刻优先级与 FIFO|`lisp/actr6/framework/scheduling.lisp:823–860`|

`find-%c` 在上述 LookAt 模板里没有 `:at 0` 覆盖。`DelayScriptStep` 旧模板在 `2485` 有另一个上下文的 `(spp find-%c :at 0.0)` 字符串，不能据此把这里的 FIND 改成零时长。START、STOP 的 `:at 0.0` 则明确位于 `1772–1799`；Think 的 `:at` 为其自身时长，位于 `2611–2625`，不能再叠加默认 0.05。

## 本轮 motor 增量的已核实公式

令 feature 时间 `f=0.001 s`、initiation `I=0.05 s`、burst `B=0.05 s`、key closure `K=0.010 s`。前三项来自 CogTool 的覆盖配置 `resources/cogtool-actr.lisp:554–573`，K 来自 `framework/device-interface.lisp:227`；不能误用原 ACT-R motor 类初始的 feature 0.050 秒。

- `general-pm.lisp:650–655`：无上次 movement 或 style 变化时，prep=`f*num_to_prepare`；同 style 时 prep=`f*feat_differences`。新 cursor-ply 有 style、hand、r、theta 共 4 个非 dummy feature；新 punch 有 style、hand、finger 共 3 个。hfrt 声明 hand/finger/r/theta；ply 的 finger 为 `:DUMMY`、style 为 `:PLY`（`motor:603–605`），`num-to-prepare=1+非nil非DUMMY字段数`（`general-pm:752–757`）。`last-prep` 在开始 prepare 时就改写，不能只记录最后完成的运动。
- `motor.lisp:496–500`：punch 同 style 换 hand 需 2 个 feature，只换 finger 需 1 个，否则 0。`513–523`：hfrt movement 同 hand/finger 时，距离差不小于 2 度加 1，方向差不小于 π/4 加 1；方向差按源码绝对差，没有圆周折返。距离阈值单位是角度，方向单位是弧度（`403–412`）。
- cursor 输出时间，从 `perform-movement` 开始算：`I + max(min_fitts, b*log2(D_angle/W_angle+0.5))`；鼠标 control-order=0。释放 execution 时间为输出时间再加 B。距离及宽度先按像素/ppi/视距转角度，使用已有 Fitts 核查；目标位置输出时刻不等于资源释放时刻。
- punch 输出时间为 `I+K=0.060`，释放 execution 为 `I+2B=0.150`（`motor.lisp:482–490`）。不能把全部 `click_s` 继续加在这些分段后。
- 连续 cursor 在同 hand 和 dummy finger 下只比较 r/theta；目标 width 不属于准备 feature。cursor→punch→cursor 的 style 两次改变，后两个准备量分别 3 和 4。2014 button writer 不论上层按钮标签都生成 `hand right / finger index` 的 punch（`2003–2017`），旧 NP-B1 也明确是 INDEX；不能因为上层 `right_click` 名称就自行改成 middle finger。
- prepare 开始占用 preparation 和 processor；preparation-complete 释放 preparation。立即执行的 movement 在 execution 空闲时开始执行；执行开始占用 processor、execution；I 后释放 processor，finish 后释放 execution。整体 manual state 是三者 busy 的逻辑或（`general-pm:244–252,501–537,623–635,671–713`）。
- prepare-click production 只查询 preparation free，可与 cursor 执行重叠；click production 只查询 execution free（Java writer `2003–2037`）。点击内部仍会调用 punch prepare，但同一已准备 punch 的 feature 差为 0。Think 查询整体 manual state free，默认时间是其自身 1.2 秒；STOP 无 manual guard，但仍需清空事件队列后报告最终时间。

若后续实现全部 production/motor 子集，必须另做 visual-ready 前提审计，不能因视觉耗时未知就把 visual state 无条件置 free。历史轨迹第 176 行已自动塞入与第 187 行同名目标但仍选择 FIND，而 2014 模板存在跳过分支；这正是不能把归档轨迹当作 2014 规则输出的版本警示。

## 本轮 motor 独立手算验收方案

1. 新 punch：P=3 ms，I=50 ms，K=10 ms，B=50 ms。从 request=0 起，prep end=3、init end=53、output=63、finish=153 ms。下一相同 punch 在 153 ms 请求时 P=0，output=213、finish=303 ms；两个动作完整结束为 303 ms。期望值直接由常量公式计算，不使用旧 trace。
2. 将上例中间加入 Think 1.2 秒或 Wait 0.3 秒：last-prep 仍是 punch；后一个 punch 的准备仍为 0。相同 style 换 finger 的 command 级测试 P=1 ms，换 hand P=2 ms。
3. 新 cursor 用可手算 Fitts 下界的合成几何，使 F=0.1 秒：P=4 ms、init end=54、output=154、finish=204 ms。prep/processor/execution 区间分别为 [0,4)、[0,54)、[4,204)；坐标只在 154 ms 的输出事件提交。合法初始坐标和真实目标矩形从合成案例给定，不取 NP-B1 的目标值。
4. 第二个 cursor 使用相同 r/theta、不同目标 width：prep=0；宽度仍可改变 Fitts 输出时间。改变 r 恰好 2 度或 theta 恰好 π/4 时，各多一个 feature；略小于阈值则不增加。r 使用转角度后的移动幅度，theta 使用 atan2 的弧度。
5. 方向靠近 -π 与 +π 的两次移动：直接绝对差接近 2π，应计方向变化；不要套用最短圆周角差。新 style 或空 memory 再次为 fresh prep。
6. 零距离 cursor：无 prepare/init/output/finish 新事件，不更新 last-prep；随后 punch/cursor 的准备必须仍与零距离之前的 movement 比较。
7. 串行 cursor→punch：punch request 必须等 cursor finish，不在 cursor output 或 preparation-complete 时提前开始。状态不能重叠到同一 execution；任何时刻 overall manual state 应等于三个 busy 的或。
8. Think/Wait 不加入 production 0.05，baseline 的 modeler `click_s` 改动不应改变实验 punch 公式。keys/home 等未实现 style 必须在发起任务前拒绝，不输出部分结果。
9. 每个相对事件延迟独立转整数毫秒，同刻同优先级 FIFO；测试需要覆盖 I=0 或 P=0 时顺序仍为请求→准备完成→启动/输出/释放，并且没有悬挂 busy。事件的数值、资源区间、输出时刻和最终结束均断言。

## 未采用 FIND 候选的独立验证要求

1. 无目标动作，仅 Think(1.2)+Wait(0.3)：FIND 计数 0，总时间 1.5，不给 Think/Wait 加 production 默认时间。
2. 空 buffer、单个已知目标：SELECT=0 ms，FIRED=50 ms，buffer 写入=50 ms；procedural 仅在 [0,50) busy，visual-location 不声明 busy。
3. 同一 frame、同一目标连续请求：在子集 ready 条件下只首个 FIND；中间 Think/Wait 不自动清除 buffer；换目标一次才再 FIND。
4. 不同 widget 具有相同 bounds：writer sameLocation 与目标匹配必须分别测试。请求的目标 value 不同且 buffer 不匹配时，不能仅以 bounds 相同跳过 location 请求。
5. 显式给定匹配初始 buffer：FIND 为 0；空初始 buffer为 1。若当前输入格式不能表示这项状态，则结果必须标记采用“初始空”的子集假设，不声称原始初态已对齐。
6. 换 frame：先完成模型已有 transition barrier，再使旧 frame buffer 失效；新 frame 中同名 ID 不应命中旧目标。
7. 同刻排序：0 延迟写 buffer（priority 10）先于同刻最低优先级 conflict resolution；相同时间/优先级按入队先后。每个延迟独立量化，不能事后只 round 总时间。
8. 毫秒量化用人工设计的非边界与精确边界值测规则，不从论文或 trace 反推。例如精确有理数 2.5 ms、3.5 ms 的 ties-even 结果分别为 2、4；实际 Lisp float 与 Python binary64 在恰好边界附近的表示差异须单列数值实现限制。
历史轨迹用于发现与定位差异，不用作测试期望值的生成器。最小增量即便使某个局部事件更接近历史，也不能据此将总时长验证标为 PASS 或宣称 ACT-R 等价。

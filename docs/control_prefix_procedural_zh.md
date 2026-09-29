# 2014 生产规则控制前缀：源码执行规格

本文件只核查固定公开源码 `a91d91e8dcf95d762b6e08020029a36ea079bbba`（`1.3-2014-02-10`），不把 2009 年保存的轨迹当作 2014 年初始化或匹配规则。核查对象为 `reference/upstream-cogtool` 的 Java 模板、ACT-R procedural、utility、buffer、scheduler，以及视觉请求入口；没有运行原版 Lisp，也没有估计 EMMA 完成时间。机器可读规则与逐文件 SHA-256 见本轮 `source_rules/production_rules.json`。

## 结论与最小范围

可以支持“静态当前场景、已声明的初始位置缓冲区和视觉模块状态、空闲手动模块、正常 2014 参数配置”下，到第一次 `+manual> isa move-cursor` 请求为止的控制前缀。规则应由当前状态匹配，而不是固定执行 FIND、LOOK、MOVE 三步。匹配的位置可能使 FIND 被跳过；视觉忙也可能使已经匹配位置的初态先执行 FIND。

LOOK 请求后的 MOVE **不查询视觉模块是否空闲**。因此，在手动模块空闲、位置仍可用的范围内，无须伪造一次视觉完成事件就能发出第一次鼠标请求。视觉请求启动时的忙状态有源码依据；请求之后任意时刻的真实视觉完成状态未知。前缀结果应显式保留未建模完成，并令完整任务总时长为 `null`。可继续观察该首个鼠标请求的运动输出/释放，但这不把整个认知任务变成已完成。

本规格的匹配与冲突范围固定为：`use-tree=nil`、`er=nil`、`egs=0`、`vpft=nil`、无效用或冲突 hooks、无学习/编译、无运行中改参数和任意模型命令。真实动态 `proc-display` 受显示锁影响；直接写 buffer 的人工更新是单独标识的控制测试，不等同于真实界面变化。

## 规则模板

以下 `S` 为 Java writer 当前状态，`T` 是目标的源代码全局 value，`F` 是当前 frame。`%s` 仅取当前状态，`%1s` 取其下一状态，`%2S` 同时推进 writer；定义见 `ACTRPredictionAlgo.java:1471–1477`。不得把两个 LOOK 分支误认为连续执行。

|规则|选择时全部显式条件|RHS 主要效果|效用 / AT|来源|
|---|---|---|---|---|
|FIND|goal isa klm、state=S；frame name=F 且 status=visible|请求 visual-location(value=T)；goal→S+1|−1 / DAT|`ACTRPredictionAlgo.java:2513–2531`|
|LOOK direct|goal state=S；visual-location isa visual-location、value=T；visual state free；frame name=F、visible|请求 move-attention(screen-pos=所绑定的位置 chunk)；保留 location buffer；goal→S+2；suppress-re-encoding=t|0 / DAT|`ACTRPredictionAlgo.java:2533–2558`|
|LOOK after FIND|同上，但 goal state=S+1|同上，goal→S+2|0 / DAT|`ACTRPredictionAlgo.java:2560–2585`|
|FIND-LOCATION fallback|goal state=S+2；frame name=F、visible|请求 visual-location(value=T)；goal 保持 S+2|−1 / DAT|`ACTRPredictionAlgo.java:2075–2092`|
|MOVE|goal state=S+2；location isa/value 匹配；manual preparation、execution、state 均 free；frame name=F、visible|请求 move-cursor(loc=所绑定的位置 chunk)；保留 location buffer；goal→S+3|0 / DAT|`ACTRPredictionAlgo.java:2093–2117`|
|SUPPRESS-RE-ENCODING|goal isa klm、suppress-re-encoding=t；visual state free；frame status visible|请求 visual clear；清除 goal flag|0 / 0|`ACTRPredictionAlgo.java:1755–1771`|
|START|goal 对应启动 state|设置起始 frame，推进 state|0 / 0|`ACTRPredictionAlgo.java:1772–1783`|
|THINK（若前缀包含）|goal 对应 state；manual state free|推进 state|0 / thinkDuration|`ACTRPredictionAlgo.java:2611–2625`|

FIND 没有要求 location buffer 为空，也没有要求视觉模块空闲。LOOK 和 MOVE 没有再次检查 widget 当前可见性、所属 scene、location 的来源 frame 或 requested 标记；这些约束不能私自加进其 LHS。frame 查询见 `cogtool-actr.lisp:747–765`，name 使用 `string-equal`，visible 使用设备显示状态。场景、位置 chunk 与已编码视觉对象必须分开表示；位置匹配不是视觉对象编码完成。

LOOK 前的自动插入判断在 `ACTRPredictionAlgo.java:1235–1266`；源码调用 `flushMentalStep()`，过去减掉 LOOK 时长的代码已经注释。因此不得用新增 production 延迟再覆盖/加倍已有 THINK，也不得从 THINK 减去虚构的 LOOK 时间。`DelayScriptStep` 内另有 `find :at 0`（2485），不能套用到这里的 FIND。

## 匹配、选择与触发

`procedural.lisp:1285–1338` 在 conflict-resolution 时清空匹配缓存和 production bindings，然后按 isa/slot/query 等条件建立 conflict set。禁用规则不参与。`production-parsing-support.lisp:206–226` 将 `=visual-location` 绑定为当时 buffer 内的 chunk 身份；411–425 编译 isa/slot 条件，602–619 编译显式 query。

选择后以零相对延迟、`:max` 优先级调度 `production-selected`（procedural 1433–1450）。selected 将 procedural busy 置为真，按该 production 的 AT 调度 `production-fired`（1856–1887）。默认 AT=0.05 秒；selected 与 fired 必须是分开的事件。

**fired 不重新匹配 LHS。** `procedural.lisp:1894–1904` 直接执行已编译 actions；注释明确说明 production 不会失败触发。期间 goal、位置 buffer、frame 或模块状态变化，都不是自动取消这次 firing 的依据。`un-delay-conflict-resolution`（1526–1536）仅重新安排等待中的 conflict-resolution，不会取消 selected 的 firing。

RHS 也不是“全部状态的深拷贝快照”。请求的变量从 selection-time binding 代入（parser 802–807）；如果 location buffer 被新 chunk 替换，请求仍使用旧绑定 chunk 身份。原绑定 chunk 被直接修改 slot 则是另一种情形，不能声称它的所有值都冻结。`=goal> state ...` 修改执行时的当前 goal buffer（766–770）。空的 `=visual-location>` 是防止 strict harvesting 的 dummy action（728–731、970–986），不会把旧 chunk 写回去覆盖新 buffer。

fired 结束后安排零延迟、`:min` 优先级的下一次 conflict-resolution，并释放 procedural busy（1912–1925）。同一选中规则等待期间，不得因每个 buffer 更新而重新选择、重置 bindings 或发第二次 mouse request。无候选时使用 `schedule-event-after-change` 的等待方式（1468–1473），而不是按固定时间轮询。

## requested 标记与视觉请求

`buffers.lisp:644–650` 只在显式 `buffer requested/unrequested` 查询时检查标记；普通 `=buffer>` 不隐含此条件。本轮三个模板没有这个 query。因此同内容的 stuffed 与 requested location 在这里匹配相同分支，来源保留在记录中即可。stuffing 使用 requested=nil（vision 891–903），成功显式 FIND 使用默认 requested=t（vision 2439；buffers 768、797）。

FIND 请求经 vision 请求入口 2773–2795 安排零延迟 `find-location`；成功搜索在 2434–2446 安排 priority=10 的 buffer write，并通过 priority=9 解锁；失败设置 loc-failure 并输出 failure 事件（2447–2449）。这不是另一个固定 50 ms 搜索时长。候选选择与初始化属于独立视觉位置证据；多个候选时不能偷用 trace 里的目标。

LOOK 的视觉请求还有一个容易漏掉的选择期副作用：parser 1073–1086 编译 warning conflict-code，procedural 1448–1450 在选择时执行它。`vision.warn-vision` 2691–2696 获取 device lock；`pm-module-request` 2701–2708 在实际 visual 请求时安排 `:min` 的解锁。这是显示处理锁，不是 visual busy。`device-interface.lisp:869–887` 的解锁可能使等待中的显示更新继续运行。最小静态前缀可以记录锁并声明不支持动态显示处理；若允许动态显示，必须实现其阻塞与释放语义。

视觉请求入口在 vision 2745–2768 验证 screen-pos chunk 并安排零延迟 move-attention。EMMA 的 move-attention 在 257–310 处理请求并启动视觉 processor busy（289）；此处不移植其识别、眼动准备和完成时间。不能把未知完成等同于永远忙，更不能把它设为零延迟完成。

## 参数的有效来源链

|参数|底层默认|CogTool / generated model 影响|本规格值/限制|
|---|---|---|---|
|`:dat`|procedural 1968：0.05 秒|Java outputDesign 464–473 输出 DAT；CogToolPref 132 默认 50 ms；正常配置使用默认值|0.05 秒；每 rule 显式 AT 可替代|
|`:at`|utility 166–179 默认函数读取 DAT|START、SUPPRESS、STOP=0；THINK=thinkDuration；FIND/LOOK/MOVE 无 AT 覆盖|依规则，不按高层动作统一加时|
|`:esc`|central-parameters 113：nil|cogtool-actr 1118–1125：t|t，但 EGS=0|
|`:er`|central-parameters 115：nil|本次已检查的 CogTool 常规生成路径无覆盖|nil|
|`:egs` / `:iu` / `:ut` / `:ul`|utility 370–381：0 / 0 / nil / nil|FIND 两种模板显式 U=−1；LOOK/MOVE U 默认0|固定；不启用噪声或学习|
|`:vpft` / `:ppm`|procedural 1965、1993：nil / nil|常规路径无覆盖|固定关闭|
|`:utility-hook` / offsets / conflict hooks|utility 390–398、procedural 1997：nil|可扩展但不属于普通生成模板|不支持自定义 hooks|
|`:use-tree`|procedural 2010：nil|不输出 trace 的 Java 分支454–456改成t；默认研究关闭、trace开启，保持nil|明确使用nil配置与定义顺序|
|`:epl`|production-compilation 809：nil|常规路径无覆盖|不启用编译|

`define-cogtool-model` 1167–1174 从 default-global-parameters 拷贝并依次覆盖，然后在生成规则前调用 sgp。另有 1179 的可选 `/tmp/act-r-kludge.lisp` 外部加载口；本实验不加载这个扩展，不宣称复原了任意用户机器上保存的研究偏好。Java 在非研究替代参数路径输出 50 ms DAT，而不是只依赖 ACT-R 初始化默认。

AT/U 的默认值是**首次访问时缓存**，不是必然在 production 构造时初始化：procedural 711–737 的 accessor 先查参数表，缺值才调用默认函数并保存；显式 `spp` 参数优先。utility 311–314 还警告 production 已存在时改 DAT/ESC/UL/IU 不受支持。本规格参数在运行开始前固定，不接收运行中的参数写入。

`compute-utility`（utility 193–214）先接受 numeric hook override，否则为 production U +（ESC 且 EGS 非零时的噪声）+ numeric offsets。默认配置退化为 U。utility threshold 为 nil。候选按最大效用选择；`er=nil` 时同效用候选覆盖先前 best（procedural 1382–1388），不是随机也不是先定义者胜。`add-production` 756–758 使用 push-last；在 `use-tree=nil` 范围内，同效用因此由**后定义规则**胜出。`er=t` 才 permute 平局列表（1393–1394），本范围拒绝它。

## 同刻调度与计时

事件队列键为 `(整数毫秒, priority 降序, 同 priority 入队顺序)`，`:max` 高于所有 numeric，`:min` 低于所有 numeric。定义及比较代码为 scheduling 823–860；FIFO 仅适用于同一时刻且优先级相同的事件。相对时间在 scheduling 967–968 逐事件转换为 `now_ms + seconds->ms(delay)`；`seconds->ms` 为 `(round x .001)`（misc-utils 349–351）。Common Lisp 的 ROUND 在精确中点使用偶数舍入，但底层浮点表示可能影响中点；不能把保留三位小数的轨迹文本当作时钟，也不能只在任务总时长末尾舍入。

|事件|相对延迟|优先级|来源|
|---|---|---|---|
|reset 后初次 conflict-resolution|0|`:min`|procedural 895–898|
|production-selected|0|`:max`|procedural 1437–1441|
|production-fired|AT|0（默认）|procedural 1875–1887；scheduling 939|
|RHS goal modification|0|100|parser 759–773|
|RHS module request|0|50|parser 800–810|
|RHS implicit clear on request / harvest|0|10|parser 970–1004|
|视觉 location buffer write|0|10|vision 2439；stuffing 898–903|
|视觉 location lookup unlock|0|9|vision 2441–2445|
|find-location / move-attention 内部调用|0|0|vision 2761–2766、2791–2795|
|视觉请求释放 selection device lock|0|`:min`|vision 2701–2708|
|fired 后 conflict-resolution|0|`:min`|procedural 1912–1917|

特别是 fired 本身 priority=0；它运行时才安排 priority=100/50/10 的 RHS 后续事件。不能把未来这些 RHS 的优先级倒推为 fired 的优先级，跨越已经更早处理的同刻事件。无候选的动态等待由 scheduling 1079–1151 和 875–935 处理：寻找同模型的下一非 maintenance 事件，并在其时刻以 `:min` 尝试匹配；不是每 50 ms 盲目重试。subset 的状态变更唤醒应保持单个 pending conflict event。

LOOK 的 next conflict:min 通常早于视觉选择锁 unlock:min 入队：前者由 fired 直接安排，后者直到 request50 callback 才安排。因此 conflict 先运行，选出的 MOVE selected:max 也可先于这次 unlock。FIND/普通 stuffing 的 unlock9 则在 conflict:min 前。不能把不同种类的 unlock 统一提升到 conflict 之前。

## 独立手算与控制测试预期

下面以 START 已处理、当前时间为 0、DAT=0.05、frame 正确可见、manual 全 free、静态唯一目标、无前置 THINK 为条件。它们是由规则推导的规格，不是抄历史 trace；真实初始化应由独立场景构造规则决定，不能为了得到 0.150 而强制清空 buffer。

|场景|预期控制路径/判定|
|---|---|
|A location 空、visual free|FIND selected0/fired.050；LOOK selected.050/fired.100；MOVE selected.100/fired及request.150。FIND内部搜索和写入均为同刻事件。|
|B location 已匹配、visual free|LOOK 的 U0 赢 FIND 的 U−1；LOOK fired.050；MOVE request.100。|
|C location 指向其他目标|LOOK 不匹配，先 FIND；成功搜索后与 A 相同。|
|D 相同内容 requested=true/false|B 的路径与时刻相同；仅 buffer provenance 不同。|
|E location 匹配但 visual busy、goal=S|LOOK 被挡，但 FIND 仍匹配；FIND fired.050，转S+1 后等待 visual free，不可跳过LOOK。无已知未来完成时是等待/未支持状态，不是完整成功。|
|F frame 不可见/不匹配|FIND/LOOK/MOVE 均被挡。仅 widget 不在当前 scene 与“frame不可见”不是同一个条件；对 stale chunk 依据 isa/value 和已选 bindings判断，不附加私设LHS。|
|G FIND 与 LOOK 同时匹配|U0 的 LOOK 胜。另造两个同U规则，后定义者胜；不可用队列入队先后冒充冲突策略。|
|H 同刻 location write 与 conflict|write priority10 在 conflict:min 前，匹配看新buffer；同priority事件才按入队序。|
|I LOOK 已选，等待中位置buffer替换或frame/query变化|不撤销，不重新选择，按原AT触发；screen-pos仍用选中时绑定chunk身份，空location RHS不还原被替换buffer。必须区分请求被发出与下游模块一定接受。|
|J 首次MOVE fired|只发一个 manual request、推进goal一次；等待期间状态事件不能重复dispatch；达到prefix边界后不得继续凭空生成后续click。|

人工指定时刻的 visual-free、buffer replacement 等只验证控制语义，应在输入和结果中标 synthetic-control；不能作为官方案例真实性证据。时间为0的规则或反复 FIND-LOCATION 可以产生无进展循环，需要事件数/仿真时限和最后状态快照。队列耗尽只表示无待处理事件，不能自动设置任务完成。

## 对本轮结果的可比较边界

历史 NP-B1 保存轨迹属于 2009 构建，不能用它反推 2014 的 requested 语义、初始 stuffing 或噪声参数。本地仓库可见历史最早为 2013 年导入，没有取得同一 2009 可执行源码配置。因此只能逐条件解释首条候选、首次触发和首次请求的差异，不能把前缀吻合当作总时长或 ACT-R 等价验证。

在静态 scene/manual-free 前缀中，未知视觉完成不会妨碍 MOVE 匹配。即使视觉已经完成，SUPPRESS 与 MOVE 同U，MOVE 在普通生成文件里后定义，仍由 MOVE 胜出；但这不证明后续脚本、display更新、prepare-click重叠或终止已建模。本轮保留原 baseline 与 motor subset 身份，新增控制模式需单独版本与 fingerprint；未覆盖事件、未解决依赖、任务完成状态和完整总时长为空的原因应进入结果，而不是依靠报告文字补充。

## 边界补充：请求发出不等于运动可立即执行

本补充对应 `source_rules/production_boundary_addendum.json`，不改写先前的 `production_rules.json` 和初版文档快照。

MOVE 选中以后、触发以前发生 `synthetic manual_busy`，仍不能撤销该 production。以本轮独立 matching-location 场景为例，LOOK 在 .050 秒触发、MOVE 在 .050 秒选中；人工 execution-busy 更新在 .075 秒发生。MOVE 仍应在 .100 秒触发并发出鼠标请求。此时不可以据此直接报告正常的光标输出和释放。

`motor.lisp:721–763` 的 `move-cursor` 在 729 调用 `check-jam`；`general-pm.lisp:304–311` 只检查 **preparation** 是否忙。在手已经位于鼠标、请求有效的前提下，execution 忙并不构成这个 jam。若 preparation 空闲，CogTool 的 `prepare-movement` 覆盖实现（`cogtool-actr.lisp:55–63`）可以开始准备；`preparation-complete`（101–111）把动作放进 execution queue。`general-pm.lisp:535–537` 仅在 execution 为 FREE 时取队首并 perform。既有动作 finish 后，CogTool 的 `finish-movement`（172–175）释放 execution 并调用 `maybe-execute-movement`。

本轮共享 motor 模块尚不支持这个执行队列，所以最小、明确的边界是：保留 production-fired、mouse_request 和首次请求时间，然后输出 `unsupported_manual_queue`；不调用正常空闲路径生成 motor events，输出与释放时间均为空。这里的 `unsupported` 是 Python 子集边界，不能写成“上游 execution-busy 会 jam”。同理，任意非空闲 manual 状态不属于本前缀的正常请求准入范围，不能用一条统一规则冒充完整上游 jam/排队实现。

人工 `manual_free` 也不天然等价于原版动作 finish：单独的 `change-state` 只更新状态，`maybe-execute-movement` 是另外的调用。未来若扩展队列，需要明确该人工事件是否代表 finish，并验证准备、排队、资源释放和唤醒的完整顺序。

## 边界补充：FIND 失败没有 priority=10 的 buffer write

`vision.lisp:2447–2449` 在 `find-location` callback 内立即把 `loc-failure` 设为真，再安排零延迟的 `find-loc-failure`。入口 2791–2795 和失败通知均未指定 priority，使用 scheduler 的默认值 **0**。`find-loc-failure`（2478–2479）只是空的 trace 函数。只有成功路径在 2439 安排 priority=10 的 location buffer write，并在 2441–2445 安排 priority=9 的 unlock。

因此，失败路径应由 priority=0 的搜索回调直接改变失败标志，随后执行 priority=0 的失败通知；不能把失败包装成 priority=10 的伪造 `visual_location_return`。请求自带的 priority=10 clear 已经清空 buffer，失败无需再次写入空 chunk。该区别在同刻并发事件中具有实际意义，不能只核对最终的空 buffer。

新增独立回归分别验证上述两个边界。失败路径测试在真实 `predict()` 调用中旁观调度回调的实际 priority，既检查状态前后，也检查失败通知；不单靠结果里声明的 priority 元数据。`control_matrix/attempt_03` 保存了 32 个测试全部通过的日志/XML、22 行矩阵及每行输入/输出；A–J 的前两次记录保持原样。这里仍没有原版运行或整任务准确性结论。

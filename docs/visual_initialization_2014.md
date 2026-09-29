# 固定 2014 版本的视觉初始化规格

实现目标为 `a91d91e8dcf95d762b6e08020029a36ea079bbba`。本地 Git 当前 HEAD 与该提交一致；既有版本审计仍未找到可信的 2009 CogTool 1.0.4 r3035 对应源码。下述状态是**明确选择默认配置后、按 2014 源码推导的初始化**，不是对旧缓存初态的恢复，也不是本次原版运行结果。

本轮证据位于 `reports/validation/20260926T062952Z_control_prefix/initialization_audit/`。`scripts/extract_control_scene.py` 的 `extract_scene()` 可读取固定电话模型，返回原始控件、辅助组位置、可见性和唯一最左候选；不调用预测引擎、不读取旧轨迹作为输入。

## 配置边界

选择普通 CogTool ACT-R 输出，`USE_EMMA=true`、`emitVirtualFrames=false`、默认研究参数、不加载可选运行时覆盖文件、无额外 `set-visloc-default`。这是一项显式配置，不等于观测到了用户旧机器上的偏好。

`ACTRPredictionAlgo.java:172` 将 `emitVirtualFrames` 初始化为 false。仅 `SNIFACTPredictionAlgo.java:1108-1123` 临时切为 true，并在 finally 恢复。普通 CogTool 不采用 CT-Explorer 的虚拟菜单页面和几何去重位移。原文件的 `renderWidget=false` 不会使普通模型输出省略该控件。

`CogToolPref.java:128-133` 的默认值为 alternative-parameters=false、视觉注意 85 ms、运动起动 50 ms、peck 系数 75 ms、production DAT 50 ms、USE_EMMA=true。实际旧偏好和实际新 Java 生成文件均未取得，机器证据中保留 null。

## 从空设备到首个位置缓冲区

| 阶段 | 状态及事件 | 固定源码 |
|---|---|---|
| 建立模型 | visual 和 visual-location 的 chunk 槽初始为 nil；goal-focus 设置 goal，状态为 1 | `framework/internal-structures.lisp:237-250`；`cogtool-actr.lisp:1167-1227` |
| 模块 reset | visual 的 modality/preparation/processor/execution 全 free；current-marker、currently-attended、失败标志均清空；EMMA eye-loc=(0,0) | `support/general-pm.lisp:323-337,833-837`；`vision.lisp:2542-2571`；资源 `emma.lisp:775-786` |
| 建立设备 | 新 cogtool-device 的 curframe=nil、visible-p=t；所有页面构造完成，但尚无当前页面 | `ACTRPredictionAlgo.java:480-503`；`cogtool-actr.lisp:819-835` |
| 运行前 | 安装设备、按保存手位决定 start-hand-at-mouse、鼠标置 (0,0)、调用 proc-display；由于 curframe=nil，视觉场景为空 | `cogtool-actr.lisp:891-900,1138-1154` |
| 开始页规则 | `set-start-frame-%c` 以显式 `:at 0.0` 触发，设置 destination-frame 并推进 goal；transition 设置 curframe 后调用 proc-display | `ACTRPredictionAlgo.java:1770-1783`；`cogtool-actr.lisp:264-282,1037-1049` |
| 场景进入 | build-vis-locs-for → frame-vis-locs → make-frame-vis-locs；process-display 将新位置放入 visicon，时间戳为当前 mp-time，最后调用 visicon-update | `cogtool-actr.lisp:891-950`；`vision.lisp:625-748,1094-1132` |
| 自动填充 | buffer 为空、device locks=0、未追踪对象时，按缺省位置规格筛选；t=0 调度 SET-BUFFER-CHUNK，priority=10、requested=nil；解锁事件 priority=9 | `vision.lisp:891-910,2646-2647` |

因此，正常状态不应直接在 run 前人为塞入一个位置。可以实现零时长开始页规则及填充事件，也可以将“开始页及填充完成后的状态”声明为独立入口，但必须说明省略的初始化阶段和它们均处于模型时刻 0。

## 场景、菜单和辅助组

`outputFrame` 遍历当前页控件；普通模式下没有“菜单未打开就隐藏 MenuItem”的条件。仅无标题、无辅助文本的 Noninteractive 控件有特定省略条件，NP-B1 不涉及。`make-frame-vis-locs` 同时产生控件和组的位置。可见性按整个 frame 的 visible-p、是否有当前 frame、vision-suppressed 判断；不可添加 GUI 经验推测的菜单可见性规则。

NP-B1 页面对象 6 有 10 个 widget，另有实际持久化的 SimpleWidgetGroup 12、36：

| 对象 | 成员或类型 | 原始 bounds（x,y,width,height） | 2014 visual-location（x,y） |
|---|---|---|---|
| 8 / w8 | ContextMenu，Widget 1 | 20,302,88,23 | 64,313 |
| 22 / w22 | MenuItem，Widget 5 | 64,345.5,119,15.75 | 123,352.5 |
| 42 / w42 | ContextMenu，Widget 1 [2] | 21,342,88,23 | 65,353 |
| 12 / g12 | 14,18,22,28 | 64,314,119,63 | 123,345 |
| 36 / g36 | 32,38,46,52 | 65,354,119,63 | 124,385 |

组边界取成员矩形 union（`Association.java:226-249,371-374`），组也经 `outputFrameElement` 输出为 cogtool-group（`ACTRPredictionAlgo.java:883-999`）。中心规则为 `x + floor(width/2)`、`y + floor(height/2)`（`cogtool-actr.lisp:934-946`），不是直接除以 2 得到浮点几何中心。

父菜单 childItems、子控件 parentGroup 均由原对象引用识别；它们不是新编造的“额外可视目标”。10 个控件及两个组的全部位置保存在 scene.json。

辅助组的 Java HashSet 遍历、Lisp hash 遍历、匿名 `GROUP [iN]` 生成名没有通过原程序执行确认，故 `order`、`original_generated_symbol` 为 null。所有首次入场对象的 creation_time_s=0 来自这次选定的初始化事件，不来自旧 trace。

## 自动填充的选择与来源标记

reset 将默认规格设为 `isa visual-location screen-x lowest :attended new`。筛选先遵循该规格，再在候选中取最新 visual timestamp，同时间戳候选按 symbol-name 排序后 random-item。

当前完整 12 个位置中，w8 的 screen-x=64 唯一最小，另一 ContextMenu 为 65，控件与组其余为 123 或 124。因此**所选 2014 配置下，正常初次填充可精确确定为 w8**，不需要还原随机数或未知组顺序。若未来场景有同 x 并列且实现未支持实际后续规则，应停在 unsupported，不能任意挑一个。

必须保持 `:process-cursor=nil`：否则 cursor 也可能进入场景并改变最左候选。固定 device-interface 参数默认如此，所选普通模型没有覆盖它。

| 缓冲区变化 | 内容 | requested 标记 | 视觉注意含义 |
|---|---|---|---|
| stuffing | 选出的 visual-location chunk | nil / unrequested | 不表示已看过或编码完成 |
| 显式 find-location 成功 | 满足请求的 location chunk | t | 也不表示 visual 对象已编码 |
| move-attention 后编码完成 | visual object 进入 visual buffer | 通常 requested=t | 这是另外的视觉模块完成过程 |

`vision.lisp:2433-2447` 的显式查找没有给 `schedule-set-buffer-chunk` 传 requested，因此取 `buffers.lisp:797` 默认 t。buffer 框架单独存储该标记（768-788）。位置查找本身的 module state 查询总是 free（`vision.lisp:2675-2684`），与 buffer 是否有内容、是否 requested 分开。

生成的 FIND、LOOK-AT、MOVE-MOUSE 模板没有 requested/unrequested 查询。相同目标位置仅来源标记不同，不能人为让这些规则走不同分支。标记仍需保留以支持审计和将来的显式 query。

## LOOK 请求与首个鼠标请求的依赖

`ScriptStepWriter.outputScriptStepState` 检查每个脚本步骤 focus 是否为新 widget；必要时在该步骤前插入 ACT-R LookAt，即使原示范和保存的 KLM 脚本没有显式 LookAt（`ACTRPredictionAlgo.java:1237-1257`）。这与高层自动 Think 是不同层级；不得将“示范无 LookAt”解释为没有视觉机制。

`generateLookAt` 的两个 LOOK-AT 变体要求目标 visual-location 匹配、visual state free、当前 frame 名及 visible 状态匹配。它们触发 `+visual isa move-attention screen-pos=<选中时绑定位置>`，保留 location buffer，推进 goal 到后续状态，并置 suppress-re-encoding=t（2504-2584）。

visual state 是模块 modality 状态；该值由 processor、preparation、execution 任一 busy 汇总而来（`general-pm.lisp:244-252,443-480`），不是 visual buffer 是否非空。

后续 `move-mouse-%c` 要求相同目标 location、manual preparation/execution/state 全 free、frame 匹配且 visible；**没有 visual buffer 内容或 visual state free 条件**（`ACTRPredictionAlgo.java:2095-2119`）。所以 LOOK 已发出请求并推进 goal 后，MOVE 不需要等视觉编码完成。两个流程允许重叠。

EMMA 请求实际会建立编码/眼动过程：move-attention 先设置 processor busy，initiate-eye-move 再设置 preparation busy 并排入眼动准备/编码事件（资源 `emma.lisp:257-310,395-415`）。不能把它改成瞬间完成，也不能统一补 150 ms。固定 CogTool 还覆盖 EMMA encoding-complete、去除眼动噪声（`cogtool-actr.lisp:133-154,1099-1108`）。

本轮前缀可以只接受 LOOK 请求，记录“编码完成未实现/未决”，并根据不依赖编码完成的 MOVE 条件继续到首次 manual 请求。随后应 partial、reported_task_time_s=null。不要把未计算的 completion timestamp 填成 0，也不要把首个 MOVE 时 visual busy 的所有细分标志假称为完整 EMMA 仿真的输出。

## 有效参数链

以下均指选定的无额外覆盖配置；实际旧参数不用于生成这些值。机器版见 parameter_chain.json。

| 项 | 底层/加载 | CogTool/生成模型覆盖 | 所选 profile 值与范围 |
|---|---|---|---|
| production DAT | procedural 默认 .05 | Java 默认 ACTR_DAT=50 ms；outputDesign 写入 :dat；define-cogtool-model 合并后 sgp | .05 s；set-start-frame 等有独立 :at=0，不统一加时 |
| visual-attention-latency | vision/EMMA 注册 .085 | Java VISUAL_ATTENTION 默认 85 ms，再经 sgp | .085 s 参数值；不能等同 EMMA 整个 LookAt 时长 |
| visual-encoding-factor/exponent | EMMA .010 / 1.0 | CogTool *default-global-parameters* 改为 .006 / .4 | .006 / .4，仅 EMMA 配置 |
| visual onset / finst | EMMA 注册 .5 s / 3 s / 4 个 | 未发现普通生成链覆盖 | .5 / 3 / 4 |
| auto-attend | 基础 vision slot=nil，基础模块注册参数=nil | EMMA 先 undefine 基础模块，再注册自己的参数表，刻意不注册 auto-attend | 继承 slot=nil；不是所选 EMMA 可调参数 |
| :vstu | 固定相关源中无定义 | 无 | not_defined_by_selected_source；不引入新版 ACT-R 参数 |
| process-cursor | device-interface 默认 nil | 普通链无覆盖 | false，不将鼠标作为视场对象 |
| mouse/eye 初态 | CogTool run cursor=(0,0)；EMMA reset eye=(0,0) | 无已知 profile 覆盖 | 仅2014所选profile；2009两者仍未验证 |
| frame/menu 可见性 | device visible-p=t；curframe=nil | 起始页规则设置frame；emitVirtualFrames=false | 整页可见，菜单项无闭菜单过滤 |
| randomization | :randomize-time 默认 nil | *cogtool-random-seed*=(1 0)，生成 design 写入 :seed；CogTool覆盖 add-gaussian-noise 为恒等 | 唯一最左选择不依赖随机支路 |

覆盖顺序必须按源码读：基础 ACT-R →（USE_EMMA 时）EMMA 替换视觉模块 → CogTool boilerplate 默认 → outputDesign 生成覆盖（含 DAT 等）→ define-cogtool-model 复制并合并默认、调用 sgp → 可选 `/tmp/act-r-kludge.lisp` → 生成 production 自身的 spp 参数 → 实际运行。

可选 kludge 文件可以做任意运行时改动（`cogtool-actr.lisp:1179`）；本 profile 明确不启用。不能将未获得的原版实际运行配置说成已验证。

## 可以执行的最小规格与未知项

可以严格实现：空缓冲区/全 free 的所选初态；零时长开始页规则；整页 10 控件及两个辅助组；t=0 的唯一最左 stuffing w8、requested=false、优先级 10/9；buffer 内容与 module 状态分离；显式查找的 requested=true；LOOK 请求后的 goal 推进；不依赖视觉编码完成的 MOVE 条件。

保持 unknown：2009 r3035 对应源码及初态；原版实际 Java 偏好与生成 Lisp；原版当前运行输出；组匿名编号和遍历次序；尚未实现的 EMMA 后续精确状态及完成事件。并列候选和超出模型边界的场景应显式不支持。

原版重跑值继续为 null。本审计未重试任何已失败运行环境，也未用历史 0.150 s 或缓存总时长构造输入。

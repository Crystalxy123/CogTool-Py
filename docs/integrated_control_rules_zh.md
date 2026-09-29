# 固定 2014 版本：NP-B1 后续控制与任务终止

本规格只依据固定提交 `a91d91e8dcf95d762b6e08020029a36ea079bbba` 的源码和官方 NP-B1 的对象引用。不是实际原版运行结果，也不是 2009 r3035 的行为证明。规则编号由 Java 模板静态展开推导；未声称获得原版前端本次生成的 Lisp。缓存 307 的时间和轨迹不参与此推导。

## 输入与展开边界

NP-B1 是 `Pop-Up / Look up one number`，TaskApplication 283、Demonstration 284、初态 285、Frame 6。唯一示范 287 使用 Transition 25，源 MenuItem 22、父 ContextMenu 8；ButtonAction 24 是左键单击，目标还是 Frame 6，delay 为 0。父菜单属性未保存时，固定源码默认右键打开。

`KLMCognitiveGenerator.java:1110–1188,1204–1216` 从父链生成 Point(8)、右键(8)、Think、Point(22)、示范左键(22)。这不是把旧缓存生成步骤作为输入。`ACTRPredictionAlgo.java:1235–1266` 在新焦点前插入 LookAt；Think 在下一个焦点前 flush，实际使用完整时长（1306–1312），注释中的减去 0.15 秒没有执行。`KLMCognitiveGenerator.java:624` 构造自动 Think，`ThinkScriptStep.java:117,199–205` 给出默认 1.2 秒；此值有独立源码来源。

## 正常包装器启动的实际视觉副作用

最终独立复核发现并修正了初版集成漏掉的启动 clear。这个发现来自以下同步调用链，不能用旧轨迹的首个时刻反推。

1. Java `ACTRPredictionAlgo.java:556–575` 依次写入 EMMA、包装器、design、script 模型定义，最后执行 `cogtool-run-model`。模型创建在 `framework/model.lisp:269–288` 先 reset 模块，再求值模型体；启动 run 不再次 reset 掉下面的 clear。
2. `define-design` 每次新建 cogtool-device（Java 497–499），其 `curframe=nil`（包装器 825）。设备初始 locks=0，reset 也置 0（`device-interface.lisp:239,282–286`）。`cogtool-run-model:1142–1152` 安装设备后、1155 的 run 之前，调用 `proc-display`。
3. `device-interface.lisp:188–196` 直接调用 `process-display`；`vision.lisp:641–646` 因 locks=0 不延期，而同步调用 `build-vis-locs-for`。包装器 891–896 对 `curframe=nil` 执行 `(clear vis-mod)` 并返回空列表。
4. `general-pm.lisp:839–842` 的 attention clear 调用基类，284–292 将 preparation 置 busy，并以默认 priority 0 排入 **0.050 秒**后的 `change-state(:last none,:prep free)`；还清理 feature memory/执行队列。EMMA 的 after 方法将 moving-attention 置 nil（369–370）。clear 不对 device 加锁；空 visicon 的 stuffing 也找不到对象，不加锁（`vision.lisp:891–910`）。
5. t=0 的 START 不要求 visual free，仍可设 Frame 并处理新 scene。stuffing priority10、unlock priority9 之后，location 即使已经是目标 W8，visual preparation 仍 busy，所以只能选择低 utility 的 FIND。已在启动时排入的 clear release 于 t=.050 先执行，同 priority 0 的 FIND firing 后执行；然后 LOOK 在 .050 选择/.100 firing，MOVE 在 .100 选择/.150 firing。这个顺序来自 guard、AT 与 FIFO，不是整体平移轨迹。

人工单目标 (1,0)、宽10 场景的独立算例：首 MOVE=.150；cursor feature preparation=.004，initiation=.050，Fitts 下限=.100，burst=.050；设备输出=.304，manual release/队列结束=.354，STOP=.150。旧 prefix 0.1 作为历史快照保持原结果和局限；新 integrated scope 0.2 才包含真实包装器启动事件。明确指定的 synthetic 初态代表初始化后的控制阶段，不重复插入该 clear。

## 生产规则状态机

以下 `F` 为 `01_PopUpStart`；`W8`、`W22` 分别是 `Widget 1 in 01_PopUpStart`、`Widget 5 in 01_PopUpStart`。编号前提是源码常量 `EMIT_KEEP_ALIVE=false`（152）。state/nameCounter 都从 1 开始（1208–1215），模板 `%S` 才推进静态 state（1582–1593），每次 emit 自增编号（1632）。除表中特别列出，utility 为初始 0、AT 为有效 `:dat`（此 profile 为 0.05 秒）。

| 规则名 | goal 前→后 | 其他 LHS 条件 | utility / AT | RHS 请求 |
|---|---|---|---|---|
| *suppress-re-encoding-1 | klm，任意 state，suppress=t→nil | visual state free；frame visible | 0 / 0 | visual clear |
| set-start-frame-2 | 1→2 | 无 | 0 / 0 | plist destination=F |
| find-3 | 2→3 | frame F visible | -1 / DAT | visual-location value=W8 |
| look-at-4 | 2→4 | location W8；visual state free；frame F visible | 0 / DAT | move-attention(绑定 location)，suppress=t |
| look-at-5 | 3→4 | 同上 | 0 / DAT | 同上 |
| find-location-6 | 4→4 | frame F visible | -1 / DAT | visual-location value=W8 |
| move-mouse-7 | 4→5 | location W8；manual preparation/execution/state 均 free；frame F visible | 0 / DAT | manual move-cursor(绑定 location) |
| prepare-click-8 | 5→6 | manual preparation free；frame name=F | 0 / DAT | manual prepare(style punch,hand right,finger index) |
| click-mouse-9 | 6→7 | manual execution free；frame name=F | 0 / DAT | manual click-mouse |
| THINK-10 | 7→8 | manual state free | 0 / 1.2 | 无模块请求；设置 duration 属性 |
| find-11 | 8→9 | frame F visible | -1 / DAT | visual-location value=W22 |
| look-at-12 | 8→10 | location W22；visual state free；frame F visible | 0 / DAT | move-attention(绑定 location)，suppress=t |
| look-at-13 | 9→10 | 同上 | 0 / DAT | 同上 |
| find-location-14 | 10→10 | frame F visible | -1 / DAT | visual-location value=W22 |
| move-mouse-15 | 10→11 | location W22；manual preparation/execution/state 均 free；frame F visible | 0 / DAT | manual move-cursor(绑定 location) |
| prepare-click-16 | 11→12 | manual preparation free；frame name=F | 0 / DAT | manual prepare(style punch,hand right,finger index) |
| click-mouse-17 | 12→13 | manual execution free；frame name=F | 0 / DAT | manual click-mouse |
| stop-18 | 13→isa stop | 无其他条件 | 0 / 0 | goal 请求 stop chunk |

模板证据：start/suppression/stop 1741–1799；click 1941–2037；Point 2075–2117；LookAt 2504–2585；Think 2597–2625。查找没有视觉 free 条件，Point 没有视觉 free 条件，prepare-click 没有 manual execution/state free 条件，click-mouse 没有 manual preparation/state free 条件，Think 没有视觉/帧条件，STOP 没有 manual/visual 条件。不得为“安全”补入源码不存在的 guard。`general-pm.lisp:244–252,443–450` 的 manual state free 表示 prep/proc/exec 都不 busy。

表中 click 的模板没有显式 `status visible`，但不能把其 `frame.name` 当作普通字符串比较：`cogtool-actr.lisp:747–765` 的 `frame-module-query` 在 name 分支先检查 `(visible-p OR *system-wait-blocks-only-vision*)`，而后者默认 nil（23）。因此所选有效 profile 中，prepare-click/click-mouse 的 name query 仍受可见性门控。若未来支持该全局参数设为 t，name 与显式 status 两种查询才会出现差异；此子集没有声称支持该变化。

规则只在冲突选择时匹配；已选规则在 AT 等待中不重新检查 LHS，绑定 location 身份保留。不能按观察到的某一次轨迹硬写顺序，也不能把 FIND→LOOK 永远连起来：匹配 location 时直接 LOOK 的 utility 0 胜过 FIND 的 -1。默认线性 conflict、ER=nil 的同 utility 分支，后定义规则优先；suppress 可能在前景动作等待期运行，不应手工安排固定清理时刻。

## 提前预备、队列与实际输出

`prepare-click` 可在 Point 的执行尚 busy 时选中，条件只检查 preparation free。执行 `prepare` 建立 punch，设置 `exec-immediate-p=nil`（`general-pm.lisp:548–551`），因此预备完成不会自动放入运动执行队列。

后续生成的请求是 **click-mouse，不是 execute**。`motor.lisp:797–800` 在右手位于鼠标时调用新的 punch；`general-pm.lisp:761–776` 的 defstyle 构造新 movement，其 exec-immediate 默认 t（603–604）。同一手指 punch 与上次预备 punch 的特征差为 0（`motor.lisp:493–496`），仍会安排 0 毫秒 preparation-complete。不能省去该事件后把前一对象直接 execute。

预备开始令 prep/proc busy、保存 last-prep，并安排 preparation-complete（CogTool 包装器 `cogtool-actr.lisp:55–69`）；完成先释放 prep，自动执行 movement 才入 FIFO，然后调用 maybe-execute（101–111）。只有 execution free 才从 FIFO pop 并开始运动（`general-pm.lisp:535–537`）。显式 execute 在 565–573：要求存在 last-prep 且 prep 不 busy，才入队；这条 API 不是 NP-B1 生成器的路径。

CogTool 将 motor-feature-prep-time 覆盖为 0.001 秒（包装器 569–573、1123），所以 cursor-ply→punch 的 style/hand/finger 三特征预备是 0.003 秒；随后同一 punch 是 0。该数值不可用底层 ACT-R 的 0.05 秒覆盖回来。普通 click 若遇 preparation busy，会触发原 check-jam（`general-pm.lisp:304–311`）；不可默默排成“准备好了再点”。

运动开始将 proc/exec busy；initiation-complete 在 initiation-time 后释放 proc（包装器 116–130、154–156），输出与最终释放分别排队。punch 的输出为 initiation+key-closure，释放为 initiation+2×burst（`motor.lisp:482–490`）；固定 profile 的后两项是 0.01/0.05 秒。普通指针输出为 initiation+Fitts，释放再加 burst（`motor.lisp:612–615`、`general-pm.lisp:699–701`）。所有这些 queue-command 默认 priority 0（`general-pm.lisp:871–908`）。

## 菜单和设备语义

Java 普通 ButtonPress 分支只读取 pressType，未按 Left/Right 区分生成的 motor 请求（1941–2037）。右键与最后左选都到右手食指 punch；包装器 OUTPUT-KEY 把鼠标键位转成 `device-handle-click`（229–242），`DEVICE-CLICK` 没有 button 参数（977–980）。因此“菜单打开”是上层生成步骤语义的注记，应在该步骤实际 DEVICE-CLICK 输出时确认；不能声称原设备后端独立实现了右键按钮协议。

普通固定 profile 的 `emitVirtualFrames=false`；菜单项已在同一 scene，并不在父点击时新增。不得为这个模型额外隐藏/显示菜单项、重建 visicon 或重置视觉 buffer。`*infer-transitions*` 默认 nil（248）；正常转换应依据预设 plist，不做点击几何猜测。

Transition 25 是 Frame 6 的 delay=0 自环：Java 1535–1559 不输出 destination-frame；运行时 1041–1049 也只对首次 frame 或不同 frame 执行 TRANSITION-TO/proc-display。因此最后左选之后没有额外 transition production、系统等待或 scene reset。可保留一个零时间的输入语义注记，但不能将其当作额外控制阶段。

## 终止与结果字段

STOP 的目标请求仅令 goal 变成 stop，不调用 break；不等点击输出，也不等 manual release。最后 click 的请求发出后即可选择零 AT STOP。

`scheduling.lisp:331–336` 的事件循环持续到事件队列为空、break 或时间上限；387 返回 `末事件时钟−run起点`。`run:524–559` 另发同刻的 run-terminated 维护事件。如果还存在未来事件而未用完时间，源码会 `run-full-time` 到 timeout（故不能将“没有可匹配生产规则”当作队列结束）。CogTool 使用 `(run *timeout*)` 的第一返回值（包装器 1155–1162），另印处理器 CPU 时间。Java 将 stdout 最后一行数字解析为 taskTime（`ACTRPredictionAlgo.java:286–306`；命令值 433–436；`Subprocess.java:477–479`）。默认 timeout 为 600 秒，来自 `CogToolPref.java:117`；这是上限，不是 NP-B1 固定结束时间。

结果应分别提供 `model_stop_time_s`、`last_device_output_time_s`、`last_manual_release_time_s`、`simulation_end_time_s`。只有明确 STOP 已发生、所支持模块的真实事件全部处理完、无失败/unsupported/limit，且结束原因为 `event_queue_exhausted_after_stop`，才能把 `reported_task_time_s` 设为源定义的队列结束时间。实际完成的时间戳可在不完整结果保留，但完整任务预测必须 null。眼动完成即使晚于编码/STOP 也可能仍在队列；不能只取最后 manual release 冒充 run 返回值。CPU/机器实耗独立记录。

## 仍未知或不在本子集的内容

- 2009 r3035 对应源码、默认值与当前 2014 的兼容性未知；原版本轮重跑值为 null。
- 无本次原 Java 前端生成的 Lisp。已取得带装载适配的独立 Lisp 后端运行与有效参数打印；共享 Python 转换/生成的限制仍存在，不能称为前端或完整流程通过。
- 普通菜单设备只有 generic click；本子集的 menu-open 标记是注明来源的语义层观测。
- 多层菜单、不同 frame 及带正 delay 转场、同父菜单重复选择、鼠标按钮独立设备状态、随机/学习/自定义 runtime kludge 不由本 NP-B1 子集推导支持。
- 捕获异常、time/event limit、不受支持的视觉路径都不能升级为完整任务结果。

## 0.3.0 的连续任务范围

同一静态页面、零延迟自环、各不相同父菜单的连续选择已开放。源码 isOpen:1023–1038 对另一父菜单返回 false；produceMenuSteps:1051–1053,1110–1188 和 produceItemSteps:1210–1216 产生第二套必要动作。TaskController 的既有规则编译循环连续推进 state/nameCounter，所有模块与时钟只创建一次，不在两个查询之间 reset。其余公式、参数、STOP 与尾事件规则不变。此范围由 NP-B2 首次 unsupported 后的源码核查和局部回归支持，并非以两个 NP-B1 时间相加得到。

## 0.4.0：有限键盘、手部、换页和响应等待（2026-09-26）

固定源码仍为 a91d91e8dcf95d762b6e08020029a36ea079bbba。默认引擎和
klm_baseline 不变；integrated_task 使用同一个生产调度器、视觉模块、
MotorModule 与毫秒时钟，未串接旧串行计算器。新输入须显式选择此范围。

普通键盘设备输入以 `keys` 与 `device: keyboard` 表示，有限规则只接受 a–z；
不是把焦点悄悄设到任意文本框。键盘配置通过不可变参数集的
`with_keyboard_defaults()` 显式启用。连词 get-spelling、同手执行门、
跨手准备门依据 ACTRPredictionAlgo.java 1640–1740、2197 等处；
具体按键手指/坐标、特征准备、peck/recoil、Homing 和执行 FIFO 复用
motor.lisp、device-interface.lisp 与 cogtool-actr.lisp 的规则。
只在共享模拟设备中输出事件，不向宿主发送任何输入。

跨页在触发动作的设备输出时提交（cogtool-actr.lisp 977–981、1037–1049），
保留鼠标、眼位、运动状态和复制到缓冲区的 visual-location。每帧单独建立
visicon，不合并页面；同坐标跨页时仍沿用 Java 的同位置 LookAt 抑制。
所有参与场景的 frame name、visual value 必须无歧义，否则返回 partial。
跨页时仍有被注视/正在移动注意力的对象，当前子集明确不支持动态 EMMA
再编码，返回 null；这不是宣称上游也不支持这种变化。

转移延迟是动作生产的 sideband 属性，自动 wait/transition 注释不产生
第二条 Wait 生产。设备输出后开始等待，隐藏 frame 查询状态但不清现有
visicon；等待完成恢复可见并 proc-display（1052–1081）。frame NAME 查询
也检查可见性（747–765）；已经选中的生产不会重新匹配，FIND 请求本身按
vision.lisp 2429–2449 搜索现存 visicon。等待可以与 Think 重叠，不能相加。
显式独立 wait、LookAt、命令文本、组合/功能键、非 ASCII、嵌套/hover/
双击/同父菜单重访仍不在已验证集成范围。

`Transition.delay_label` 保存系统响应的原标签，旧输入缺省 None 时序列化
不新增字段。正等待的 P-L writer 要求标签有明确来源；绝不猜标签。
STOP、最后设备输出、手部释放、眼动完成及队列返回分别记录。原10秒/
1000事件保护不变；超限返回 time_limit/event_limit 和 null，不能当完整任务。
独立 Java 默认600秒政策另存，未把不同上限静默抹平。

证据为 reports/validation/20260926T132706Z_task_extension。
合成规格仅共用高层人工输入，Java 构建原 Project/Design/Demonstration 后
重新生成；P-P、P-L、J-L不共用生产或耗时。比较器保留 TextActionSegment
到逐键的映射及所有注释，必须核查必要输出/换页/等待/结束事件；未打印的
proc-display与完整资源状态仍 unknown，不能据配对事件宣称整个模型等价。

## 0.5.0：Text、命令属性与键盘设备转移（2026-09-27）

本节取代 0.4.0 对命令文本和 ASCII 数字的范围限制；其余边界不变。
固定源码仍为上述 2014 commit。已有独立 Java 重新生成路径，故前文
“无本次原 Java 前端生成”的描述仅代表当时阶段，不代表当前证据。
本轮证据在 reports/validation/20260927T021507Z_command_device_extension。

Text 保留 `kind: text`，不是 Button 或 TextBox。KLMGenerator.java
1651–1655 对非交互 Text 的选择恢复 INITIAL 而不自动加 Think；仍保留
有依据的 Home、Point、Click，不设置文本框焦点或增加阅读耗时。视觉
对象由上游 ACTR 导出器的 cogtool-text 表示，几何和值保持原字段。

`is_command` 是 KeyAction 的建模标记，独立于 `modifiers`、整串
`key_text` 和逐物理键 `keys`。KLMGenerator.java 791–799 在 command
开头必要时插入一次 mental step；Home 仍按实际手部状态只插入一次。
不解释命令语法，不插入 Enter/Escape，不向宿主系统发送输入。
ACTRPredictionAlgo.java 的 WORD 模式只对连续字母生成 get-spelling；
数字打断单词段，但数字本身仍输出。ASCII 数字沿用固定键盘表和
MotorModule；键 5 的左手食指 peck-recoil 使用源表已舍入的 r=2.24、
theta=-1.11，不用新的几何公式替换。没有新增时间补偿或案例分支。

Frame 可拥有明确的 `devices`；InputDevice 转移使用 `source_type`、
`source_id`、`keys`、`key_text`、`is_command`、`modifiers`，不构造几何
目标。共享校验器按当前 Frame 和完整 KeyAction 元组匹配引用；
`key_text` 验证与 `keys` 一致。转换保存原图中未被示范走过的 DOWN×14
设备自环；DOWN 的原字符 U+E00D 可无损保留，但实际执行功能键仍返回
partial，不能把图边可保存当作引擎已支持该动作。

键盘提交使用 cogtool-actr.lisp 264–285、971–975 的 pending 规则：每条
实际按键 production 触发时加一，物理 OUTPUT-KEY 时减一；只有末键规则
提供 destination，且 pending 归零时才消费该 destination 并提交。不是
按整串长度预装计数，也不是识别特定命令文本。两条命令连续使用同一
Clock、资源、手位和视觉状态，不在中间 reset。继续处理 STOP 后的实际
尾事件。正系统响应沿用已有设备转移机制，本官方任务没有补造等待。

原任务首次点击的视觉 suppression clear 在两次换页前已经结束；换页时
没有 moving-attention 或 attended-object，故未进入尚不支持的动态视觉
再编码分支。未打印的上游资源状态和 current-marker 仍不声称已观测。

新增字段缺省时省略序列化，旧输入内容身份不变；真实启用的新字段参加
保存、重载及规范化内容哈希。参数仍通过不可变有效集合和覆盖接口管理；
键盘默认值显式启用，默认引擎仍是 klm_baseline。命令/设备输入必须显式
选择集成范围。组合修饰键、非 ASCII 输入、显式 LookAt、独立 Wait、
动态注意再编码以及一般应用命令解释仍未开放。

输入、生成 production/SPP、有序按键、pending 提交及最终边界均进入
比较；同时间未打印的跨模块顺序不补造。P-P/P-L/J-L 一致只表示声明
范围内对齐；参考仍为固定 Java 生成链加装载适配的上游后端，完整未经
修改 GUI 的 original_rerun_s 继续 null。

## 0.6.0：显式注视、DOWN 序列与参考运行政策（2026-09-27）

本节更新0.5对显式普通目标LookAt和DOWN实际执行的限制，其他未声明范围
保持。证据：reports/validation/20260927T041344Z_look_direction_extension。
未扩展Vim命令解释、其他功能键、复杂菜单或动态注意力再编码。

原 LookAtScriptStep 没有 duration。集成输入以 `{op: look_at, target: ...}`
表达，拒绝人为固定duration；klm_baseline依旧要求duration_s。固定
KLMCognitiveGenerator.java 1923–1983 对新几何位置保留LookAt，复制原
lastMental状态，再调用addMental；通常得到LookAt→Think。相同bounds再次
LookAt只调用addMental，若前一步已mental则生成警告且不再生成动作。此处
Widget.sameLocation比较bounds，不比较名称、ID或Frame。生成器的显式
lastLookedAt与writer插入自动注视的历史相互独立，不能混为一个缓存。

ACTRPredictionAlgo.java 1233–1268排除显式LookAt的自动重复插入；2504–2594
输出FIND、直接LOOK、FIND后LOOK三条规则，通过真实VisionModule运行。
Think的manual free门控不要求视觉完成，可以和编码/眼动重叠；LookAt
不增加鼠标移动、点击或阅读理解时间。suppression、buffer clear和事件
优先级复用原机制，不注入完成信号。主任务换页时注意力已按该规则清除，
不触发动态再编码；这不是宣称动态分支已实现。

原DOWN是一条KeyAction中的U+E00D标记：一个标记对应一个物理输出。
KeyboardUtil将其视为右手command-key，独立于KeyAction.isCommand=false。
重复相同command-key只在段首按需加Think，不按字符加Think或reset。
ACTRPredictionAlgo.encodeKey 1179–1183实际映射为 `slash`；固定后端
使用右手小指、peck-recoil、r=1、theta=1.57、输出坐标(10,5)，不是本机
键盘方向区。沿用已有MotorModule和准备记忆，无新方向键计时器。

源WORD正则只排除ASCII范围，因此两个以上U+E00D会成为一个spelling段；
不能使用原来的[a-z]简化来排除它。原文字保持不变，LispUtil.makeSymbol
加reader竖线，原Java US-ASCII导出将私用字符替换为问号；核心的运行规则
名称记录解码后的symbol名，P-L导出单独保留相同reader语法。这是生成
结构差异，不是按键改变；14个标记仍恰好14个press-key请求和14个输出。

原0.5的10秒/1000事件配置仍为legacy_bounded，默认序列化不增加字段，
旧内容身份保持。新增reference_2014固定max_time_s=600：CogToolPref117
存600000毫秒，经ACTRPredictionAlgo178–179除1000、wrapper调用run。
事件上限独立保留1000；实际PP30秒/JL及PL120秒墙钟保护属于验证launcher，
不进入模型时间公式。`control.run_policy`及模拟/事件上限进入保存、哈希
和执行记录。验证清单可为每个案例明确选policy_input，旧回归仍用旧配置。

scheduling.lisp 532–535在next-time严格大于上限才停止，所以等号事件及
同刻新事件仍执行。539–557在最后时刻等于上限时打印time limit reached，
Java completeWork对默认600秒亦标Model Timeout。本实现reference_2014
按此处理：等号事件处理完后time_limit，reported_task_time_s=null；若剩余
下个事件超限，则仅推进模拟时钟至上限，不提前执行该事件。已执行轨迹和
elapsed_simulation_s另存。原legacy政策维持先前的最后已处理事件时刻。
STOP不能提前结束尚有运动/视觉尾事件的任务。边界599/600/601秒由独立
Think小例测试，600秒测试并不消耗600秒墙钟时间。

# 固定 2014 CogTool EMMA：可执行视觉机制与边界

本页对应 `a91d91e8dcf95d762b6e08020029a36ea079bbba`（`1.3-2014-02-10`）和本轮共享时钟 `VisionModule`。它是静态、字符串值、可唯一绑定场景对象的一部分源码移植，不是完整 ACT-R/EMMA 等价实现，也没有原程序重新运行证据。2009 缓存轨迹和发表总时长不参与公式、参数或测试期望。

以下路径相对于 `reference/upstream-cogtool/`。简写 E 为 `java/edu/cmu/cs/hcii/cogtool/resources/emma.lisp`，C 为同目录 `cogtool-actr.lisp`，PM 为 `lisp/actr6/support/general-pm.lisp`，V 为 `lisp/actr6/core-modules/vision.lisp`。

## 有效代码与参数链

Java `model/ACTRPredictionAlgo.java:542–575` 先写入 EMMA 资源（556–558），再写入 CogTool 覆盖资源（560），然后设计和脚本。当前资源 E 与 `lisp/actr6/extras/emma/emma.lisp` 字节相同；证据仍优先引用真正复制的资源文件。

E 的视觉模块会替换原 vision 注册（818–821），其版本字符串为 `4.0a1-emma`（903）。E 注册默认编码因子 .010、指数 1.0（875–884），但 C 的实际默认参数表把它们覆写为 .006、.4（1118–1125）。不能使用未覆盖的 EMMA 默认值计算。

| Python 有效参数 | 本轮默认 | 有效来源与含义 |
|---|---:|---|
| `visual_encoding_factor_s` | .006 s | C:1118–1125，覆盖 E 的 .010 |
| `visual_encoding_exponent_per_deg` | .4 /deg | C:1118–1125，覆盖 E 的 1.0 |
| `visual_object_frequency` | .01 | E:526–536、895–899，字符串无频率注册时的默认 |
| `eye_feature_prep_s` | .050 s | PM:210–228，视觉继承 PM 特征准备时间 |
| `eye_initiation_s` | .050 s | PM:224–225，计入眼动执行公式 |
| `eye_saccade_rate_s_per_deg` | .002 s/deg | E:203–206、885–889 |
| `eye_saccade_base_s` | .020 s | E:203–206、890–894 |
| `pixels_per_inch` | 72 px/in | `framework/device-interface.lisp:154–155,222–224` |
| `viewing_distance_in` | 15 in | 同文件:225 |

这七个视觉参数只由 `with_vision_defaults()` 显式增加，持久化全元数据；旧基线和旧控制前缀参数集合不变。C 对 **motor** 特征准备时间 .001 的覆盖不会把眼动特征时间也改为 .001。正常 profile 采用源码 reset 注视点 `(0,0)`，与鼠标位置无关（E:775–783）。人工初眼仅供明确标记的 synthetic 模型。

**reset 后资源全 free 不是正常 wrapper 的运行起点。** `cogtool-run-model` 在 `run` 前先同步调用 `proc-display`（C:1152，run 在1155）；刚构建的 design 的 `curframe=NIL`（825）。`device-interface.lisp:188–196` 直接调用 V:624–646 的 `process-display`，此时 device locks=0、pending-procs=NIL（`device-interface.lisp:239–240`），于是 `build-vis-locs-for` 的空 frame 分支同步调用 `clear`（C:891–896）。PM:284–292 当场令视觉 preparation busy，并排 .050 s 后恢复的 priority 0 事件（`queue-command` 默认 priority0，PM:871–908）。这是真实模块事件，不是给每个动作增加 .050 s。

启动 clear 不生成眼动/编码、不移动眼位、不建立 frame/device lock。attention 主方法清 marker 与 attended（PM:839–849）；vision after 调 `remove-tracking`（V:2398–2408、2348–2353）并释放 execution；EMMA after 清 attention token（E:369–370）。随后初始空 `process-display` 的 bookkeeping 可能设置 scene-change，但 marker/attended 已 NIL，EMMA `update-attended-loc` 的两个触发条件均不成立（E:343–365），空 visicon 也不能 stuffing。

SET-START-FRAME 仍可在 t=0 触发并建立 frame（C:1037–1049）；stuffing 的条件不查询视觉资源 free（V:891–910），所以可在 t=0 以 priority10 写 location、priority9 解 device lock。可是 LOOK 的 `?visual> state free` 仍因 preparation busy 不满足，FIND 不含这个资源 guard，因此正常 source profile 首个目标 production 是 FIND，即便 stuff 的 location 正是目标。启动 clear 的 .050 priority0 事件先入队，同刻先于稍后排入的 FIND firing；之后正常 after-find LOOK 可以选中。

初次集成试跑遗漏了 wrapper 的启动 clear，得到 2.595 s 与 t=0 direct LOOK 路径。该输出只保留为修正前审计证据，不作为最终源码条件结果。旧 prefix-only 0.1 快照也保留原状并标注其初始化局限；synthetic controller 测试代表已指定的 post-START 状态，不追加正常 wrapper 的启动 clear。最终正常集成值必须由修正后的共享 controller 重新运行产生，不能在旧总时长上手工加 .050 s。

## 字符串对象、几何与频率

C:245 的 `*widget-value-is-title*` 默认 NIL。`frame-vis-loc-template`（C:934–949）把 `value` 设为控件全局名称，标题另存 `display-label`；坐标为 `x+floor(width/2), y+floor(height/2)`。因此频率不由标题长度、中文字符数、按钮类型或文本内容猜测。

E:526–536 对字符串按完整 `value` 查询 `freq-ht`，不存在则用默认频率；reset 清空该表（783）。当前普通 CogTool 写出路径没有注册频率表的调用。非字符串对象可以读取并累加 `vis-obj-freq` chunk 扩展，这一学习分支不在本轮实现内。Python 限制 `0 < f <= 1`，拒绝非字符串值，避免把零频率或大于一的值解释成有效编码。

普通 LOOK 请求不指定 scale。V:1383–1395 在容差内找特征，1407–1424 优先用绑定 location 的 canonical visicon entry，1793–1800 在候选中直接返回同一 entry；同坐标对象通过 `determine-focus-dmo`（1435–1445）匹配源 entry。`fill-default-vis-obj-slots`（3134–3145）复制 `value`。本模块要求 controller 提供仍存在且可唯一绑定的 canonical 对象，保留 `chunk_id` 与全局字符串值；不替代词组识别、多特征合并或随机 nearest-feature 分支。相邻 group 不会因为距离更近而抢走已绑定的 canonical 控件。

令像素位移长度为 `d`，PPI 为 `p`，观看距离为 `v` 英寸：

```
ecc_deg = degrees(atan((d / p) / v))
theta = 0                 if d == 0
        atan2(dy, dx)     otherwise
Tenc = factor * (-ln(f)) * exp(ecc_deg * exponent)
```

角度换算见 `device-interface.lisp:263–264`，零距离方向见 `motor.lisp:431–437`，编码见 E:504–509。不是 `atan(d/v)`，也不是把像素直接作为指数。

眼落点有两层舍入：先 `round(v*tan(radians(r_deg))*p)` 得到径向像素，再从当时眼位沿 theta 移动，并逐坐标 `round`（`device-interface.lisp:255–257`；`misc-utils.lisp:631–641`）。所以半像素目标不保证成为精确最终眼位。所有事件的相对秒延迟各自按 `ROUND(seconds/.001)` 转为毫秒，不在最后才对总和舍入；相对事件从当时整数毫秒计时点起算。Python 实数采用双精度；未声称复现任意 Lisp 实现的浮点位级舍入差异。

## 准备、执行、编码与残余编码

E:543–552 先用 r、theta 构建 saccade 并算准备时间，最后才赋 `trgt`。因此初次准备是 style+r+theta 三个非 NIL 特征，`3*.050=.150`，不是四个。后续同类 saccade 只比较 r 和 theta（E:223–227）：

```
n_changed = int(abs(r_new-r_old) >= 2 degrees)
          + int(abs(theta_new-theta_old) >= pi/4)
Tprep = n_changed * feature_prep
Texec = initiation + r_deg*saccade_rate + saccade_base
```

2° 和 pi/4 的**等号**属于变化；方向比较没有环绕修正（`motor.lisp:403–412`）。新 style/无上次准备由 PM:650–655、752–757 决定。眼动执行 .050 已含在 Texec，不能另排一次通用 motor initiation 再重复加时；E 的 `perform-movement(saccade)`（473–485）覆盖通用 PM 执行方法。

具体生命周期：

1. 接收 move-attention 时设唯一 token、当前绑定 location、处理器 busy，计算原始 Tenc（E:257–292）。本轮 API 不推进时钟。
2. `initiate-eye-move` 总是把准备设 busy，记录上次 saccade，先排准备完成；只有 **未舍入** `Tenc <= Tprep+Texec` 才同时排编码完成（E:395–416）。比较不能换成三个毫秒值的比较。
3. 准备完成把准备设 free；CogTool 覆盖方法检查当前 `last-prep`、加入执行队列并尝试执行（C:96–111）。视觉 saccade 不更新通用 initiation stamp，故正常眼动不能靠这段 stamp 判定提前释放处理器。
4. saccade 执行把执行设 busy，计算落点，排 `COMPLETE-EYE-MOVE`（E:473–485）。未另排 initiation-complete。
5. 编码完成按 **CogTool 覆盖方法** C:133–149：token=NIL，执行与处理器 free；准备不变。确认原对象仍在，再返回视觉对象；视觉 buffer 写入另排同刻 priority 10、requested=T（V:1360–1377）。
6. 眼动完成总是更新眼位。若 token 仍匹配，计算新偏心角和新的基准编码时间，并按下式继续准备/编码；最后执行释放并尝试执行队列（E:443–462；C:167–175）。

```
remaining = Tenc(new_eccentricity) * (1 - elapsed_since_shift_start / previous_raw_shift_duration)
```

这里 elapsed 使用实际毫秒事件时刻，分母保留上次未舍入识别时间。不是简单地从新 Tenc 中减去已经过时间。重新调用 initiate 时也仍会准备下一眼动；不能把第二次准备当作多余而丢弃。

**早编码不会自动取消眼动。** C:133–149 没有 `delete-event`，也不清 `last-prep`。准备事件和已安排的眼动完成仍可继续运行。编码时看到 `execution=free`，不等于该 request 已经没有未来眼动事件。资源快照、编码完成时刻和最终眼动完成时刻分别记录。

E:424–425 还有一个旧 `preparation-complete :after` 清句柄方法，但 C:96 先 `fmakunbound` 旧 generic，再重新 `defgeneric`（98）和定义主方法（101），故不能把该旧 after method 当成 CogTool 覆盖后的有效方法。对已执行句柄再 delete 不产生新的时钟推进；Python 的句柄保留了 executed 标记。

## clear、取消与未知边界

源码 `clear` 的主方法（PM:284–292）只在 preparation 不 busy 时执行：准备 busy，排**字面 .050 s**后准备 free、last-command none；清 last-prep、执行队列和 initiation stamp。attention clear（839–849）清 marker/attended，EMMA after（E:369–370）清 token，vision after（V:2398–2408）清 tracking/失败等标志。这里 `remove-tracking`（V:2348–2353）**无条件立即把 execution 设为 free**，即使从未 tracking；不能只删 tracking 字段而漏掉这个资源变化。processing 状态不因此释放。

clear 不取消已经安排的眼动完成或编码事件；本模块保持它们。视觉缓冲区的隐式清空是 `+visual` 请求的另一个 priority 10 动作，不等于模块 clear；controller 分开调度。模块 `clear(clear_buffer=False)` 默认不伪造这个缓冲区动作。

源码新 move-attention 在 execution busy 时警告并不接收；execution free 时可删除先前准备事件（E:259–280），但旧编码回调仍引用模块共享 shift-target。动态消失还会进入 fallback object lookup 或 `update-attended-loc`（E:343–365）。这些交叉请求/动态场景需要更多对象和队列语义，本轮不拼凑近似：

- 旧模块事件未结束或视觉仍 busy 时的新请求：明确 `unsupported`，不对重复目标偷偷去重。
- 对象在接收、编码或眼动回调处被发现消失：明确 `unsupported`，不制造替代对象、编码完成或资源释放。
- preparation busy 时 clear：明确边界，不冒充已经完整实现上游 jam 与 after-method 组合。
- 在 unsupported 边界取消本模块剩余排队事件，记录 `subset_boundary_cleanup; not an upstream cancellation rule`。这只是停止不再可解释的 Python 投影；不声称上游会同样取消。
- 非字符串/频率注册、随机时间、随机最近特征、动态 visicon 跟踪和多对象合并不在本轮范围。

其中「clear 在无编码事件的远目标眼动途中使 token=NIL」仍按已实现源码运行：眼睛完成落位，但没有残余编码，处理器可保留 busy；没有把空队列当成任务成功。

## 同刻顺序、随机性与终止

视觉内部 preparation/encoding/eye-complete/clear-complete 默认为 priority 0；视觉 buffer 写入 10；controller 的冲突解析 `:min`。同时间同优先级按插入顺序执行。initiate 先排 preparation 再排 encoding；在同一毫秒到期时准备先执行，随后编码可把刚 busy 的 execution 再设 free。Buffer-write 10 会先于仍待执行的 0 和 `:min` 事件执行。不同 priority 必须保留，不能把状态更新批量拍平成单一时间点。

E 使用 `rand-time`，但 `framework/random.lisp:382–387` 的 `:randomize-time` 默认 NIL，435–450 因而直接返回原值。CogTool 还把 `add-gaussian-noise` 替换为返回输入（C:1096–1104）；不能在这里另加眼动位置随机噪声。`*cogtool-random-seed*=(1 0)`（C:251）是版本身份，不是把关闭的随机时间重新启用。本模块范围没有随机选择分支。

模块 request 的 `encoding_completed` 只说明编码返回过；`completed` 还要求该 request 的所有计划事件均结束且未触及边界。`has_pending_events` 反映共享时钟中的真实句柄。模块不决定全任务时长；controller 另检查 STOP、必要设备输出、运动/视觉释放和可解释事件尾部。眼动尾事件不应被当作已取消，也不能因为视觉已编码就直接结束整个模拟。

## 独立验证

`tests/test_vision.py` 的期望来自以上公式与规则，不读取历史 trace。36 项覆盖：

- 初眼独立于鼠标；初眼已在目标或仍在原点。
- 正常 wrapper 空 frame 启动 clear 使 preparation busy50ms；其恢复先于后入队的同刻 priority0 事件，没有虚构眼动/编码。
- 原点同目标：编码 28 ms、fresh prep 150 ms、眼动完成 220 ms；早编码不撤销尾事件。
- 水平 1080 px/72 PPI/15 in 正好 45°：初眼完成 310 ms，重新计算残余编码在 338 ms 返回，第二次准备 360 ms、眼动完成 430 ms。
- 原始时间与逐事件毫秒舍入；同刻 preparation/encoding FIFO；buffer priority 10 高于 0 与 `:min`。
- 请求完成后相同目标 0 特征复用、方向变化、目标切换；clear 固定 50 ms并清准备复用。
- clear 在已编码眼动尾部立即释放 execution 但不取消尾事件、clear 在晚编码之前不伪造处理器释放。
- fractional 落点双层舍入、字符串长度不影响默认频率、绑定对象拷贝不被调用方改写。
- 共享时钟上的运动输出可与眼动交错；重入、消失、busy-clear 边界与真实句柄取消。
- 非法输入、缺有效参数、零时间同刻有限事件链。

运行：`.venv/bin/python -m pytest tests/test_vision.py -q`。初版源码规则与逐文件 SHA-256 保存在本轮 `source_rules/vision_rules.json`；启动路径与 remove-tracking 资源修正追加在 `vision_startup_clear_addendum.json`，不覆盖初版证据。它们不构成原版重跑或人类行为验证。

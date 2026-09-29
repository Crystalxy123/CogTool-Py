# 共享时钟取消与点击预备

实现目标固定为 CogTool `a91d91e8dcf95d762b6e08020029a36ea079bbba`（1.3-2014-02-10）。这里扩展共享组件供控制引擎使用；旧 `cogtool_motor_subset_experimental 0.1.0` 仍按串行请求与清空队列的适配器运行，不主动使用新增预备接口。

| 行为 | 上游依据（仓库相对路径） | Python对应 |
| --- | --- | --- |
| 删除尚未执行的事件，不执行其回调 | `lisp/actr6/framework/scheduling.lisp:1408–1425`，`delete-event` 实际从事件队列移除 | `Clock.schedule_event` 返回句柄；`Clock.cancel` 删除同一时钟的待执行项后恢复堆结构 |
| 优先级降序，同优先级按插入顺序；每个相对延迟独立取毫秒 | `scheduling.lisp:823–860,967–968`；`framework/misc-utils.lisp:349–351` | 保留原 `Clock.schedule`、四元组队列和取整算法；取消不推进模拟时钟 |
| 预备点击只要求 manual preparation free，后续点击要求 execution free | `java/edu/cmu/cs/hcii/cogtool/model/ACTRPredictionAlgo.java:2003–2047` | 控制器选择规则；共享模块的 `prepare(step)` 只支持 click/right_click 的右手食指 punch，不阻塞时钟 |
| prepare 设置 exec-immediate 为 nil，只准备特征 | `lisp/actr6/support/general-pm.lisp:548–551,650–655` | `prepare` 更新 last_prepared，复用原 `changed_features` 和特征耗时参数，记录 `exec_immediate=false` |
| 准备完成释放 preparation；仅在正 init-stamp 且已过 initiation-time 时释放 processor | `java/edu/cmu/cs/hcii/cogtool/resources/cogtool-actr.lisp:101–111` | `_init_stamp_s` 为模块内部字段；prepare 完成后按源条件另记 processor 释放。没有设备输出或菜单提交 |
| 后续 click-mouse 并非 execute；它调用 punch，再走 prepare-movement | `lisp/actr6/core-modules/motor.lisp:797–801`；`general-pm.lisp:769–777` | 调用原 `request(click/right_click)`；同样的 punch 特征差为零，但保留零时准备事件，之后使用原启动/输出/释放算法 |
| 菜单打开/点击信息在设备输出时改变 | 本地既有共享运动模块的 click_output 提交边界；上游设备输出入口 `cogtool-actr.lisp:185–193,224–242` | prepare、request 和 initiation 均不提交 open_menu；右键输出只提交一次 |

取消句柄公开 `when_ms/order/cancelled/executed`。取消已执行、已取消或其他时钟的句柄返回 false；无效句柄类型明确拒绝。模块负责把取消原因、目标与请求身份写入自己的轨迹，Clock 不给旧引擎追加结果字段。

`prepare` 返回与原 request 相同形式的完成句柄，完成仅表示特征准备结束。准备与原鼠标 execution 可以重叠。准备中的重复请求明确拒绝，防止旧回调错误释放新准备状态。通用 execute、运动执行队列及准备替换未实现；原 request 仍拒绝上一执行尚未完成的路径。上游通用队列规则见 `general-pm.lisp:535–573`，不能将当前受限支持扩称为完整移植。

独立测试 `tests/test_shared_module_extensions.py` 使用手推的小几何输入核对取消后的时钟、同刻排序、右键输出提交一次、预备与鼠标执行重叠、processor 条件释放及后续零时准备。它们检验实现规则，不是原版差分或预测准确率验证。

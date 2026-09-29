# 实现与兼容性

软件包版本 0.2.0；默认仍为 klm_baseline，另有显式选择的 motor 0.1.0、
prefix_only 0.1.0 和 integrated_task 0.6.0 实验范围。保存 schema 2，兼容
旧 schema 1；这是本项目 JSON，不是通用 CogTool 格式。固定上游 commit：
a91d91e8dcf95d762b6e08020029a36ea079bbba。详细规则见
[integrated_control_rules_zh.md](integrated_control_rules_zh.md)。

| 范围 | 当前实现及边界 | 证据范围 |
|---|---|---|
| klm_baseline | 默认串行求和；显式参数点击/键入/Home、LookAt、等待 | 四例回归，不等价 ACT-R |
| 不可变参数与内容身份 | 实际有效值、单位、来源、版本入哈希，保存重载 | API/JSON/CLI 及回归测试 |
| 集成视觉、眼动、规则和运动 | 共享 Clock、条件选择、资源、队列及真实尾事件 | 固定源码与独立 Java→移植 Lisp 必要事件对照 |
| Text | 独立类型，普通指向/点击，不自动当输入框或增加阅读 | T1 与 PR-CF-M |
| 命令键盘 | is_command 与 modifiers 分开；小写 ASCII 字母、数字和源定义 DOWN；逐键输出 | C1/C2/K1 与 PR-CF-M |
| InputDevice 转移 | Frame 所属 Keyboard，完整 KeyAction 匹配；末键且 pending 归零提交 | D1/D2 与 PR-CF-M |
| 页面与系统等待 | 已实现有限普通转移与原 delay；保留连续手/眼状态 | PR-CF-E 及响应合成条件 |
| 原工程读取 | 电话查询、普通控件及本轮键盘设备的有界对象转换 | 无通用 .cgt/XML 兼容声明 |
| 完整 ACT-R、应用命令解释、复杂设备和 GUI | 未实现 | 不声明替代原版 |

## 输入和状态边界

一个项目一个设计。几何单位 px，负坐标合法，宽高须正且有限；时间按字段
维度验证和转换。实际 Python 对象也完整校验；未知操作、错误类型、空键和
非法引用不得静默忽略。人工 Demonstration 与展开 ScriptStep 不混用。

默认基线键入依赖输入框焦点。集成全局键盘输入必须显式选择 keyboard 角色；
有设备转移时还须指定当前 Frame 的 device_id 和 transition。InputDevice
不含几何，不能换成上次点击 Widget。基线支持的按键集合较大，不代表集成
引擎也支持全部键：集成实际执行其他功能键、组合修饰键、非 ASCII 文本、独立
Wait 和子控件注视等组合仍拒绝或返回 partial，不回退串行基线。

DOWN 原字符 U+E00D 在原动作和设备边上无损保存，实际执行按固定导出器映射到
后端 slash，不能当作真实箭头区运动。显式普通目标 LookAt 不指定 duration，
由真实 VisionModule 和源 KLM 自动 Think 规则处理；基线 LookAt 仍需固定时长。
按键只模拟模型事件，不执行 Shell/Vim 命令，不模拟真实编辑内容/光标。
新字段缺省省略，旧输入内容哈希保持；启用字段完整参与身份及保存重载。

跨页时若仍有 attended/moving-attention 对象，需要的动态视觉重编码分支
尚未开放。STOP 不等于队列结束；不完整运行的完整预测为 null。明确的
超时/事件数限制和未支持状态不会被改成 complete。

## 参考和测试边界

本轮使用固定 2014 原 Java 读取/重新生成/导出，再交给有装载兼容补丁的
上游 Lisp 后端；独立于 Python 转换、步骤生成、writer 和预测。P-L 则用于
隔离 Python 生成/writer 与运行机制。三路径对照只声明核查字段、有序规则、
必要事件和任务边界通过，不以相同总时间代替这些核查。

2009 缓存是 archived_reference。未经修改的完整 GUI 重跑值
original_rerun_s 继续 null；本轮 J-L 保存为 java_generated_ported_reference_s。
未打印的资源状态、同步调用、同刻跨模块顺序保留 unknown。旧本地三个
差分测试缺少对应真实证据，仍是原有 skip；不能用新增官方案例代替它们。
统计区分完整官方任务、合成条件、单元测试和重复次数。

## 平台和分发

实际环境为本机 macOS arm64 / Python 3.11；Windows/Linux 未运行。产品
只需 Python 标准库；Java/SBCL 仅参考验证使用。没有公开发布或自动下载，
上游许可、参考环境原补丁、原工程与历史报告保留。

运行政策另存：旧 legacy_bounded 默认10秒/1000事件保持；reference_2014 固定600模拟秒，
保留1000事件及外层墙钟保护。恰好上限的所有同刻事件仍处理，最终标time_limit/null。
保护上限不是任务耗时；elapsed_simulation_s 单列。详见集成规则0.6章节与本轮runtime_policy证据。

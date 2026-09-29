本表按冻结 integrated_task 0.6.0 和当前输入校验整理。发行包0.2.1rc1的封装身份不改变认知规则版本。默认仍是klm_baseline；CLI沿用输入中明确保存的选择。标为“有界参考检查”不等于完整CogTool或真人准确性验证。

| 能力 | 实现范围 | 独立证据与边界 |
|---|---|---|
| 模型读写与校验 | 自有JSON；schema1读取、schema2完整保存；真实Python对象校验 | 输入/参数hash、CLI/API、覆盖与重载回归；不是通用.cgt导入 |
| 参数与身份 | 不可变有效参数；覆盖需来源；保存value/unit/source/kind/scope/default_version | 参数内容与代码/运行身份分开；无隐式调参 |
| 串行基线 | 有限Think、Point、Click、Keys、Home、给定时长LookAt、Wait及显式转移 | 4个自建本地案例；不是ACT-R资源重叠模型 |
| 运动子集 | 共享时钟上的准备、启动、输出、释放与受限特征复用 | 固定motor源码手算；实验子集版本0.1.0 |
| 控制前缀 | 条件匹配、选择/触发与第一鼠标请求边界 | prefix_only0.1.0；partial不显示完整预测 |
| 集成控制 | 有限Java模板、共享Clock、同刻优先级、尾事件和STOP | integrated_task0.6.0；5个官方完整任务及必要合成条件 |
| 鼠标和Text | 已知目标的矩形几何、普通定位/左键点击，Text保留独立类型 | NP与代码折叠任务；无自动阅读时间 |
| 上下文菜单 | 单层右键开启和左键选择；同页零延迟不同父菜单的有限连续路径 | NP-B1/NP-B2；层级/同父重复不支持 |
| 键盘与设备转移 | 小写ASCII字母/数字、固定DOWN；Frame所属Keyboard；command与modifiers分开 | 逐键输出、spelling、pending归零与末键转移；不解释真实应用命令 |
| 显式LookAt | 普通widget，无duration；源KLM自动Think/同bounds规则与有界EMMA | PR-CF-K、L1/L2/L3；非完整视觉搜索或任意重编码 |
| 页面与响应 | 已定义普通转移、零/非零response，保留连续鼠标/手/眼状态 | PR-CF-E及响应条件；活动注意力换页为明确边界 |
| 输出与批量复跑 | JSON、events.csv、steps.csv；安装后单例与manifest重算 | 核心无第三方运行依赖；R1与新R2分别报告 |

集成未支持：UP和其它未验证方向/功能键、修饰组合、IME、层级菜单、双击、拖放、通用视觉搜索、活动注意力跨页重编码、完整ACT-R/EMMA、GUI和通用CogTool格式导入。具体拒绝/partial条件见 [LIMITATIONS.md](LIMITATIONS.md)。

参数默认组分别保留 `cogtool-py-defaults-v1`、`cogtool-a91d91e-motor-v1`、`cogtool-a91d91e-keyboard-v1`、`cogtool-a91d91e-control-v1`、`cogtool-a91d91e-vision-v1`。模型提供的操作时长属于 `modeler-supplied-v1`。运行政策reference_2014的版本为1，保存schema为2；这些值不能用发行版本替代。实际身份由 `info --json` 和结果记录给出。

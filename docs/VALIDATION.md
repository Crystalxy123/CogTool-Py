验证结论按输入、步骤、已观测事件和结束边界分层。相同总时间不证明完整认知架构等价，也不证明预测真实人的速度准确。

冻结计算范围为 integrated_task 0.6.0。发行候选版本0.2.1rc1、默认klm_baseline 0.2.0、输入schema2与reference_2014政策v1各有独立身份；不因打包而统一版本号。固定来源为CogTool tag `1.3-2014-02-10`、commit `a91d91e8dcf95d762b6e08020029a36ea079bbba`。

| 官方完整任务 | 任务族与选择器 | 开发角色 |
|---|---|---|
| NP-B1 | 电话查询，Pop-Up / Look up one number | 早期集成机制开发；后补独立Java生成链，本轮回归 |
| NP-B2 | 电话查询，Pop-Up / Look up two numbers | 旧范围拒绝后开发连续不同菜单；本轮回归 |
| PR-CF-E | 代码折叠，PTP-Eclipse / Code folding with mouse | 普通跨页机制开发；本轮回归 |
| PR-CF-M | 代码折叠，Command Line / Code folding with mouse | Text、command与键盘设备转移开发；本轮回归 |
| PR-CF-K | 代码折叠，Command Line / Code folding with keyboard | 显式LookAt与DOWN扩展开发；本轮回归 |

这些官方任务曾参与开发，不能统称为五个未见过的独立预测检验。另有27个合成条件（18个原条件、7个LookAt/DOWN机制条件、2个冻结后派生条件）和4个本地串行基线。合成条件不是27名参与者、27次真人实验或27项独立准确率研究。各条目的来源、开发角色、输入/参数hash、运行政策和比较范围由 `LOCAL_ONLY/benchmarks/manifest.json` 记录。

参考路径有三条：P-P是Python生成与计算；P-L是Python生成/导出加装载适配后的上游Lisp后端；J-L是固定2014原Java读取原工程、重新生成步骤并导出，再交同一适配后端。J-L没有用缓存Script替代新生成，但它也不是未经修改的完整CogTool GUI运行；`original_rerun_s`继续为null。2009工程内的缓存另列archived_reference，版本环境未知项不会由2014结果补写。

`pass_bounded_observable_scope`表示明确列出的动作、生成规则、可匹配事件和结束边界通过。底层比较器的`overall=not_comparable`或`comparison_status=not_comparable`仍保留：未打印的完整资源状态、同步调用和跨模块同刻顺序不足以作总体等价判断。未匹配原始行、模型结构差异和未观测字段不删除、不填成free；不能将有界通过改写成所有CogTool行为兼容。

本次安装验收区分两种证据：

| 标签 | 本轮实际工作 | 可以支持的结论 |
|---|---|---|
| R1 | 新安装包从JSON重新计算，与带来源/hash的冻结记录比较 | 发行包行为回归；不是新的原版重跑 |
| R2 | 专用参考环境重新执行Java生成与Lisp，再与新安装包结果比较 | 本轮新的独立前端/参考后端对照；仍限有界可观测范围 |

R2是否执行、执行了哪些案例以及失败/阻塞，必须读取本次报告的`fresh_reference_recheck_status`与逐案记录。不能用旧J-L缓存填成R2成功。本次安装测试只证明同机不同虚拟环境的隔离，不是第三方独立复现或跨平台验证。

修改封装之前，本轮已保存36个输入重新计算与旧结果除程序墙钟外全字段一致的记录，并重跑得到706通过、3个原有跳过。706也是上一轮的测试数，不能当作本候选新增入口和干净环境的最终统计；本次最终统计从实际日志生成。三个跳过项仍对应single_click、text_entry、two_page_wait缺少其自身真实原版证据，不会由其它官方案例补齐。

发行验收应同时检查wheel安装与sdist重建安装、加载模块位置、无开发目录回引、API/CLI、36项重新计算、非法输入/超时/partial、中文空格路径、参数覆盖保存重载，以及5个官方任务的三次独立进程和A→B→A。比较完整计算字段和关键事件，只有明确列出的发行元数据与墙钟差异可以排除。运行命令见 [QUICKSTART_zh.md](QUICKSTART_zh.md)；本次是否通过以交付的REPORT、COMMANDS和各层状态为准，本文不预先宣称未完成的验收成功。

# 参数与公开输入接口迁移（0.2.0）

公开 predict、generate、保存及内容哈希均校验真实 Project 对象。校验是独立的结构、引用和示范状态检查，不调用步骤生成器，也不先序列化“清洗”对象。DemonstrationStep 是用户示范；ScriptStep 是生成结果，不能作为示范输入。未知动作、快捷键、空按键、无效初态、非法单位与非有限数值都会产生带字段上下文的 ModelError。

ParameterSet.entries 是对调用者映射复制后的只读映射，Parameter 也是冻结对象，全局 DEFAULTS 同样只读。请通过以下方式建立覆盖：

    from dataclasses import replace
    from cogtool_py.io import load_project, save_project

    project = load_project("examples/single_click.json")
    updated = replace(
        project,
        parameters=project.parameters.override(
            "think_s", 2.4, source="Explicit modeling assumption for this task"
        ),
    )
    save_project(updated, "updated.json")

这只是覆盖接口示例，不是为了匹配论文而调参。原项目、其他项目和全局默认值不变。单位按维度严格检查：时间仅 s，像素密度 px/in，视距 in；本版不自动换算 ms，必须由调用者明确转换并注明来源。合法负坐标允许，尺寸必须大于零。

schema_version=1 的旧三字段参数输入仍可读取，缺省参数按已标识的 defaults-v1 填入。也接受完整参数元数据的 v1 组合，以兼容 ParameterSet.input_dict() 的既有调用。内存模型规范化为版本 2，保存输出版本 2，完整记录九项实际参数的 value、unit、source、kind、scope、overridable、default_version。

内容 SHA-256 基于规范化任务、初态、界面、有效参数和来源信息，字典顺序、时间和保存目录不影响它。修改有效值或来源会改变内容身份。实现源文件哈希、软件版本和引擎版本另存 implementation，execution_fingerprint 绑定内容、任务和实现身份；不将这些运行代码信息混入模型内容哈希。

旧程序曾在保存时丢弃的内存参数修改无法从旧 JSON 恢复。本版只恢复文件中实际存在的值，不声称补回丢失信息；需用原始实验配置或当时完整结果参数核对后重新明确覆盖。

原有诊断中的直接字典改写路径已被禁止。因此两项参数故障测试保留名称与原失败证据，改为“直接改写被拒绝＋合法覆盖改变结果和哈希＋保存重载完整一致”。错误单位测试同时检查直接改写拒绝、覆盖拒绝与构造拒绝。负时长断言改为检查更早的 duration_s 错误位置。保存版本断言 1→2、未知版本断言 2→3 都对应明确的格式契约变化。转换等待的旧测试原先先构造引用未定义转换的中间对象再补定义，现调整为先建立完整输入，保留原动作、计时和2.05秒断言；没有删除测试、使用 skip/xfail 或放宽时间容差。

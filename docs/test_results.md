# 本轮实际测试记录

执行环境：macOS 15.6 arm64、Python 3.11.15、pytest 8.4.2。没有跨平台测试声明。依赖固定在 requirements-dev.txt；软件版本为 0.1.0。

## 总结果

实际执行 python scripts/run_validation.py，内部执行完整 pytest、4 个案例的 validate/predict、版本入口与保存重载命令。所有命令返回 0。

**214 passed，3 skipped，0 failed**（pytest 用时 0.64 s）。计时来自该次日志，仅表示软件测试运行耗时，不是人的任务时间或性能提升证据。

| 类别 | 测试 | 本轮结果 | 证据来源 |
|---|---|---|---|
| A 独立公式/规则/校验/证据机制 | test_calculation、test_generation、test_validation、test_comparison | 189 passed | 手算角度/截弦/Fitts、明确源规则、人工合成输入；不使用原版输出 |
| B 软件集成与回归 | test_integration | 25 passed | Python 自身 JSON→校验→生成→计算→导出→重载、CLI 与极端输入 |
| C 原版差分 | differential/test_original_cases | 3 skipped | 缺真实原版 single_click/text_entry/two_page_wait 输出；未执行 |

真实日志：

- validation/python/pytest.stdout.txt、pytest.stderr.txt、pytest.xml
- validation/python/run_manifest.json：实际命令、目录、返回码、输出 SHA-256、环境与时间
- validation/python/installed_packages.txt：实际安装依赖
- validation/python/wheel_install.json：本地 wheel 在全新环境的独立安装/运行检查
- validation/original/attempts/manifest.json 及分项 stdout/stderr：原版实际失败证据

## 案例结果

下表全部为 Python klm_baseline 的结果，绝非原版参考输出。示例 click/key/homing 时长为明确软件测试假设，不能用于声称人体表现或原版预测一致。

| 案例 | 预测秒数 | 主要生成操作 |
|---|---:|---|
| single_click | 1.628814409 | Think → Point → Click |
| text_entry | 2.428091697 | Think → Point → Click → Home → Key(h) → Key(i) |
| two_page_wait | 3.986109841 | Think → Point → Click → Wait(0.75) → Transition → Think → Point → Click |

完整参数、公式组成量、步骤来源、输入哈希与事件时刻保存在 validation/python/各案例/result.json，CSV 分别保留步骤和事件。outputs/ 下还保留交互运行案例。每个 result 都明确 original_comparison=unverified、differential_tests=not_executed。

## 已修复并保留的回归

- 超长 JSON 整数曾抛未包装的 ValueError；现在统一包装为带文件上下文的 ModelError，CLI 返回 2，且不输出部分预测。
- 初次并行开发的四个测试断言使用了旧字段名 effective_width_px；按实际公开输出字段 approach_width_px 对齐后通过。数值公式预期未调整，未放宽容差。
- 非有限值、负时长、非法尺寸、布尔冒充数值、未知操作、无焦点输入、缺控件/无效转换、未知参数/单位/引擎均有拒绝测试；模型文本保持惰性，不执行 Python。

未收集覆盖率，没有性能对比或实验数据，也不把导入器的合成证据当作原版成功运行。

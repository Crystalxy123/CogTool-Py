# CogTool-Py 来源、版权和许可声明

CogTool-Py 是本工作区的独立研究原型名称，不是官方 CogTool 版本，也不表示 Carnegie Mellon University 或原作者背书。

本项目包含依据 CogTool 公开源代码改写的有界规则，以及新增的 Python 数据模型、串行基线、文件处理、命令行和验证代码。新增及改写日期：2026-09-24。移植只覆盖文档中列出的功能，不是完整 CogTool 或 ACT-R 实现。新文件的来源与修改性质见文件头及 `docs/source_audit.md`。

## CogTool 上游

CogTool 1.3, Copyright (c) 2005–2013 Carnegie Mellon University.

Source: <https://github.com/cogtool/cogtool>，tag `1.3-2014-02-10`，commit `a91d91e8dcf95d762b6e08020029a36ea079bbba`。

上游 Java 源码声明采用 GNU Lesser General Public License version 2.1，或由接收者选择更新版本。本项目代码同样以 **LGPL-2.1-or-later** 提供；根 `LICENSE` 是上游 `LICENSE.txt` 的完整未修改副本。

This software is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Lesser General Public License for more details.

## ACT-R 与其他上游组件

本项目的运动公式与来源核查涉及上游随附的 ACT-R 源码。`lisp/actr6/core-modules/motor.lisp` 原声明：Copyright (c) 1998–2010 Mike Byrne/Dan Bothell；GNU LGPL（对应完整文本从参考树 `lisp/actr6/LGPL.txt` 原样保存在 `LICENSES/ACT-R-LGPL-2.1.txt`）。Java 文件头还保留 ACT-R 6.0 的 Copyright (c) 1998–2007 Dan Bothell, Mike Byrne, Christian Lebiere & John R Anderson。

参考树含有另行许可的历史组件：Eclipse SWT/Draw2D（EPL 1.0）、CLISP（GPL，见各 CLISP 目录 COPYRIGHT）、Apache Commons-Lang、jopt-simple（原文件内许可）、Mozilla XULRunner（MPL 1.1）以及 Sun JRE（见 `jre/LICENSE` 和第三方声明）。这些条目是已读上游版权头及随附文件的记录，不代表对整棵参考树做完逐文件许可证审计。

Python 的正常计算不依赖或调用上述 Java/Lisp 组件，发行包不包含 `reference/`、用户原有仓库、安装包、论文或图片。Python 开发/测试依赖按项目依赖配置声明，保留其各自许可证。若未来添加可选 GUI 或把参考组件打包分发，需另行核查和补充相应许可材料。

## 文档和自建材料

官方文档来源：<https://github.com/cogtool/documentation>，commit `1f5fe10e2bebfb7544aa85a6db2c10078df9f9d3`。参考树中的文档、示例、图片保留原状；本项目新增说明与自建 JSON 例子不冒充官方文档或官方验证样例。未知的单独文档/素材分发许可，列为公开发布前核查项。

本轮没有向任何公开服务发布代码、论文、截图或本地数据。

2026-09-26 新增的 `cogtool_py/motor_subset.py` 按上述固定版本的 ACT-R `motor.lisp`、`general-pm.lisp`、调度框架及 CogTool `cogtool-actr.lisp` 改写有限运动规则，沿用 LGPL-2.1-or-later，保留 ACT-R 作者及 CMU 来源。它是新写的 Python 运动生命周期子集，不包含上游 Lisp 二进制，也不表示完整 ACT-R 移植。逐规则依据见 `docs/mechanism_evidence_zh.md`。

2026-09-26 新增的 `control_prefix.py`、`control_models.py` 与共享事件时钟，按同一固定版本的 CogTool Java production 模板和 ACT-R procedural、vision、buffers、production-parsing-support、scheduling 源码改写受限的初始化与规则控制流程。procedural 与 scheduling 的原声明为 Copyright (c) 2004 Dan Bothell；视觉和运动相关源码保留其 ACT-R 作者声明。改写沿用 LGPL-2.1-or-later；完整上游许可见上述 LICENSES 文件，逐规则证据见 `docs/control_prefix_procedural_zh.md`。本次未移植完整视觉编码、通用 production 编译器或完整认知架构。

2026-09-26 后续集成新增 `vision.py`、`task_control.py`，继续改写上述固定版本的有限视觉与 production 规则。实际装载的 `java/edu/cmu/cs/hcii/cogtool/resources/emma.lisp` 文件头声明：Copyright (c) 2000–2003 Rice University，Mike Byrne；EMMA package is public domain software。Python 视觉实现也包含受 LGPL 约束的 ACT-R general-pm/vision/device-interface 与 CogTool 覆盖逻辑的改写，项目整体继续采用 LGPL-2.1-or-later，保留各来源身份。没有移植完整 EMMA、通用视觉搜索、学习或完整 ACT-R；逐规则来源见 `docs/vision_mechanism_zh.md` 和 `docs/integrated_control_rules_zh.md`。

本轮参考验证入口 `scripts/run_ported_reference.py` 在独立报告副本中运行固定版本 ACT-R、EMMA 与 CogTool Lisp 源码。原始版权与许可头全部保留；只有装载器的 SBCL 兼容补丁，补丁和逐文件身份随报告保存。Python 产品不依赖 Lisp。模板转写沿用上游 CogTool 的 LGPL-2.1-or-later 许可，参考结果明确标为 ported_reference_backend，并披露共享输入生成。

2026-09-27 发行候选补充（0.2.1rc1；保留以上历史声明）：本轮新增/修改仅涉及发行配置、安装资源定位、公开运行/身份/示例/基准入口、文档和验收组织。认知规则、公式、默认参数与事件语义对应冻结的集成范围0.6.0；若发现必要计算补丁，必须单列记录，不能视为普通打包。新增包装代码与说明继续按本项目LGPL-2.1-or-later声明处理，没有改为MIT，没有新增未经确认的作者、软件DOI或发布地址。

本地资料分发边界：`reference/upstream-documentation/README.txt`说明CogTool软件采用LGPL，但当前本地未发现该文档树中覆盖所有原工程、截图、论文与附件的单独许可证文本。电话查询和编程任务的README提供提交人与文献来源，不足以在本审计中认定每项素材均已获单独再分发授权。因此原.cgt、其转换JSON、衍生trace和相关材料标为LOCAL_ONLY并与核心安装包/自建示例隔离；这是一项尚待明确的资料范围，不是将其声明为无许可，也不是宣称下载或转换自动产生新的授权。

核心wheel和对应sdist应保留本NOTICE、LICENSE及LICENSES内的许可文本；自建最小JSON示例注明其建模假设，不冒充官方数据。专用Java/Lisp参考工具及兼容补丁另存，保留原文件版权头、来源commit和补丁；普通Python导入/预测不会启动这些工具。构建/测试wheelhouse中的第三方包维持其原始license与元数据，不因与本候选同目录就改用本项目许可。没有把原工程、论文全文、图片、字体、jar/native或整个第三方树作为核心运行资源。

该声明是依据本地文件的来源与范围记录，技术安装成功不等于所有材料可公开分发。候选材料清单、逐项hash和待核查项见本轮distribution_audit；本次仍未公开发布。

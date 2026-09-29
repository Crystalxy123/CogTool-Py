# CogTool Mac 桌面版

这是当前 CogTool-Py 0.2.1rc1 的本地桌面包装：原生 macOS 窗口负责选择模型、任务和查看结果，内置 Python 引擎完成计算。无需另装 Python、Java 或 Lisp，也无需联网。

## 安装和使用

适用于 **Apple Silicon（M 系列）Mac、macOS 15.0 及以上**。本次实际构建与验收环境是 macOS 15.6 arm64；其他系统版本和 Intel Mac 未验证。

1. 打开 `CogTool-0.2.1rc1-macOS-arm64.dmg`，将 `CogTool.app` 拖到 `Applications`（应用程序）。也可以解压同名 ZIP 后移动应用。
2. 双击 `CogTool.app`。从内置示例开始，或打开本项目格式的 JSON 模型。
3. 选择任务后运行预测。结果显示预测时间、步骤和模型信息，可以打开结果所在文件夹查看 `result.json`、`events.csv`、`steps.csv` 以及保存的 `input.json`。部分集成引擎另有运动和视觉事件 CSV。
4. 每次预测使用新的结果目录，便于保留历史记录。若模型不支持或计算未完成，界面会显示状态，不能把没有总时间的结果当成成功预测。

应用使用本地临时（ad-hoc）签名，**未使用 Apple Developer ID 签名或公证**。本机双击可用不等于其他 Mac 下载后无提示。若 macOS 因未验证开发者而阻止打开，在确认文件来自本次可信交付后，可在“系统设置 → 隐私与安全性”中选择“仍要打开”。不需要关闭系统安全保护。

## 支持范围

桌面版复用现有计算引擎和输入保存的配置，不自动更换引擎或参数。内置的四个示例是本项目自建 JSON，其点击、按键等时长属于明确标注的建模假设。

当前支持本项目 schema 1/2 JSON，保存为 schema 2。它不是原版 CogTool 图形编辑器，不支持任意 `.cgt` 文件导入；也不是完整 ACT-R、完整视觉搜索或通用交互设计编辑器。需要编写或修改模型时，可编辑 JSON 后重新打开。官方素材及标为 `LOCAL_ONLY` 的基准数据未放入这个安装包。详细边界见源码中的 `docs/SUPPORTED_FEATURES.md` 和 `docs/LIMITATIONS.md`。

## 发行内容与源码

构建输出在 `dist/macos/`：

- `CogTool.app`：可双击的完整应用。
- `CogTool-0.2.1rc1-macOS-arm64.dmg`：含“应用程序”快捷方式的安装镜像。
- `CogTool-0.2.1rc1-macOS-arm64.zip`：应用 ZIP 副本。
- `CogTool-0.2.1rc1-source.tar.gz`：本次核心、桌面界面、示例、许可和构建脚本源码。
- `CogTool-0.2.1rc1-build-report.json`：环境、文件摘要与打包检查记录。

在 Finder 右键应用选择“显示包内容”，`Contents/Resources/` 内包含 `Examples`、`Licenses`、`Source`、中文使用说明及构建清单。`engine/cogtool-engine` 及其 `_internal` 目录包含独立运行所需的 Python 和引擎；应用不依赖工作区或 Homebrew 路径。

代码继续采用 LGPL-2.1-or-later，保留原 `LICENSE`、`NOTICE.md` 和 ACT-R 许可说明。附带的 Python 与 PyInstaller 引导程序按各自许可提供。源码归档包含重新生成应用所需的项目源码和构建脚本，不含官方原工程、论文或历史 Java/Lisp 运行环境。此交付未公开发布。

## 从源码重新构建

需要 Apple Silicon Mac、macOS 15 或更高版本、Apple Command Line Tools（Swift 编译器和 macOS SDK），以及可创建虚拟环境的 Python 3.11 或更高版本。当前验收使用 Python 3.11.15、Swift 6.2.3、macOS SDK 26.2。构建脚本明确设置最低系统为 15.0；这不表示已经验证所有 15.x 系统。

在解压的源码目录或本项目根目录执行：

```sh
python3.11 -m venv .desktop-build-venv
.desktop-build-venv/bin/python -m pip install -r desktop/macos/requirements-build.txt
.desktop-build-venv/bin/python scripts/build_macos_app.py
```

只在安装构建依赖时需要访问包索引；构建脚本不联网。构建依赖已锁定版本。脚本将 PyInstaller 引擎放入原生 SwiftUI 应用，生成 CT 图标、签名，然后生成并验证 DMG 与 ZIP。

脚本会从不含外部 Python 的最小 PATH 和独立目录运行冻结引擎，对四个示例的所有任务与源码计算做完整结果比对（仅排除程序实际耗时），验证计算值、事件、步骤与实际源码指纹；另行检查内置资源示例。它还校验应用签名和 DMG 完整性。构建检查不代替人工桌面操作验收，最终交付应实际打开窗口、示例和导出结果。

为避免覆盖历史文件，已有产物时脚本默认报错。确需重建时使用：

```sh
.desktop-build-venv/bin/python scripts/build_macos_app.py --replace
```

`--replace` 仅替换上面列出的本版本桌面产物，且在新构建通过检查后才替换。项目根目录原有的 `CogTool.dmg` 不受影响。临时构建和检查记录保存在 `build/macos/runs/`，编译缓存保存在 `build/macos/cache/`。相同源码的 source 归档固定排序和元数据；应用签名、时间记录和系统工具输出不承诺逐字节一致。

CogTool-Py 0.2.1rc1 是本地研究软件候选包。普通计算只使用 Python 标准库；Java、SWT、SBCL、Lisp 源码和原研究目录均不属于运行依赖。包声明 Python ≥3.11；本次候选的实际平台验证范围是 macOS 15.6 / arm64 / Python 3.11.15，不能据此宣称 Windows、Linux 或其它 Python 版本已通过。

取得本次发行目录，将 wheel 放在 `dist/`。在该目录创建全新环境并安装本地文件：

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install --no-index --no-deps dist/cogtool_py-0.2.1rc1-py3-none-any.whl
```

这里不使用公共索引同名包、不使用 editable 安装，也不需要设置 PYTHONPATH。目录可以在原开发项目之外，并可以包含空格或中文。运行示例和 API 见 [QUICKSTART_zh.md](QUICKSTART_zh.md)。

发行材料按用途分开：

| 材料 | 用途与依赖 |
|---|---|
| `dist/cogtool_py-0.2.1rc1-py3-none-any.whl` | 安装 Python 软件；没有必需第三方运行依赖 |
| `dist/cogtool_py-0.2.1rc1.tar.gz` | 对应源码发行包；重建需要构建工具，不回取原工作区 |
| `examples/` | 自建最小案例；不是官方模型或真人数据 |
| `LOCAL_ONLY/benchmarks/` | 36项冻结复跑材料及来源清单；官方衍生材料的公开分发范围尚未明确 |
| `reference_tools/` | 专用参考验证入口与说明；需要其独立记录的 Java/SWT/Lisp 环境，普通预测不使用 |

构建后端沿用 setuptools。构建依赖固定为 setuptools 80.9.0、wheel 0.45.1；开发测试可选依赖为 pytest 8.4.2。这些工具不应被当作普通运行依赖。wheelhouse若附带第三方原始wheel，其版本、hash和许可必须保留；以发行清单为准，不要求用户将构建或测试依赖全部装入运行环境。

本地wheel安装在预先可用的Python/pip环境中不访问索引。sdist重建的工具供应与安装后的离线计算是不同事项：缺少构建工具时不能把重建称为已离线完成。验收采用的模块路径检查、网络/子进程调用守卫及实际离线安装结果记入交付报告；未物理阻断网络时不宣称做了物理断网测试。

维护者应分别从wheel与sdist在项目之外的全新环境验收。sdist路径必须从归档本身重建wheel；不使用源码目录、软链接或`.pth`补文件。实际解释器、加载模块路径、安装清单、依赖检查与哈希见交付的干净环境记录。相同源码/行为与归档字节完全相同是两种结论，不能用其中一种代替另一种。

本候选未公开发布。许可证和资料边界见 [NOTICE](../NOTICE.md) 与 [LIMITATIONS.md](LIMITATIONS.md)。

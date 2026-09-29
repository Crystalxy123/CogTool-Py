"""Audit supplied reference data read-only; never run or fit CogTool models.

Uses the Codex bundled document runtime and artifact-tool for workbook evidence.
The manually checked PDF observations are bound to exact SHA-256 values. Re-running
rechecks those bytes and table transcription, rather than pretending visual review
or original-program execution happened again automatically.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies"
DOC_COMMIT = "1f5fe10e2bebfb7544aa85a6db2c10078df9f9d3"
CODE_COMMIT = "a91d91e8dcf95d762b6e08020029a36ea079bbba"
NP_PDF = "reference/upstream-documentation/examples/phone-number-lookup/JohnEtAl_CHI04.pdf"
PR_PDF = "1937117.1937118.pdf"
VISUAL_OBSERVATIONS = {
    "NP": {
        "path": NP_PDF,
        "sha256": "8b3b78ecddb4fd9b12912ec84961e167fca66c1efd411ff992466455fc8582ac",
        "review_date": "2026-09-25", "page": 6, "label": "Table 1",
        "method": "Complete page rendered with Poppler at 150 dpi and visually inspected; title and surrounding text read with pypdf",
        "values": {
            "NP-A1": {"published_prediction_s": 15.6, "human_mean_s": 15.4, "human_sd_s": 3.0, "reported_participants": 20},
            "NP-A2": {"published_prediction_s": 25.6, "human_mean_s": 25.5, "human_sd_s": 5.0, "reported_participants": 20},
            "NP-B1": {"published_prediction_s": 3.5, "human_mean_s": 4.3, "human_sd_s": 1.0, "reported_participants": 20},
            "NP-B2": {"published_prediction_s": 6.2, "human_mean_s": 6.5, "human_sd_s": 0.9, "reported_participants": 20},
        },
    },
    "PR": {
        "path": PR_PDF,
        "sha256": "224c84e16f5e1cec7e7213f5ac2181079728d0bee95efbf6ff3cf42437223b87",
        "review_date": "2026-09-25", "page": 5, "label": "Figure 4",
        "method": "Complete page rendered with Poppler at 150 dpi and visually inspected; Section 4 on page 6 read with pypdf",
        "values": {
            "PR-HW-K": "161.111", "PR-HW-M": "114.405", "PR-HW-E": "40.090",
            "PR-F1-K": "30.726", "PR-F1-M": "31.247", "PR-F1-E": "10.462",
            "PR-CF-K": "10.490", "PR-CF-M": "5.780", "PR-CF-E": "3.563",
            "PR-BA-C": "40.149", "PR-BA-E": "11.833",
        },
    },
}
NP_IDS = ("NP-A1", "NP-A2", "NP-B1", "NP-B2")
SELECTED_IDS = (*NP_IDS, *VISUAL_OBSERVATIONS["PR"]["values"])
CATALOG_FILE = "实验数据/CogTool_reference_catalog.json"
WORKBOOK_FILE = "实验数据/CogTool_官方案例与对照数据.xlsx"
PUBLISHED_FIELDS = (
    "case_id", "family", "condition", "published_prediction_s", "human_mean_s",
    "human_sd_s", "reported_participants", "source_locator", "source_url", "notes",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def pdf_worker(root: Path) -> dict:
    from pypdf import PdfReader
    import pypdf
    found = {}
    for family, observation in VISUAL_OBSERVATIONS.items():
        path = root / observation["path"]
        if not path.is_file():
            found[family] = {"available": False, "path": str(path)}
            continue
        reader = PdfReader(path)
        if family == "PR":
            context = " ".join((reader.pages[5].extract_text() or "").split()).lower()
            checks = {
                "help_reading_omitted_statement": "not need to model reading the help" in context,
                "system_response_time_omitted_statement": "ignore system response time" in context,
            }
            pages = [2, 5, 6]
        else:
            context = " ".join((reader.pages[4].extract_text() or "").split()).lower()
            checks = {
                "html_mockup_statement": "html mock-up" in context,
                "behavior_recorder_statement": "behavior recorder" in context,
                "act_simple_statement": "act-simple" in context,
            }
            pages = [1, 5, 6]
        found[family] = {
            "available": True, "path": observation["path"], "sha256": sha256(path),
            "page_count": len(reader.pages), "inspected_pages": pages, "context_checks": checks,
            "figure_numbers_are_not_claimed_as_automated_ocr": True,
        }
    return {"runtime": sys.executable, "python_version": platform.python_version(),
            "pypdf_version": pypdf.__version__, "papers": found}


def inspect_workbook(root: Path, out: Path, node: Path, modules: Path) -> dict:
    helper = Path(__file__).with_name("audit_reference_workbook.mjs")
    evidence_path = out / "workbook_readonly_evidence.json"
    with tempfile.TemporaryDirectory(prefix="cogtool-catalog-") as directory:
        scratch = Path(directory)
        (scratch / "node_modules").symlink_to(modules, target_is_directory=True)
        copied = scratch / helper.name
        shutil.copyfile(helper, copied)
        process = subprocess.run([str(node), str(copied), str(root / WORKBOOK_FILE), str(evidence_path)],
                                 capture_output=True, text=True, timeout=120)
        if process.returncode:
            raise RuntimeError("Workbook read-only inspection failed: " + process.stderr[-3000:])
    return json.loads(evidence_path.read_text(encoding="utf-8"))


def indexed_rows(evidence: dict, sheet: str) -> dict:
    part = next(item for item in evidence["ranges"] if item["sheet"] == sheet)
    # All bounded source ranges begin at row 5; row 5 is the header.
    return {row[0]: {"row": i + 5, "values": row, "formulas": part["formulas"][i]}
            for i, row in enumerate(part["values"]) if i and row[0] is not None}


def strict_boundary(family: str) -> dict:
    common = [
        "Published totals are historical model predictions, not outputs rerun in this audit.",
        "Geometry, demonstration/leaf-task mapping, initial state, parameter configuration and timing boundary must be aligned.",
        "A hash-identified executable/runtime and newly saved raw trace are required for execution equivalence.",
        "klm_baseline omits ACT-R production/preparation/overlap and EMMA; published totals cannot validate that engine as equivalent.",
    ]
    specifics = ([
        "The 2004 HTML/Netscape/Behavior Recorder/ACT-Simple toolchain is not the 2014 fixed CogTool source.",
        "Official README records a 2009 archive; its .cgt contents cannot be assumed identical to 2004 models.",
        "N=20 describes N&P93 user data; the This paper novice/expert modeler rows each have N=1.",
    ] if family == "NP" else [
        "Figure 4 project name PERCS_CLI_PTP_Comparison_20091216_1513 does not identify an executable build.",
        "Use leaf results only; Min task-group rows duplicate the minimum of child alternatives.",
        "Help reading is excluded; all system-response times are omitted (page 6, Section 4).",
        "PLATEAU paper is distinct from official repository PPIG1218_1409_0.pdf; do not interchange versions silently.",
    ])
    return {"strict_comparable": False, "status": "historical_reference_only",
            "original_rerun_s": None, "python_result_s": None, "execution_tolerance_s": None,
            "blockers_and_scope": common + specifics}


def markdown(report: dict) -> str:
    lines = ["# 官方参考目录只读核对", "", f"核对时间：{report['created_at_utc']}。", "",
             "本次仅核对目录、Excel 和论文。没有重新执行原版或用发表值调整模型参数。原始 JSON、XLSX、PDF 均未改写。", "",
             f"选入 {len(report['selected_cases'])} 条（NP 4、PR 11），另保留 {len(report['excluded_official_cases'])} 条 PDA 排除记录。JSON 的其他目录部分没有作为本轮计算目标。", "",
             "## 数值和条件", "", "|案例|条件|发表预测/s|真人均值/s|真人 SD/s|人数|原文核对|",
             "|---|---|---:|---:|---:|---:|---|"]
    for row in report["selected_cases"]:
        def value(key):
            return "null" if row[key] is None else str(row[key])
        source = "Table 1，第 6 页" if row["case_id"].startswith("NP-") else "Figure 4，第 5 页"
        lines.append(f"|{row['case_id']}|{row['condition']}|{value('published_prediction_s')}|{value('human_mean_s')}|{value('human_sd_s')}|{value('reported_participants')}|{source}：{row['publication_audit']['status']}|")
    lines += ["", "null 表示未提供，不是零。PR 无对应真人统计；不得借用 NP 的样本量。所有原始 original_rerun_s、python_result_s 和时间容差空值原样保留。", "",
              "## 证据与定位", "",
              f"- JSON：`{CATALOG_FILE}`，`official_and_developer_published_results[0:15]`；原始官方/开发者记录共 19 条。",
              f"- Excel：`{WORKBOOK_FILE}`，`官方文献数值!A6:J20` 的 15 行与 JSON 所列字段逐项核对；另核对 `运行对照!A6:L20`，原版/Python/容差列均为空。发表值为常量，未重新计算或导出工作簿。",
              f"- NP：`{NP_PDF}`，PDF 第 6 页 Table 1 视觉核对；第 5 页任务/工具链说明。目录中印刷页 460 的说法另保留为来源定位，不将建模时间列误认为任务预测。",
              f"- PR：`{PR_PDF}`，PDF 第 5 页 Figure 4 视觉核对 11 个叶任务数值；第 6 页 Section 4 核对时间边界。目录原先写的附件名带日期后缀，本地实际文件名不同，已用 SHA-256 锁定实际读取文件。",
              "- PR 图中显示 40.090、10.490、5.780 秒；JSON 数值形式省略末尾零，没有数值差异。黄色 Min 任务组是子条件的最小值汇总，未重复计入 11 条案例。",
              "- PDF 的人工视觉观察记录绑定精确文件 SHA-256；脚本复跑验证文件未变及目录数值一致，不冒称每次自动完成新视觉核查。", "",
              "## 严格可比边界", "",
              "NP 的 20 是 N&P93 真人观察人数；This paper 的 novice/expert 两行各有 1 名建模者，预测完全相同。本表保留 4 个任务条件，不把两行变成 8 个独立任务。论文流程使用 HTML/Netscape、Behavior Recorder、ACT-Simple 和 ACT-R；不能视为 2014 tag 的运行证据。官方 README 为 2009 归档说明，版本仍须逐项对齐。", "",
              "PR Help 任务不包含阅读帮助正文，且所有模型均忽略系统响应时间。文中讨论了为了任务对齐而在命令行方案包含打开 Google、从书签选帮助页等步骤；不能单纯删掉这些跨窗口动作。Figure 4 项目标题含 20091216，但不提供二进制构建身份。官方归档 PPIG 稿与本地 PLATEAU 稿应分开记录。", "",
              f"当前代码参考为 `{CODE_COMMIT}`，文档归档为 `{DOC_COMMIT}`。15 条发表值均标 strict_comparable=false，原因是没有在本核查中取得匹配版本、几何、初始状态、参数、边界与真实轨迹的新执行证据。后续若主流程实际提取模型/缓存或运行仿真，应另存来源；不能用这里的 null 伪装执行值。", "",
              "发表位数（NP 0.1 秒、PR 0.001 秒）只是印刷精度，不是代码实现容差，也不授权使用 10–20% 人体预测误差来判断迁移等价。", "",
              "## 排除清单", "", "|案例|条件|发表预测/s|排除原因|", "|---|---|---:|---|"]
    for row in report["excluded_official_cases"]:
        lines.append(f"|{row['case_id']}|{row['condition']}|{row['published_prediction_s']}|PDA/触屏研究不属于本轮 NP+PR 范围；数值保留，未核对其原论文。|")
    lines += ["", "## 核查结果与复跑", "",
              f"Excel/JSON 不一致项：{len(report['workbook_differences'])}。参考资产 Git blob 不一致项：{sum(not x['git_blob_matches_catalog'] for x in report['asset_file_checks'] if x['local_exists'])}。输入字节保持不变：{report['inputs_unchanged']}。", "",
              "仅使用本地文件和本机 bundled runtime，无网络请求或文件上传。复跑：", "",
              "```bash", "python scripts/audit_reference_catalog.py --out reports/validation/<run_id>", "```", "",
              "运行环境、脚本哈希、输入 SHA-256、精确 Excel 单元格定位、PDF 观察及排除理由见同目录 catalog_audit.json。"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--bundle-python", type=Path, default=DEPENDENCIES / "python/bin/python3")
    parser.add_argument("--bundle-node", type=Path, default=DEPENDENCIES / "node/bin/node")
    parser.add_argument("--node-modules", type=Path, default=DEPENDENCIES / "node/node_modules")
    parser.add_argument("--pdf-worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    root = args.workspace.resolve()
    if args.pdf_worker:
        write_json(args.pdf_worker, pdf_worker(root))
        return 0
    if args.out is None:
        parser.error("--out <run_dir> is required")
    out = args.out.resolve() / "reference"
    out.mkdir(parents=True, exist_ok=True)
    input_names = [CATALOG_FILE, WORKBOOK_FILE, PR_PDF, NP_PDF]
    before = {name: sha256(root / name) for name in input_names if (root / name).is_file()}
    catalog = json.loads((root / CATALOG_FILE).read_text(encoding="utf-8"))
    official = catalog["official_and_developer_published_results"]
    if len({row["case_id"] for row in official}) != len(official):
        raise ValueError("duplicate official case ids")
    selected = [row for ident in SELECTED_IDS for row in official if row["case_id"] == ident]
    if len(selected) != 15:
        raise ValueError("Expected the specified NP 4 and PR 11 catalog cases")
    workbook = inspect_workbook(root, out, args.bundle_node, args.node_modules)
    by_id = indexed_rows(workbook, "官方文献数值")
    runs = indexed_rows(workbook, "运行对照")
    pdf_evidence = out / "pdf_readonly_evidence.json"
    subprocess.run([str(args.bundle_python), str(Path(__file__).resolve()), "--workspace", str(root), "--pdf-worker", str(pdf_evidence)],
                   capture_output=True, text=True, check=True, timeout=60)
    pdfs = json.loads(pdf_evidence.read_text(encoding="utf-8"))
    differences = []
    case_records = []
    for entry in official:
        workbook_row = by_id.get(entry["case_id"])
        if workbook_row is None:
            differences.append({"case_id": entry["case_id"], "reason": "absent in Excel"})
            continue
        for index, field in enumerate(PUBLISHED_FIELDS):
            if entry[field] != workbook_row["values"][index]:
                differences.append({"case_id": entry["case_id"], "field": field, "catalog": entry[field], "excel": workbook_row["values"][index]})
    suggested = {row["case_id"]: row for row in catalog["suggested_first_migration_run_conditions"]}
    for entry in selected:
        ident = entry["case_id"]
        family = "NP" if ident in NP_IDS else "PR"
        observation = VISUAL_OBSERVATIONS[family]
        pdf = pdfs["papers"][family]
        observed = observation["values"][ident]
        checks = ({field: entry[field] == value for field, value in observed.items()}
                  if family == "NP" else {"published_prediction_s": entry["published_prediction_s"] == float(observed)})
        hash_matches = pdf.get("sha256") == observation["sha256"]
        original_index = next(i for i, r in enumerate(official) if r["case_id"] == ident)
        row_number = by_id[ident]["row"]
        run = runs[ident]
        nulls = {"catalog_original_rerun_s": entry.get("original_rerun_s"), "catalog_python_result_s": entry.get("python_result_s"),
                 "suggested_original_rerun_s": suggested[ident]["original_rerun_s"], "suggested_python_result_s": suggested[ident]["python_result_s"],
                 "suggested_time_tolerance_s": suggested[ident]["time_tolerance_s"],
                 "excel_original_rerun_s": run["values"][2], "excel_python_result_s": run["values"][3], "excel_tolerance_s": run["values"][7]}
        case_records.append({**entry, "catalog_pointer": f"/official_and_developer_published_results/{original_index}",
            "excel": {"sheet": "官方文献数值", "row_range": f"A{row_number}:J{row_number}", "prediction_cell": f"D{row_number}",
                      "human_cells": f"E{row_number}:G{row_number}", "run_sheet": "运行对照", "run_range": f"A{run['row']}:L{run['row']}"},
            "null_evidence": nulls, "all_execution_fields_remain_null": all(v is None for v in nulls.values()),
            "publication_audit": {"status": "source_verified" if hash_matches and all(checks.values()) else "catalog-transcribed_unverified",
                "source_path": observation["path"], "source_sha256": pdf.get("sha256"), "pdf_page": observation["page"],
                "figure_or_table": observation["label"], "visual_observation_sha256_matches": hash_matches,
                "visual_review_date": observation["review_date"], "field_matches": checks,
                "prediction_as_printed": str(entry["published_prediction_s"]) if family == "NP" else observed,
                "printed_resolution_s": 0.1 if family == "NP" else 0.001,
                "resolution_is_not_execution_tolerance": True},
            "comparability": strict_boundary(family)})
    assets = []
    for entry in catalog["official_repository_assets"]:
        if entry["case_family"] not in {"电话查询", "编程工具"}:
            continue
        path = root / "reference/upstream-documentation" / entry["path"]
        item = {"path": str(path.relative_to(root)), "catalog_blob_sha": entry["git_blob_sha"], "local_exists": path.is_file()}
        if path.is_file():
            content = path.read_bytes()
            blob = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
            item.update({"sha256": hashlib.sha256(content).hexdigest(), "git_blob_sha": blob, "git_blob_matches_catalog": blob == entry["git_blob_sha"]})
        assets.append(item)
    rendered = []
    poppler = shutil.which("pdftoppm")
    if poppler:
        for family, info in VISUAL_OBSERVATIONS.items():
            if pdfs["papers"][family].get("available"):
                prefix = out / f"{family.lower()}_source_page_{info['page']}"
                subprocess.run([poppler, "-f", str(info["page"]), "-singlefile", "-r", "150", "-png", str(root / info["path"]), str(prefix)],
                               capture_output=True, text=True, check=True, timeout=60)
                rendered.append({"family": family, "path": str(prefix.with_suffix(".png").relative_to(args.out.resolve())), "sha256": sha256(prefix.with_suffix(".png"))})
    after = {name: sha256(root / name) for name in before}
    report = {
        "audit_schema_version": "1.0", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "operation": "read_only_reference_catalog_audit", "network_used": False, "uploads": False,
        "source_inputs": [{"path": name, "sha256_before": value, "sha256_after": after[name]} for name, value in before.items()],
        "inputs_unchanged": before == after,
        "runtime": {"driver_python": sys.executable, "bundled_python": str(args.bundle_python), "bundled_node": str(args.bundle_node),
                    "node_modules": str(args.node_modules), "bundle_version": "26.905.11957", "poppler": poppler,
                    "driver_sha256": sha256(Path(__file__)), "workbook_helper_sha256": sha256(Path(__file__).with_name("audit_reference_workbook.mjs"))},
        "catalog_metadata_original": {k: catalog[k] for k in ("schema_version", "prepared_on", "purpose", "status", "important_notes")},
        "catalog_metadata_is_not_current_run_status": True,
        "catalog_counts": {key: len(value) for key, value in catalog.items() if isinstance(value, list)},
        "selected_cases": case_records,
        "excluded_official_cases": [{**row, "exclusion_reason": "PDA/touch interaction outside requested NP+PR scope; preserve published values without claiming paper re-verification"}
                                    for row in official if row["case_id"] not in SELECTED_IDS],
        "workbook_differences": differences, "workbook_recalculated": False, "workbook_exported": False,
        "pdf_evidence": pdfs, "rendered_source_pages": rendered, "visual_observation_records": VISUAL_OBSERVATIONS,
        "asset_file_checks": assets,
        "strict_comparable_case_count": 0,
        "note": "Source transcription verification, cached archived model outputs and newly executed original results are separate evidence classes. This audit supplies only the first.",
    }
    write_json(out / "catalog_audit.json", report)
    (out / "CATALOG_zh.md").write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"selected": len(case_records), "excluded": len(report["excluded_official_cases"]),
                      "publication_verified": sum(r["publication_audit"]["status"] == "source_verified" for r in case_records),
                      "workbook_differences": len(differences), "inputs_unchanged": before == after,
                      "audit": str(out / "catalog_audit.json")}, ensure_ascii=False))
    return 0 if before == after and not differences else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""hooks/validate_json.py — 知识条目 JSON 校验器（schema 驱动）。

字段契约的单一事实来源是 `schemas/article.schema.json`（标准 JSON Schema）。
本脚本加载该 schema 来校验，**代码里不硬编码任何字段名/类型/约束** —— 字段增删只改 schema，
不改本文件。这是「单一事实来源」原则：避免 schema 在多处各抄一遍而漂移。

兼容批量集合形态（顶层 dict 含 items[] 数组、或顶层即为 JSON 数组），逐条校验。

用法：
    python hooks/validate_json.py <json_file> [json_file2 ...]
    python hooks/validate_json.py 'knowledge/articles/*.json'
    python hooks/validate_json.py --schema path/to/other.schema.json <files>

退出码：
    全部通过 → exit 0
    任一文件有错误 → exit 1（打印错误列表 + 汇总统计）
    用法/schema 加载错误 → exit 2

校验分两层（JSON Schema 的能力边界）：
    1. 结构校验（schema 驱动）：字段存在性、类型、枚举、pattern、minLength、minItems、
       minimum/maximum、additionalProperties。这部分 100% 由 schema 决定。
    2. 业务规则（代码）：JSON Schema 无法表达的跨字段约束 —— source↔id 对应关系、
       relevance_score ≥ 0.6 门控。这部分硬编码不可避免（跨字段逻辑）。
       未来若改用 jsonschema 库 + if/then/else，可把 source↔id 移入 schema。
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# schema 默认路径：相对脚本位置解析（hooks/ → 上级 → schemas/），与 CWD 无关
DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "article.schema.json"

# ===== 业务规则常量（跨字段约束，JSON Schema 无法表达）=====
ID_GITHUB = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
ID_HACKERNEWS = re.compile(r"^\d+$")
SCORE_GATE = 0.6  # organizer 质量门控阈值；articles/ 中不应出现低于门控的条目


@dataclass
class FileReport:
    """单个文件的校验结果。"""

    path: Path
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# --------------------------------------------------------------------------- #
# JSON Schema 子集解释器（零第三方依赖）
# 仅支持本项目 schema 用到的关键字：type / enum / pattern / minLength /
# minItems / items / minimum / maximum / required / properties /
# additionalProperties。schema 本身是标准 JSON Schema，未来可直接换用 jsonschema 库。
# --------------------------------------------------------------------------- #
def _json_type(value: object) -> str:
    """返回值的 JSON 类型名。"""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "null"
    return type(value).__name__


def _type_matches(value: object, expected: str) -> bool:
    """值是否符合 JSON Schema 的 type 约束（number/int 不接受 bool）。"""
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return True  # 未知 type 不拦


def _validate_value(value: object, subschema: dict, field_path: str) -> list[str]:
    """根据子 schema 校验单个值，返回错误列表。"""
    errors: list[str] = []

    expected_type = subschema.get("type")
    if expected_type and not _type_matches(value, expected_type):
        errors.append(f"{field_path}: 类型错误，期望 {expected_type}，实际 {_json_type(value)}")
        return errors  # 类型错则后续约束无意义

    if "enum" in subschema and value not in subschema["enum"]:
        errors.append(f"{field_path}: 值 {value!r} 不在枚举 {subschema['enum']} 中")

    if "pattern" in subschema and isinstance(value, str):
        if re.search(subschema["pattern"], value) is None:
            errors.append(f"{field_path}: 不匹配模式 {subschema['pattern']!r}（值 {value!r}）")

    if "minLength" in subschema and isinstance(value, str):
        if len(value) < subschema["minLength"]:
            errors.append(
                f"{field_path}: 长度不足，最少 {subschema['minLength']}，实际 {len(value)}"
            )

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in subschema and value < subschema["minimum"]:
            errors.append(f"{field_path}: 小于下限 {subschema['minimum']}，实际 {value}")
        if "maximum" in subschema and value > subschema["maximum"]:
            errors.append(f"{field_path}: 大于上限 {subschema['maximum']}，实际 {value}")

    if "minItems" in subschema and isinstance(value, list):
        if len(value) < subschema["minItems"]:
            errors.append(
                f"{field_path}: 元素不足，最少 {subschema['minItems']}，实际 {len(value)}"
            )

    if "items" in subschema and isinstance(value, list):
        item_schema = subschema["items"]
        for index, item in enumerate(value):
            errors.extend(_validate_value(item, item_schema, f"{field_path}[{index}]"))

    return errors


def validate_against_schema(data: object, schema: dict, context: str = "") -> list[str]:
    """结构校验：按 schema 校验一个 article 对象（required / additionalProperties / 各字段）。"""
    prefix = f"[{context}] " if context else ""

    if not isinstance(data, dict):
        return [f"{prefix}条目不是 JSON 对象，实际 {_json_type(data)}"]

    errors: list[str] = []
    properties = schema.get("properties", {})
    required = schema.get("required", [])

    # 必填字段存在性
    for name in required:
        if name not in data:
            errors.append(f"{prefix}缺失必填字段: {name}")

    # additionalProperties: false → 拒绝未定义字段（防 score_breakdown 等泄漏）
    if schema.get("additionalProperties") is False:
        for key in data:
            if key not in properties:
                errors.append(f"{prefix}出现未定义字段（schema 未声明）: {key}")

    # 各已声明字段的约束
    for name, subschema in properties.items():
        if name in data:
            errors.extend(_validate_value(data[name], subschema, f"{prefix}字段 {name}"))

    return errors


def check_business_rules(data: object, context: str = "") -> list[str]:
    """业务规则：JSON Schema 无法表达的跨字段约束。"""
    prefix = f"[{context}] " if context else ""

    if not isinstance(data, dict):
        return []

    errors: list[str] = []
    src = data.get("source")
    id_ = data.get("id")
    score = data.get("relevance_score")

    # source ↔ id 对应关系（跨字段，schema 无法表达）
    if isinstance(id_, str) and id_:
        if src == "github-hot-repos" and not ID_GITHUB.match(id_):
            errors.append(f"{prefix}ID 格式异常（GitHub 应为 owner/repo）: {id_}")
        elif src == "hackernews-top" and not ID_HACKERNEWS.match(id_):
            errors.append(f"{prefix}ID 格式异常（HN 应为数字）: {id_}")

    # 质量门控：articles/ 中不应出现 < 0.6 的条目
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        if score < SCORE_GATE:
            errors.append(f"{prefix}relevance_score 低于门控阈值 {SCORE_GATE}: {score}")

    return errors


# --------------------------------------------------------------------------- #
# 文件加载与条目提取
# --------------------------------------------------------------------------- #
def load_articles(path: Path) -> tuple[list[tuple[object, str]], list[str]]:
    """读取文件，返回 (待校验条目列表[(data, context), ...], 解析错误列表)。

    支持三种 JSON 形态：单个 article 对象 / 集合（dict 含 items[]）/ JSON 数组。
    """
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], [f"无法读取文件: {exc}"]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], [f"JSON 解析失败: {exc}"]

    articles: list[tuple[object, str]] = []
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        for index, item in enumerate(data["items"]):
            articles.append((item, f"items[{index}]"))
    elif isinstance(data, list):
        for index, item in enumerate(data):
            articles.append((item, f"[{index}]"))
    elif isinstance(data, dict):
        articles.append((data, ""))
    else:
        errors.append(
            f"不支持的 JSON 结构: 顶层为 {_json_type(data)}，"
            f"期望 dict / list / 含 items[] 的 dict"
        )
    return articles, errors


def collect_paths(args: list[str]) -> list[Path]:
    """从命令行参数收集文件路径，展开通配符（单文件 / 多文件通配）。"""
    paths: list[Path] = []
    for arg in args:
        matched = glob.glob(arg)
        if matched:
            paths.extend(Path(m) for m in matched)
        else:
            paths.append(Path(arg))  # 无匹配也保留，以便报告「文件不存在」
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def load_schema(path: Path) -> dict:
    """加载 JSON Schema 文件（失败则抛 SystemExit 退出码 2）。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"无法读取 schema 文件 {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"schema 文件 {path} JSON 解析失败: {exc}") from exc


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
def _print_file_report(report: FileReport) -> None:
    if report.ok:
        print(f"PASS  {report.path}")
    else:
        print(f"FAIL  {report.path}  ({len(report.errors)} 个错误)")
        for err in report.errors:
            print(f"        - {err}")


def _print_summary(reports: list[FileReport]) -> None:
    total = len(reports)
    passed = sum(1 for r in reports if r.ok)
    failed = total - passed
    total_errors = sum(len(r.errors) for r in reports)
    print()
    print("=" * 64)
    print(f"汇总: 文件 {total} | 通过 {passed} | 失败 {failed} | 错误 {total_errors}")


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="知识条目 JSON 校验器（schema 驱动，字段契约见 schemas/article.schema.json）"
    )
    parser.add_argument(
        "--schema",
        default=str(DEFAULT_SCHEMA_PATH),
        help=f"JSON Schema 文件路径（默认: {DEFAULT_SCHEMA_PATH}）",
    )
    parser.add_argument("files", nargs="+", metavar="json_file", help="待校验 JSON 文件（支持通配符）")
    args = parser.parse_args(argv[1:])

    schema = load_schema(Path(args.schema))
    print(f"[schema] {Path(args.schema)}（required {len(schema.get('required', []))} 字段）\n")

    paths = collect_paths(args.files)
    reports: list[FileReport] = []

    for path in paths:
        report = FileReport(path=path)
        if not path.exists():
            report.errors.append("文件不存在")
            reports.append(report)
            _print_file_report(report)
            continue
        if not path.is_file():
            report.errors.append("不是常规文件")
            reports.append(report)
            _print_file_report(report)
            continue
        articles, load_errors = load_articles(path)
        report.errors.extend(load_errors)
        for data, context in articles:
            # 结构校验（schema 驱动）+ 业务规则（跨字段）
            report.errors.extend(validate_against_schema(data, schema, context))
            report.errors.extend(check_business_rules(data, context))
        reports.append(report)
        _print_file_report(report)

    _print_summary(reports)
    return 0 if all(report.ok for report in reports) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

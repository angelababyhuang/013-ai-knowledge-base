#!/usr/bin/env python3
"""hooks/check_quality.py — 知识条目 5 维质量评分器（rubric 驱动）。

评分规则的单一事实来源是 `schemas/quality-rubric.json`。本脚本加载该 rubric 来评分，
**代码不硬编码任何阈值/权重/词表/标签列表** —— 调分只改 rubric，不改本文件。

5 个维度（加权总分 100）：
    摘要质量(25) / 技术深度(25) / 格式规范(20) / 标签精度(15) / 空洞词检测(15)
等级：A ≥ 80，B ≥ 60，C < 60。

用法：
    python hooks/check_quality.py <json_file> [json_file2 ...]
    python hooks/check_quality.py 'knowledge/articles/*.json'
    python hooks/check_quality.py --rubric path/to/other.rubric.json <files>

退出码：存在 C 级条目 → exit 1，否则 exit 0。

适配说明（课程 schema → 本项目 schema）：
    - 技术深度：课程用 score(1-10)，本项目无此字段；改用 relevance_score(0-1)×25。
    - 格式规范：课程查 status，本项目无此字段；改用 category（open-source/paper-or-talk/article-or-news）。
    - 标签精度：标准词表取项目中出现≥2次的高频标签（数据驱动）。
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# rubric 默认路径：相对脚本位置解析（hooks/ → 上级 → schemas/），与 CWD 无关
DEFAULT_RUBRIC_PATH = Path(__file__).resolve().parent.parent / "schemas" / "quality-rubric.json"


@dataclass
class DimensionScore:
    """单个维度的评分结果。"""

    name: str
    label: str
    score: float
    max_score: float
    details: list[str] = field(default_factory=list)


@dataclass
class QualityReport:
    """单个条目（或文件内单条）的质量评分报告。"""

    path: Path
    context: str
    dimensions: list[DimensionScore] = field(default_factory=list)
    grade: str = "C"
    error: str | None = None  # 加载/解析错误时填，此时 dimensions 为空

    @property
    def total(self) -> float:
        return round(sum(d.score for d in self.dimensions), 2)

    @property
    def ok(self) -> bool:
        return self.error is None and self.grade != "C"


# --------------------------------------------------------------------------- #
# rubric 加载
# --------------------------------------------------------------------------- #
def load_rubric(path: Path) -> dict:
    """加载评分 rubric（失败则抛 SystemExit 退出码 2）。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"无法读取 rubric 文件 {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"rubric 文件 {path} JSON 解析失败: {exc}") from exc


def _grade(total: float, boundaries: dict) -> str:
    if total >= boundaries.get("A", 80):
        return "A"
    if total >= boundaries.get("B", 60):
        return "B"
    return "C"


# --------------------------------------------------------------------------- #
# 各维度评分（参数全部来自 rubric，代码不含阈值/词表）
# --------------------------------------------------------------------------- #
def _score_summary(data: dict, dim: dict) -> DimensionScore:
    p = dim["params"]
    text = data.get(p["field"], "")
    if not isinstance(text, str):
        text = ""
    length = len(text)

    if length >= p["full_length"]:
        base, base_note = p["full_points"], f"≥{p['full_length']}字 满分基础"
    elif length >= p["base_length"]:
        base, base_note = p["base_points"], f"≥{p['base_length']}字 基本分"
    else:
        base, base_note = p["low_points"], f"<{p['base_length']}字 低分"

    lower = text.lower()
    found = [kw for kw in p["tech_keywords_en"] if kw in lower]
    found += [kw for kw in p["tech_keywords_zh"] if kw in text]
    found = list(dict.fromkeys(found))  # 去重保序
    bonus = min(len(found) * p["keyword_points"], p["keyword_bonus_max"])
    score = min(base + bonus, dim["max_score"])

    return DimensionScore(
        name=dim["name"], label=dim["label"], score=score, max_score=dim["max_score"],
        details=[f"{length}字 · {base_note}", f"技术关键词×{len(found)} (+{bonus})"],
    )


def _score_scale_field(data: dict, dim: dict) -> DimensionScore:
    p = dim["params"]
    val = data.get(p["field"])
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        raw = val * p["factor"]
        score = max(0.0, min(raw, dim["max_score"]))
        detail = f"{p['field']}={val} × {p['factor']} = {raw:.2f}"
    else:
        score, detail = 0.0, f"字段 {p['field']} 缺失或非数值"
    return DimensionScore(
        name=dim["name"], label=dim["label"], score=score, max_score=dim["max_score"],
        details=[detail],
    )


def _score_format(data: dict, dim: dict) -> DimensionScore:
    p = dim["params"]
    points_each = p["points_each"]
    fields = p["fields"]
    got = 0.0
    count = 0
    marks = []
    for f in fields:
        name, check = f["name"], f["check"]
        val = data.get(name)
        if check == "url_https":
            ok = isinstance(val, str) and val.startswith("https://")
        else:  # nonempty
            ok = isinstance(val, str) and val.strip() != ""
        if ok:
            got += points_each
            count += 1
            marks.append(f"✓{name}")
        else:
            marks.append(f"✗{name}")
    return DimensionScore(
        name=dim["name"], label=dim["label"], score=got, max_score=dim["max_score"],
        details=[f"{count}/{len(fields)} 字段合规", " ".join(marks)],
    )


def _score_tags(data: dict, dim: dict) -> DimensionScore:
    p = dim["params"]
    tags = data.get(p["field"], [])
    if not isinstance(tags, list):
        tags = []
    standard = set(p["standard_tags"])
    hits = [t for t in tags if t in standard]
    precision = min(len(hits), p["optimal_count"]) * p["points_per_standard"]

    pattern = re.compile(p["tag_pattern"])
    all_valid = bool(tags) and all(isinstance(t, str) and pattern.match(t) for t in tags)
    format_bonus = p["format_bonus"] if all_valid else 0
    score = min(precision + format_bonus, dim["max_score"])

    return DimensionScore(
        name=dim["name"], label=dim["label"], score=score, max_score=dim["max_score"],
        details=[
            f"标准标签×{len(hits)}" + (f" ({', '.join(hits)})" if hits else " (无)"),
            f"格式{'合规' if all_valid else '不合规'}",
        ],
    )


def _score_buzzword(data: dict, dim: dict) -> DimensionScore:
    p = dim["params"]
    text = " ".join(str(data.get(f, "")) for f in p["fields"]).lower()
    hits = [w for w in p["blacklist_zh"] if w in text]
    hits += [w for w in p["blacklist_en"] if w in text]
    deduction = len(hits) * p["deduction_per_hit"]
    score = max(dim["max_score"] - deduction, 0.0)
    return DimensionScore(
        name=dim["name"], label=dim["label"], score=score, max_score=dim["max_score"],
        details=[
            f"命中空洞词×{len(hits)}" + (f" ({', '.join(hits)})" if hits else ""),
            f"扣 {deduction} 分" if deduction else "无空洞词",
        ],
    )


_SCORERS = {
    "summary": _score_summary,
    "scale_field": _score_scale_field,
    "format": _score_format,
    "tags": _score_tags,
    "buzzword": _score_buzzword,
}


def score_dimension(data: dict, dim: dict) -> DimensionScore:
    """按维度 type 分派到对应评分函数。"""
    scorer = _SCORERS.get(dim.get("type"))
    if scorer is None:
        return DimensionScore(
            name=dim["name"], label=dim["label"], score=0.0, max_score=dim["max_score"],
            details=[f"未知维度类型: {dim.get('type')}"],
        )
    return scorer(data, dim)


def score_article(data: object, rubric: dict, path: Path, context: str = "") -> QualityReport:
    """对单条 article 评分，返回 QualityReport。"""
    if not isinstance(data, dict):
        return QualityReport(path=path, context=context, error=f"条目不是 JSON 对象，实际 {type(data).__name__}")
    dims = [score_dimension(data, d) for d in rubric["dimensions"]]
    total = sum(d.score for d in dims)
    grade = _grade(total, rubric.get("grade_boundaries", {}))
    return QualityReport(path=path, context=context, dimensions=dims, grade=grade)


# --------------------------------------------------------------------------- #
# 文件加载与条目提取（兼容 单条 / items[] / 数组）
# --------------------------------------------------------------------------- #
def load_articles(path: Path) -> tuple[list[tuple[object, str]], str | None]:
    """返回 (待评分条目列表[(data, context), ...], 错误信息)。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], f"无法读取文件: {exc}"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [], f"JSON 解析失败: {exc}"

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
        return [], f"不支持的 JSON 结构: {type(data).__name__}"
    return articles, None


def collect_paths(args: list[str]) -> list[Path]:
    """展开通配符、去重保序。"""
    paths: list[Path] = []
    for arg in args:
        matched = glob.glob(arg)
        paths.extend(Path(m) for m in matched) if matched else paths.append(Path(arg))
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


# --------------------------------------------------------------------------- #
# 可视化输出
# --------------------------------------------------------------------------- #
def _bar(score: float, max_score: float, width: int = 24) -> str:
    ratio = (score / max_score) if max_score > 0 else 0
    ratio = max(0.0, min(1.0, ratio))
    filled = round(ratio * width)
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def _print_report(report: QualityReport, rubric: dict) -> None:
    total = report.total
    max_total = rubric["total_score"]
    loc = f"{report.path}" + (f" [{report.context}]" if report.context else "")
    print(f"\n═══ {loc} ═══")
    if report.error:
        print(f"  ✗ 评分失败: {report.error}")
        return
    for d in report.dimensions:
        print(f"  {d.label:<7} {_bar(d.score, d.max_score)} {d.score:>5.1f}/{d.max_score:<3.0f}  {' · '.join(d.details)}")
    print(f"  {'─' * 62}")
    grade_mark = {"A": "🅰", "B": "🅱", "C": "⚠ C"}.get(report.grade, report.grade)
    print(f"  {'总分':<6} {_bar(total, max_total)} {total:>5.1f}/{max_total:<3.0f}  等级 {grade_mark}")


def _print_summary(reports: list[QualityReport]) -> None:
    scored = [r for r in reports if r.error is None]
    grades = {"A": 0, "B": 0, "C": 0}
    for r in scored:
        grades[r.grade] = grades.get(r.grade, 0) + 1
    errors = len(reports) - len(scored)
    print()
    print("=" * 64)
    print(f"汇总: 条目 {len(scored)} | A {grades['A']} | B {grades['B']} | C {grades['C']}"
          + (f" | 评分失败 {errors}" if errors else ""))


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="知识条目 5 维质量评分器（rubric 驱动，规则见 schemas/quality-rubric.json）"
    )
    parser.add_argument(
        "--rubric",
        default=str(DEFAULT_RUBRIC_PATH),
        help=f"评分 rubric 文件路径（默认: {DEFAULT_RUBRIC_PATH}）",
    )
    parser.add_argument("files", nargs="+", metavar="json_file", help="待评分 JSON 文件（支持通配符）")
    args = parser.parse_args(argv[1:])

    rubric = load_rubric(Path(args.rubric))
    print(f"[rubric] {Path(args.rubric)}（{len(rubric['dimensions'])} 维度，满分 {rubric['total_score']}）\n")

    paths = collect_paths(args.files)
    reports: list[QualityReport] = []

    for path in paths:
        if not path.exists():
            reports.append(QualityReport(path=path, context="", error="文件不存在"))
            _print_report(reports[-1], rubric)
            continue
        if not path.is_file():
            reports.append(QualityReport(path=path, context="", error="不是常规文件"))
            _print_report(reports[-1], rubric)
            continue
        articles, err = load_articles(path)
        if err:
            reports.append(QualityReport(path=path, context="", error=err))
            _print_report(reports[-1], rubric)
            continue
        for data, context in articles:
            rep = score_article(data, rubric, path, context)
            reports.append(rep)
            _print_report(rep, rubric)

    _print_summary(reports)
    # 存在 C 级或评分失败 → exit 1
    return 0 if all(r.ok for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

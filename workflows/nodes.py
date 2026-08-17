#!/usr/bin/env python3
"""workflows/nodes.py — LangGraph 知识库工作流的 5 个节点函数。

每个节点是纯函数：接收 :class:`~workflows.state.KBState`，返回**部分状态
更新**的 dict（LangGraph 按 channel 合并），不修改入参、不抛异常中断图。

流水线（与 pipeline/pipeline.py 四步的对应关系）::

    collect_node   ←→ Step1 Collect   GitHub Search API（urllib.request）
    analyze_node   ←→ Step2 Analyze   逐条 LLM 摘要/标签/评分
    organize_node  ←→ Step3 Organize  <0.6 门控 + URL 去重 + 反馈定向修正
    review_node    ←→ patterns/supervisor.py 的审核循环（四维度版）
    save_node      ←→ Step4 Save      articles/ + index.json

与既有实现的兼容约定：

- **save_node 完全对齐现有契约**：文件名 ``{date}-{source}-{slug}.json``、
  article 12 字段（schemas/article.schema.json）、index.json 的
  ``{updated_at, total_count, articles:[9字段]}`` 结构，并按 id 查重保证
  幂等——下游消费者（mcp_knowledge_server.py、patterns/router.py、
  pipeline 的 load_existing_urls）不受影响。
- ``slugify`` / ``build_meta`` / ``build_article`` / ``SLUG_STOPWORDS``
  复制自 pipeline/pipeline.py（其为脚本式模块 ``from model_client import``
  不可包导入），逻辑保持一致，注明出处。
- organize 门控取课程要求的 ``relevance_score < 0.6`` 子集（pipeline 另有
  摘要长度 / tags 数量 / url 三规则，见其 gate_item）。
- review 的 ``iteration >= 2 强制通过`` 与 state.MAX_REVIEW_ITERATIONS=3
  语义一致：iteration 0、1 可不通过，第 3 轮（iteration=2）强制放行。

LLM 调用统一走 workflows/model_client.py（课程签名 chat / chat_json /
accumulate_usage），底层复用 pipeline/model_client 的多 provider 基建。

环境变量::

    GITHUB_TOKEN    可选，GitHub API 提额
    WORKFLOWS_DRY_RUN=1    save_node 只打日志不落盘（自测用）

用法（下一节接入 StateGraph 前的手动串联）::

    from workflows.state import KBState
    from workflows.nodes import collect_node, analyze_node, ...

    state: KBState = {...初始化...}
    state.update(collect_node(state))

也可直接运行自测（建议配 WORKFLOWS_DRY_RUN=1 防止污染 articles/）::

    set -a && . ./.env && set +a && WORKFLOWS_DRY_RUN=1 \\
        python workflows/nodes.py --limit 2
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from workflows.model_client import accumulate_usage, chat_json  # noqa: E402
from workflows.state import KBState, MAX_REVIEW_ITERATIONS  # noqa: E402

logger = logging.getLogger("workflows.nodes")

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
GITHUB_API = "https://api.github.com/search/repositories"
DEFAULT_QUERY = "AI agent"
DEFAULT_LIMIT = 5  # analyze 逐条调 LLM，采集量即成本，默认取小

SCORE_GATE = 0.6  # 对齐 pipeline.SCORE_GATE / organizer 门控

# GitHub 源隐含 category（AGENTS.md：GitHub 恒为 open-source）
GITHUB_CATEGORY = "open-source"

ARTICLES_DIR = _PROJECT_ROOT / "knowledge" / "articles"
INDEX_FILE = ARTICLES_DIR / "index.json"

# 复制自 pipeline/pipeline.py SLUG_STOPWORDS（该模块不可包导入）
SLUG_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on",
    "with", "is", "are", "by", "at", "as", "from",
}

DRY_RUN = os.getenv("WORKFLOWS_DRY_RUN", "") == "1"


# --------------------------------------------------------------------------- #
# 通用工具（与 pipeline.py 同口径，复制因其不可包导入）
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    """当前 UTC 时间，ISO 8601（YYYY-MM-DDTHH:mm:ssZ）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def read_json(path: Path, default: Any) -> Any:
    """读取 JSON；不存在或解析失败返回 default（不抛错）。"""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取 %s 失败（%s），按默认处理", path, exc)
        return default


def write_json(path: Path, data: Any) -> None:
    """2 空格缩进、UTF-8、中文不转义落盘（对齐 AGENTS.md JSON 格式）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def slugify(title: str) -> str:
    """title → 全小写连字符 slug，去停用词（复制自 pipeline/pipeline.py）。"""
    words = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-").split("-")
    slug = "-".join(w for w in words if w and w not in SLUG_STOPWORDS)
    return slug or "untitled"


def _normalize_url(url: str) -> str:
    """URL 去重键：去尾部斜杠与协议差异（http/https 同源视为同条）。"""
    normalized = (url or "").strip().rstrip("/")
    if normalized.startswith("http://"):
        normalized = "https://" + normalized[len("http://"):]
    return normalized.lower()


# --------------------------------------------------------------------------- #
# 节点 1：collect_node
# --------------------------------------------------------------------------- #
def collect_node(state: KBState) -> dict:
    """调 GitHub Search API 采集 AI 相关热门仓库（urllib.request）。

    产出 sources 列表（报告式通信：只留下游需要的结构化摘要，不带 README
    原文等原始数据），元素对齐 knowledge/raw/ 的 github item 结构：
    ``{id, title, url, source, collected_at, stars, language, topics,
    pushed_at, description}``。

    网络失败时按项目错误策略记录并返回空列表，不中断图。
    """
    logger.info("[CollectNode] 开始采集 GitHub 热门仓库（query=%r）", DEFAULT_QUERY)
    limit = DEFAULT_LIMIT

    params = urllib.parse.urlencode(
        {
            "q": DEFAULT_QUERY,
            "sort": "stars",
            "order": "desc",
            "per_page": limit,
        }
    )
    req = urllib.request.Request(
        f"{GITHUB_API}?{params}",
        headers={"Accept": "application/vnd.github.v3+json"},
    )
    token = os.getenv("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        logger.error("[CollectNode] GitHub API 请求失败: %s", exc)
        return {"sources": []}

    collected_at = now_iso()
    items: List[Dict[str, Any]] = []
    for repo in data.get("items", [])[:limit]:
        items.append(
            {
                "id": repo.get("full_name") or repo.get("html_url", ""),
                "title": repo.get("name") or repo.get("full_name", ""),
                "url": repo.get("html_url", ""),
                "source": "github-hot-repos",
                "collected_at": collected_at,
                "stars": repo.get("stargazers_count"),
                "language": repo.get("language"),
                "topics": repo.get("topics") or [],
                "pushed_at": repo.get("updated_at"),
                "description": repo.get("description") or "",
            }
        )

    logger.info("[CollectNode] 采集完成，共 %d 条", len(items))
    return {"sources": items}


# --------------------------------------------------------------------------- #
# 节点 2：analyze_node
# --------------------------------------------------------------------------- #
_ANALYZE_SYSTEM = (
    "你是 AI 领域的技术分析师。对给定的仓库做中文摘要、打英文标签、"
    "评估与 AI/LLM/Agent 领域的相关性。只输出 JSON。"
)

_ANALYZE_PROMPT = """分析以下 GitHub 仓库，严格只输出如下 JSON（不要 markdown 围栏）：
{{
  "summary": "中文摘要 100-200 字，说明它是什么、解决什么问题、为何值得关注",
  "tags": ["3-5 个英文小写 kebab-case 标签，如 large-language-model"],
  "relevance_score": 0.0
}}
其中 relevance_score 是 0.0-1.0 的浮点数（与 AI/LLM/Agent 领域的相关度，
1.0 表示高度相关），保留两位小数。

仓库信息：
- 名称：{title}
- 地址：{url}
- 描述：{description}
- 语言：{language}，stars：{stars}"""


def analyze_node(state: KBState) -> dict:
    """逐条调 LLM 生成中文摘要、英文标签、0-1 相关性评分。

    单条解析失败按项目错误策略跳过（记 warning），失败条目以 0.0 分
    进入 analyses，由 organize_node 门控自然丢弃——不在节点里抛错。
    """
    sources = state.get("sources") or []
    logger.info("[AnalyzeNode] 开始分析 %d 条数据", len(sources))

    tracker = dict(state.get("cost_tracker") or {})
    analyzed_at = now_iso()
    results: List[Dict[str, Any]] = []

    for item in sources:
        prompt = _ANALYZE_PROMPT.format(
            title=item.get("title", ""),
            url=item.get("url", ""),
            description=item.get("description") or "（无描述）",
            language=item.get("language") or "未知",
            stars=item.get("stars") or "未知",
        )
        parsed, usage = chat_json(prompt, system=_ANALYZE_SYSTEM)
        tracker = accumulate_usage(tracker, usage, node="analyze_node")

        if not isinstance(parsed, dict):
            logger.warning(
                "[AnalyzeNode] %r 分析结果解析失败，按 0.0 分进入门控",
                item.get("id"),
            )
            parsed = {"summary": "", "tags": [], "relevance_score": 0.0}

        try:
            score = round(float(parsed.get("relevance_score", 0.0)), 2)
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(1.0, score))

        results.append(
            {
                **item,
                "summary": str(parsed.get("summary") or ""),
                "tags": [str(t) for t in (parsed.get("tags") or []) if t],
                "relevance_score": score,
                "analyzed_at": analyzed_at,
            }
        )

    passed = sum(1 for r in results if r["relevance_score"] >= SCORE_GATE)
    logger.info(
        "[AnalyzeNode] 分析完成 %d 条，其中 %d 条达到 %.1f 门控线",
        len(results), passed, SCORE_GATE,
    )
    return {"analyses": results, "cost_tracker": tracker}


# --------------------------------------------------------------------------- #
# 节点 3：organize_node
# --------------------------------------------------------------------------- #
def _build_meta(item: Dict[str, Any]) -> Dict[str, Any]:
    """meta 跨源统一容器（GitHub 字段集，复制自 pipeline.build_meta 口径）。"""
    return {
        "stars": item.get("stars"),
        "language": item.get("language"),
        "topics": item.get("topics") or [],
        "pushed_at": item.get("pushed_at"),
    }


def _revise_with_feedback(
    article: Dict[str, Any], feedback: str, tracker: dict
) -> tuple[Dict[str, Any], dict]:
    """按审核反馈用 LLM 定向修正单条 article 的 summary/tags。"""
    prompt = (
        "以下知识条目未通过审核，请按审核反馈修正摘要与标签。\n"
        "严格只输出如下 JSON（不要 markdown 围栏）：\n"
        '{"summary": "修正后的中文摘要 100-200 字", "tags": ["修正后的标签"]}\n\n'
        f"审核反馈：{feedback}\n\n"
        f"当前条目：{json.dumps({k: article.get(k) for k in ('title', 'summary', 'tags')}, ensure_ascii=False)}"
    )
    parsed, usage = chat_json(prompt, system="你是知识库条目修订助手，只输出 JSON。")
    tracker = accumulate_usage(tracker, usage, node="organize_node")
    if isinstance(parsed, dict):
        if parsed.get("summary"):
            article = {**article, "summary": str(parsed["summary"])}
        if parsed.get("tags"):
            article = {
                **article,
                "tags": [str(t) for t in (parsed.get("tags") or []) if t],
            }
    else:
        logger.warning("[OrganizeNode] %r 修正解析失败，保留原条目", article.get("id"))
    return article, tracker


def organize_node(state: KBState) -> dict:
    """门控（< 0.6 丢弃）+ URL 去重 + 格式化为 12 字段知识条目。

    去重两层：batch 内按规范化 URL，batch 外对齐存量 index.json 的
    url/id（幂等，重复运行不产生重复条目——AGENTS.md 规则 3）。
    审核循环中（iteration > 0 且有反馈）逐条 LLM 定向修正 summary/tags。
    """
    analyses = state.get("analyses") or []
    iteration = state.get("iteration", 0)
    feedback = state.get("review_feedback") or ""
    logger.info(
        "[OrganizeNode] 输入 %d 条，iteration=%d，feedback=%s",
        len(analyses), iteration, "有" if feedback else "无",
    )

    tracker = dict(state.get("cost_tracker") or {})

    # 存量 url/id 集合（幂等去重）
    index = read_json(INDEX_FILE, {})
    existing: Dict[str, str] = {}
    for entry in (index.get("articles") or []):
        existing[_normalize_url(entry.get("url", ""))] = entry.get("id", "")
    existing_ids = {e.get("id", "") for e in (index.get("articles") or [])}

    kept: List[Dict[str, Any]] = []
    seen_urls = set(existing.keys())
    dropped = {"low_score": 0, "dup_url": 0, "dup_id": 0}

    for item in analyses:
        if item.get("relevance_score", 0.0) < SCORE_GATE:
            dropped["low_score"] += 1
            continue
        url_key = _normalize_url(item.get("url", ""))
        if url_key and url_key in seen_urls:
            dropped["dup_url"] += 1
            continue
        if item.get("id") in existing_ids:
            dropped["dup_id"] += 1
            continue
        seen_urls.add(url_key)

        # 12 字段知识条目（对齐 schemas/article.schema.json）
        article: Dict[str, Any] = {
            "id": item["id"],
            "title": item["title"],
            "url": item["url"],
            "category": GITHUB_CATEGORY,
            "source": item["source"],
            "collected_at": item["collected_at"],
            "summary": item.get("summary", ""),
            "tags": item.get("tags", []),
            "relevance_score": item.get("relevance_score", 0.0),
            "analyzed_at": item.get("analyzed_at", ""),
            "organized_at": now_iso(),
            "meta": _build_meta(item),
        }
        kept.append(article)

    # 审核反馈定向修正（课程关键设计点：iteration > 0 且有 feedback）
    if iteration > 0 and feedback:
        logger.info("[OrganizeNode] 按审核反馈修正 %d 条", len(kept))
        revised = []
        for article in kept:
            revised_article, tracker = _revise_with_feedback(article, feedback, tracker)
            revised.append(revised_article)
        kept = revised

    logger.info(
        "[OrganizeNode] 通过 %d 条，丢弃 %s",
        len(kept), dropped,
    )
    return {"articles": kept, "cost_tracker": tracker}


# --------------------------------------------------------------------------- #
# 节点 4：review_node
# --------------------------------------------------------------------------- #
_REVIEW_SYSTEM = (
    "你是知识库质量审核员。对整理后的知识条目做四维度评分并给出结论，"
    "只输出 JSON。"
)

_REVIEW_PROMPT = """审核以下知识条目集合的整体质量。

评分维度（各 1-10 整数）：
- summary_quality   摘要质量（是否准确、信息密度、100-200 字）
- tag_accuracy      标签准确度（是否贴合内容、kebab-case）
- category_fit      分类合理性（open-source 是否恰当）
- consistency       一致性（字段完整、格式统一、与 URL 内容相符）

严格只输出如下 JSON（不要 markdown 围栏）：
{{
  "passed": false,
  "overall_score": 0.0,
  "feedback": "不通过时给出具体、可执行的改进建议；通过时可为空",
  "scores": {{"summary_quality": 0, "tag_accuracy": 0, "category_fit": 0, "consistency": 0}}
}}
其中 passed 为布尔值，overall_score 为四维度均分的 1-10 浮点数。

待审核条目：
{articles_json}"""


def review_node(state: KBState) -> dict:
    """LLM 四维度审核；iteration >= 2（第 3 轮）强制通过防死循环。

    解析失败按 fail-open 处理（视为通过并给出说明），配合 iteration
    上限兜底，保证图一定能走到 save。
    """
    articles = state.get("articles") or []
    iteration = state.get("iteration", 0)
    logger.info(
        "[ReviewNode] 第 %d 轮审核（共 %d 条，上限 %d 轮）",
        iteration + 1, len(articles), MAX_REVIEW_ITERATIONS,
    )

    tracker = dict(state.get("cost_tracker") or {})
    result: Optional[Dict[str, Any]] = None

    # 强制放行条件：达到审核轮次上限，或无条目可审（空跑）
    if iteration >= MAX_REVIEW_ITERATIONS - 1:
        logger.warning(
            "[ReviewNode] iteration=%d 达到上限，强制通过（优雅降级）", iteration
        )
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
        }
    if not articles:
        logger.info("[ReviewNode] 无条目可审，直接通过")
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
        }

    # 精简条目送审（报告式通信：只送审核需要的字段）
    slim = [
        {k: a.get(k) for k in ("id", "title", "url", "category", "summary", "tags")}
        for a in articles
    ]
    prompt = _REVIEW_PROMPT.format(
        articles_json=json.dumps(slim, ensure_ascii=False, indent=2)
    )
    parsed, usage = chat_json(prompt, system=_REVIEW_SYSTEM)
    tracker = accumulate_usage(tracker, usage, node="review_node")

    if isinstance(parsed, dict) and isinstance(parsed.get("scores"), dict):
        result = parsed
    else:
        logger.warning("[ReviewNode] 审核结果解析失败，按通过处理（fail-open）")

    passed = bool(result and result.get("passed"))
    feedback = str((result or {}).get("feedback") or "")
    scores = (result or {}).get("scores") or {}

    logger.info(
        "[ReviewNode] 完成：passed=%s，scores=%s",
        passed,
        json.dumps(scores, ensure_ascii=False),
    )
    return {
        "review_passed": passed,
        "review_feedback": feedback if not passed else "",
        "iteration": iteration + 1,
        "cost_tracker": tracker,
    }


# --------------------------------------------------------------------------- #
# 节点 5：save_node
# --------------------------------------------------------------------------- #
def save_node(state: KBState) -> dict:
    """把 articles 写入 knowledge/articles/ 并更新 index.json。

    完全对齐现有契约：
    - 文件名 ``{date}-{source}-{slug}.json``（slugify 同 pipeline）
    - article 12 字段（schemas/article.schema.json）
    - index.json ``{updated_at, total_count, articles:[9字段]}``，按
      organized_at 倒序
    - 按 id 查重（幂等：重复运行只追加新条目）

    WORKFLOWS_DRY_RUN=1 时只打日志不落盘。
    """
    articles = state.get("articles") or []
    if not articles:
        logger.info("[SaveNode] 无条目需要保存")
        return {}

    date = today_str()
    organized_at = now_iso()
    logger.info("[SaveNode] 待保存 %d 条（dry_run=%s）", len(articles), DRY_RUN)

    index = read_json(INDEX_FILE, {})
    entries: List[Dict[str, Any]] = list(index.get("articles") or [])
    existing_ids = {e.get("id") for e in entries}

    saved, skipped = 0, 0
    for article in articles:
        if article.get("id") in existing_ids:
            skipped += 1
            logger.info("[SaveNode] 跳过已存在条目 %r", article.get("id"))
            continue

        filename = f"{date}-{article['source']}-{slugify(article['title'])}.json"
        if not DRY_RUN:
            write_json(ARTICLES_DIR / filename, article)
            logger.info("[SaveNode] 写入 %s", filename)
        saved += 1
        entries.append(
            {
                "id": article["id"],
                "title": article["title"],
                "source": article["source"],
                "url": article["url"],
                "category": article["category"],
                "file": filename,
                "tags": article["tags"],
                "relevance_score": article["relevance_score"],
                "organized_at": organized_at,
            }
        )
        existing_ids.add(article["id"])

    if saved and not DRY_RUN:
        entries.sort(key=lambda e: e.get("organized_at", ""), reverse=True)
        write_json(
            INDEX_FILE,
            {
                "updated_at": organized_at,
                "total_count": len(entries),
                "articles": entries,
            },
        )
        logger.info("[SaveNode] index.json 已更新，total_count=%d", len(entries))

    logger.info("[SaveNode] 完成：新写入 %d，跳过 %d", saved, skipped)
    return {}


# --------------------------------------------------------------------------- #
# 自测入口：无 LangGraph 手动串联五个节点（图接线是下一节内容）
# --------------------------------------------------------------------------- #
def _run_smoke(limit: int) -> None:
    """端到端串联：collect → analyze → organize ⇄ review → save。"""
    state: KBState = {
        "sources": [],
        "analyses": [],
        "articles": [],
        "review_feedback": "",
        "review_passed": False,
        "iteration": 0,
        "cost_tracker": {},
    }
    globals()["DEFAULT_LIMIT"] = limit  # 自测允许 --limit 覆盖

    state.update(collect_node(state))
    if not state["sources"]:
        logger.error("采集为空，自测终止")
        return
    state.update(analyze_node(state))
    state.update(organize_node(state))

    # 审核循环（organize ⇄ review，最多 MAX_REVIEW_ITERATIONS 轮）
    while True:
        state.update(review_node(state))
        if state["review_passed"]:
            logger.info("审核通过（iteration=%d），进入保存", state["iteration"])
            break
        logger.info("审核未通过，带反馈重整理...")
        state.update(organize_node(state))

    state.update(save_node(state))

    tracker = state["cost_tracker"]
    print("\n=== 冒烟结果 ===")
    print(f"sources        : {len(state['sources'])}")
    print(f"analyses       : {len(state['analyses'])}")
    print(f"articles       : {len(state['articles'])}")
    print(f"review_passed  : {state['review_passed']} (iteration={state['iteration']})")
    print(f"cost_tracker   : {json.dumps(tracker, ensure_ascii=False)}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    import argparse

    parser = argparse.ArgumentParser(description="workflows/nodes.py 节点冒烟自测")
    parser.add_argument("--limit", type=int, default=2, help="采集条数（默认 2，控成本）")
    args = parser.parse_args()

    _run_smoke(args.limit)

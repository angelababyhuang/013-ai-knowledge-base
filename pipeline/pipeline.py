#!/usr/bin/env python3
"""pipeline/pipeline.py — 四步知识库自动化流水线。

把原先由「主 Agent → Subagent → Skill」驱动、靠 LLM 执行的
采集 → 分析 → 整理 → 保存流程固化为可直接运行的 Python 流水线：

    Step1 Collect   按 --sources 采 GitHub / HN ──▶ knowledge/raw/{source}-{date}.json
    Step2 Analyze   每条 raw item 调 LLM        ──▶ knowledge/enriched/{source}-{date}.enriched.json
    Step3 Organize  四规则门控 + url 去重        ──▶ 通过集 / 丢弃集
    Step4 Save      12 字段格式化 + 索引         ──▶ knowledge/articles/{date}-{source}-{slug}.json
                                                    + index.json + _filtered-{date}.json

产出严格对齐 schemas/article.schema.json（12 字段契约）与 organizer 的
命名 / 门控 / index 规则；LLM 调用复用同目录 model_client.py。

用法:
    python pipeline/pipeline.py --sources github,hn --limit 5
    python pipeline/pipeline.py --sources hn --limit 10 --dry-run --verbose
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from model_client import create_provider, chat_with_retry

logger = logging.getLogger("pipeline")

# --------------------------------------------------------------------------- #
# 路径常量
# --------------------------------------------------------------------------- #
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "knowledge" / "raw"
ENRICHED_DIR = PROJECT_ROOT / "knowledge" / "enriched"
ARTICLES_DIR = PROJECT_ROOT / "knowledge" / "articles"
INDEX_FILE = ARTICLES_DIR / "index.json"
VALIDATE_HOOK = PROJECT_ROOT / "hooks" / "validate_json.py"

# --------------------------------------------------------------------------- #
# 源映射与默认值
# --------------------------------------------------------------------------- #
SOURCE_MAP = {"github": "github-hot-repos", "hn": "hackernews-top"}
DEFAULT_LIMITS = {"github-hot-repos": 20, "hackernews-top": 10}

# --------------------------------------------------------------------------- #
# GitHub 采集常量（对齐 .opencode/skills/github-hot-repos/SKILL.md）
# --------------------------------------------------------------------------- #
GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
GITHUB_QUERY = 'AI OR LLM OR agent OR "large language model" OR RAG OR MCP'
GITHUB_MAX_RETRIES = 3
RATE_LIMIT_WAIT_CAP = 120.0  # 单次限流等待上限（秒），避免长时间挂起

# --------------------------------------------------------------------------- #
# HN 采集常量（对齐 .opencode/skills/hackernews-top/SKILL.md）
# --------------------------------------------------------------------------- #
HN_TOPSTORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
HN_DISCUSSION_URL = "https://news.ycombinator.com/item?id={item_id}"
HN_TOP_N = 50
HN_KEYWORDS = re.compile(
    r"\b(ai|llm|llms|agent|agents|agentic|gpt|chatgpt|claude|openai|anthropic|"
    r"gemini|deepseek|qwen|rag|mcp|transformers?|diffusion|language models?|"
    r"machine learning|neural|inference|copilot|multimodal|fine-?tun\w*)\b",
    re.IGNORECASE,
)
CODE_HOSTS = ("github.com", "gitlab.com", "bitbucket.org")
PAPER_HINT = re.compile(
    r"\b(pdf|paper|talk|slides|lecture|keynote)\b", re.IGNORECASE
)
# schema 契约：tags 必须全小写 kebab-case（^[a-z0-9]+(-[a-z0-9]+)*$）
TAG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# --------------------------------------------------------------------------- #
# 评分常量（对齐 .opencode/skills/tech-summary/SKILL.md）
# --------------------------------------------------------------------------- #
SCORE_WEIGHTS = {
    "tech_depth": 0.25,
    "practical_value": 0.30,
    "timeliness": 0.20,
    "community_heat": 0.15,
    "domain_match": 0.10,
}
CATEGORY_CAPS = {
    "paper-or-talk": {"practical_value": 0.5},
    "article-or-news": {"tech_depth": 0.5, "practical_value": 0.3},
}
VALID_CATEGORIES = ("open-source", "paper-or-talk", "article-or-news")

# --------------------------------------------------------------------------- #
# 门控常量（对齐 .opencode/agents/organizer.md）
# --------------------------------------------------------------------------- #
SCORE_GATE = 0.6
SUMMARY_MIN_LEN = 50
TAGS_MIN_COUNT = 2

SLUG_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on",
    "with", "is", "are", "by", "at", "as", "from",
}


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    """当前 UTC 时间，ISO 8601（YYYY-MM-DDTHH:mm:ssZ）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def read_json(path: Path, default: Any) -> Any:
    """读取 JSON 文件；不存在或解析失败返回 default。"""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("读取 %s 失败（%s），按空处理", path, exc)
        return default


def write_json(path: Path, data: Any) -> None:
    """2 空格缩进、UTF-8、中文不转义落盘。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


class ErrorLog:
    """errors-{date}.json 穷举式错误记录（内存累积，结束统一落盘）。"""

    def __init__(self, date: str, dry_run: bool) -> None:
        self.path = RAW_DIR / f"errors-{date}.json"
        self.dry_run = dry_run
        self.records: list[dict[str, Any]] = []

    def add(self, source: str, url: str, error: str) -> None:
        record = {
            "source": source,
            "url": url,
            "error": error,
            "timestamp": now_iso(),
        }
        self.records.append(record)
        logger.warning("[errors] %s | %s | %s", source, url, error)

    def flush(self) -> None:
        if self.dry_run or not self.records:
            return
        existing = read_json(self.path, [])
        if not isinstance(existing, list):
            existing = []
        write_json(self.path, existing + self.records)
        logger.info("errors 已追加 %d 条 -> %s", len(self.records), self.path)


# --------------------------------------------------------------------------- #
# Step 1 Collect — GitHub
# --------------------------------------------------------------------------- #
def _github_request(client: httpx.Client, params: dict[str, Any],
                    errors: ErrorLog) -> Optional[dict[str, Any]]:
    """带认证头与限流重试的 GitHub Search 请求；失败记 errors 返回 None。"""
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        logger.warning("未配置 GITHUB_TOKEN，未认证限额 60 次/小时")

    for attempt in range(GITHUB_MAX_RETRIES):
        try:
            resp = client.get(GITHUB_SEARCH_URL, params=params,
                              headers=headers)
        except httpx.HTTPError as exc:
            errors.add("github-hot-repos", GITHUB_SEARCH_URL,
                       f"网络层失败: {exc}")
            return None

        if resp.status_code in (403, 429):
            reset = resp.headers.get("X-RateLimit-Reset")
            wait = 5.0 * (attempt + 1)
            if reset and reset.isdigit():
                wait = min(max(int(reset) - time.time(), 1.0),
                           RATE_LIMIT_WAIT_CAP)
            logger.warning("GitHub 限流 %d (attempt %d/%d)，等待 %.0fs",
                           resp.status_code, attempt + 1,
                           GITHUB_MAX_RETRIES, wait)
            time.sleep(wait)
            continue

        if resp.status_code != 200:
            errors.add("github-hot-repos", str(resp.url),
                       f"HTTP {resp.status_code}: {resp.text[:200]}")
            return None

        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            errors.add("github-hot-repos", GITHUB_SEARCH_URL,
                       f"响应解析失败: {exc}")
            return None
        if not isinstance(data.get("items"), list):
            errors.add("github-hot-repos", GITHUB_SEARCH_URL,
                       "响应解析失败: 缺少 items[]")
            return None
        return data

    errors.add("github-hot-repos", GITHUB_SEARCH_URL, "限流耗尽: 重试 3 次仍 403/429")
    return None


def collect_github(limit: int, errors: ErrorLog,
                   client: httpx.Client) -> list[dict[str, Any]]:
    """采集 GitHub 热门 AI 仓库，返回 raw items（字段对齐 skill 提取表）。"""
    params = {
        "q": GITHUB_QUERY,
        "sort": "stars",
        "order": "desc",
        "per_page": limit,
    }
    data = _github_request(client, params, errors)
    if data is None:
        return []

    items: list[dict[str, Any]] = []
    collected_at = now_iso()
    for repo in data["items"]:
        item = {
            "id": repo.get("full_name"),
            "title": repo.get("name"),
            "source": "github-hot-repos",
            "collected_at": collected_at,
            "description": repo.get("description"),
            "url": repo.get("html_url"),
            "stars": repo.get("stargazers_count"),
            "language": repo.get("language"),
            "topics": repo.get("topics") or [],
            "created_at": repo.get("created_at"),
            "updated_at": repo.get("pushed_at"),
        }
        missing = [k for k in ("id", "title", "url") if not item[k]]
        if missing:
            fallback_url = str(item.get("url") or GITHUB_SEARCH_URL)
            errors.add("github-hot-repos", fallback_url,
                       f"必填字段缺失: {missing}")
            continue
        items.append(item)
    logger.info("[github] 采集到 %d 条", len(items))
    return items


# --------------------------------------------------------------------------- #
# Step 1 Collect — Hacker News
# --------------------------------------------------------------------------- #
def _hn_get(client: httpx.Client, url: str, errors: ErrorLog) -> Optional[Any]:
    """HN 请求；失败记 errors 返回 None。"""
    try:
        resp = client.get(url)
    except httpx.HTTPError as exc:
        errors.add("hackernews-top", url, f"网络层失败: {exc}")
        return None
    if resp.status_code != 200:
        errors.add("hackernews-top", url, f"HTTP {resp.status_code}")
        return None
    try:
        return resp.json()
    except json.JSONDecodeError as exc:
        errors.add("hackernews-top", url, f"响应解析失败: {exc}")
        return None


def collect_hn(limit: int, errors: ErrorLog,
               client: httpx.Client) -> list[dict[str, Any]]:
    """采集 HN Top Stories：关键词过滤 + 分层筛选 + URL 回填。

    category 此处仅做分层初步归集（open-source 候选 / AI 主题候选），
    最终 category 由 Step 2 的 LLM 判定（设计决策 D1）。
    """
    ids = _hn_get(client, HN_TOPSTORIES_URL, errors)
    if not isinstance(ids, list):
        return []

    stories: list[dict[str, Any]] = []
    for item_id in ids[:HN_TOP_N]:
        detail = _hn_get(client, HN_ITEM_URL.format(item_id=item_id), errors)
        if not isinstance(detail, dict):
            continue
        title = detail.get("title") or ""
        if not HN_KEYWORDS.search(title):
            continue
        url = detail.get("url")
        if not url:  # Ask HN / 纯文本帖回填讨论页
            url = HN_DISCUSSION_URL.format(item_id=item_id)
        stories.append({
            "id": str(detail.get("id")),
            "title": title,
            "url": url,
            "score": detail.get("score") or 0,
            "comments": detail.get("descendants") or 0,
            "author": detail.get("by"),
            "time": detail.get("time"),
        })

    # 分层筛选：open-source 候选优先，不足放宽到 AI 主题按 score 降序补足
    def is_code_host(story: dict[str, Any]) -> bool:
        return any(host in story["url"] for host in CODE_HOSTS)

    open_source = [s for s in stories if is_code_host(s)]
    fallback = sorted(
        (s for s in stories if not is_code_host(s)),
        key=lambda s: s["score"], reverse=True,
    )
    selected = open_source[:limit]
    if len(selected) < limit:
        selected.extend(fallback[: limit - len(selected)])

    collected_at = now_iso()
    items: list[dict[str, Any]] = []
    for story in selected:
        if is_code_host(story):
            category = "open-source"
        elif (PAPER_HINT.search(story["title"])
                or story["url"].endswith(".pdf")):
            category = "paper-or-talk"
        else:
            category = "article-or-news"
        item = {
            "id": story["id"],
            "title": story["title"],
            "source": "hackernews-top",
            "collected_at": collected_at,
            "url": story["url"],
            "score": story["score"],
            "comments": story["comments"],
            "author": story["author"],
            "time": story["time"],
            "category": category,  # 初步归集；Step 2 LLM 判定后可能覆盖
        }
        missing = [k for k in ("id", "title", "url") if not item[k]]
        if missing:
            errors.add("hackernews-top", story["url"],
                       f"必填字段缺失: {missing}")
            continue
        items.append(item)
    logger.info("[hn] 候选 %d 条，分层筛选后 %d 条", len(stories), len(items))
    return items


# --------------------------------------------------------------------------- #
# Step 1 — raw 幂等落盘
# --------------------------------------------------------------------------- #
def save_raw(source: str, date: str, items: list[dict[str, Any]],
             dry_run: bool) -> Path:
    """按 id 去重追加写入 knowledge/raw/{source}-{date}.json。"""
    path = RAW_DIR / f"{source}-{date}.json"
    existing = read_json(path, {})
    merged: dict[str, dict[str, Any]] = {}
    if isinstance(existing, dict):
        for old in existing.get("items", []):
            merged[old["id"]] = old
    for item in items:
        merged[item["id"]] = item
    payload = {
        "source": source,
        "collected_at": now_iso(),
        "count": len(merged),
        "items": list(merged.values()),
    }
    if not dry_run:
        write_json(path, payload)
    logger.info("[raw] %s 共 %d 条%s", path.name, len(merged),
                "（dry-run 未落盘）" if dry_run else "")
    return path


# --------------------------------------------------------------------------- #
# Step 2 Analyze
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT = (
    "你是 AI/LLM/Agent 领域技术知识库的分析员。对给定条目输出分析结果，"
    "只返回一个 JSON 对象，不要输出任何其他文字。JSON 字段：\n"
    '- "summary": 中文摘要 2-3 句（100-200 字），说清"它是什么、解决什么问题、'
    '为什么值得看"，不要照搬原文描述，要有信息增量\n'
    '- "tags": 英文 kebab-case 标签数组，3-5 个，全小写连字符分隔\n'
    '- "category": 三选一 "open-source" / "paper-or-talk" / "article-or-news"'
    "（开源仓库 / 论文或演讲 / 资讯或文章；仅 HN 条目需要，GitHub 条目可省略）\n"
    '- "tech_depth": 0.0-1.0 技术深度（底层原理/架构设计/算法创新）\n'
    '- "practical_value": 0.0-1.0 实用价值（工程师能否直接用于项目）\n'
    '- "timeliness": 0.0-1.0 时效性（最新趋势/近期发布）\n'
    '- "community_heat": 0.0-1.0 社区热度（Stars/Score/评论数）\n'
    '- "domain_match": 0.0-1.0 与 AI/LLM/Agent 核心领域的匹配度\n'
    "评分需客观、跨条目有梯度。"
)


def build_analysis_prompt(item: dict[str, Any]) -> str:
    """按源组装条目上下文。"""
    lines = [f"标题: {item['title']}", f"链接: {item['url']}"]
    if item["source"] == "github-hot-repos":
        lines.append(f"描述: {item.get('description') or '（无）'}")
        lines.append(f"Stars: {item.get('stars')}")
        lines.append(f"语言: {item.get('language')}")
        lines.append(f"Topics: {', '.join(item.get('topics') or [])}")
        lines.append("来源: GitHub 热门仓库")
    else:
        lines.append(f"HN 得分: {item.get('score')}，评论数: {item.get('comments')}")
        lines.append(f"初步分类: {item.get('category')}（请自行复核并给出最终 category）")
        lines.append("来源: Hacker News 热门")
    return "\n".join(lines)


def extract_json(text: str) -> Optional[dict[str, Any]]:
    """从 LLM 返回文本提取 JSON 对象（容忍 ```json 代码块包裹）。"""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else text
    if not candidate.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        candidate = text[start: end + 1]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def normalize_tags(tags: list[Any]) -> list[str]:
    """把 LLM 返回的 tags 规整为 schema 要求的 kebab-case，丢弃无法规整的项。

    LLM 可能返回 "Large Language Model" / "AI_Agents" 等非法形态，
    不规整会让 article 过不了 validate_json.py 的 tags pattern 校验。
    """
    normalized: list[str] = []
    for tag in tags:
        slug = re.sub(r"[^a-z0-9]+", "-", str(tag).lower()).strip("-")
        if slug and TAG_PATTERN.match(slug) and slug not in normalized:
            normalized.append(slug)
    return normalized


def _clamp01(value: Any) -> Optional[float]:
    """把 LLM 维度分钳制到 0.0-1.0；非法返回 None。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(min(max(float(value), 0.0), 1.0), 2)


def apply_category_caps(category: str, breakdown: dict[str, float]) -> None:
    """按 category 截断维度上限，超限维度记入 _override。"""
    caps = CATEGORY_CAPS.get(category)
    if not caps:
        return
    for dim, cap in caps.items():
        if breakdown.get(dim, 0.0) > cap:
            override = breakdown.setdefault("_override", {})
            override[dim] = (
                f"原值 {breakdown[dim]} 超出 {category} 上限 {cap}，已截断"
            )
            breakdown[dim] = cap


def compute_score(breakdown: dict[str, Any]) -> float:
    """五维加权 relevance_score，两位小数。"""
    score = sum(
        float(breakdown.get(dim, 0.0)) * weight
        for dim, weight in SCORE_WEIGHTS.items()
    )
    return round(min(max(score, 0.0), 1.0), 2)


def analyze_item(provider: Any, item: dict[str, Any],
                 errors: ErrorLog) -> Optional[dict[str, Any]]:
    """对单条 raw item 调 LLM，返回分析字段；失败记 errors 返回 None。"""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_analysis_prompt(item)},
    ]
    try:
        resp = chat_with_retry(provider, messages, temperature=0.3)
    except Exception as exc:  # noqa: BLE001 — 单条失败不中断整体
        errors.add(item["source"], item["url"], f"LLM 调用失败: {exc}")
        return None

    data = extract_json(resp.content)
    if data is None:
        errors.add(item["source"], item["url"],
                   f"LLM 返回 JSON 解析失败: {resp.content[:200]!r}")
        return None

    summary = data.get("summary")
    tags = data.get("tags")
    if not isinstance(summary, str) or not summary.strip():
        errors.add(item["source"], item["url"], "LLM 返回必填字段缺失: summary")
        return None
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        errors.add(item["source"], item["url"], "LLM 返回必填字段缺失: tags")
        return None
    tags = normalize_tags(tags)
    if not tags:
        errors.add(item["source"], item["url"],
                   "LLM 返回 tags 全部无法规整为 kebab-case")
        return None

    breakdown: dict[str, Any] = {}
    for dim in SCORE_WEIGHTS:
        value = _clamp01(data.get(dim))
        if value is None:
            errors.add(item["source"], item["url"],
                       f"LLM 返回维度分非法: {dim}={data.get(dim)!r}")
            return None
        breakdown[dim] = value

    # category：GitHub 恒 open-source；HN 以 LLM 判定为准（D1），非法值回退
    if item["source"] == "github-hot-repos":
        category = "open-source"
    else:
        category = data.get("category")
        if category not in VALID_CATEGORIES:
            fallback = item.get("category") or "article-or-news"
            breakdown["_override"] = {
                "category": f"LLM 返回非法 category {category!r}，回退 {fallback}"
            }
            category = fallback

    apply_category_caps(category, breakdown)
    return {
        "summary": summary.strip(),
        "tags": tags,
        "category": category,
        "relevance_score": compute_score(breakdown),
        "score_breakdown": breakdown,
    }


def analyze_all(provider: Any, items: list[dict[str, Any]],
                errors: ErrorLog) -> list[dict[str, Any]]:
    """逐条分析，返回增补了分析字段的 enriched items。"""
    enriched: list[dict[str, Any]] = []
    analyzed_at = now_iso()
    for index, item in enumerate(items, 1):
        logger.info("[analyze] (%d/%d) %s", index, len(items), item["title"])
        analysis = analyze_item(provider, item, errors)
        if analysis is None:
            continue
        merged = dict(item)
        merged.update(analysis)
        merged["analyzed_at"] = analyzed_at
        enriched.append(merged)
    logger.info("[analyze] 成功 %d / %d 条", len(enriched), len(items))
    return enriched


def save_enriched(source: str, date: str, items: list[dict[str, Any]],
                  dry_run: bool) -> Path:
    """幂等写 enriched：按 id 覆盖分析字段，不重复追加。"""
    path = ENRICHED_DIR / f"{source}-{date}.enriched.json"
    existing = read_json(path, {})
    merged: dict[str, dict[str, Any]] = {}
    if isinstance(existing, dict):
        for old in existing.get("items", []):
            merged[old["id"]] = old
    for item in items:
        merged[item["id"]] = item  # 同 id 覆盖（含 collector 原字段 + 新分析字段）
    payload = {
        "source": source,
        "collected_at": items[0]["collected_at"] if items else now_iso(),
        "analyzed_at": now_iso(),
        "count": len(merged),
        "items": list(merged.values()),
    }
    if not dry_run:
        write_json(path, payload)
    logger.info("[enriched] %s 共 %d 条%s", path.name, len(merged),
                "（dry-run 未落盘）" if dry_run else "")
    return path


# --------------------------------------------------------------------------- #
# Step 3 Organize — 门控 + 去重
# --------------------------------------------------------------------------- #
def gate_item(item: dict[str, Any]) -> Optional[str]:
    """四规则门控，返回丢弃原因；通过返回 None。"""
    if item.get("relevance_score", 0.0) < SCORE_GATE:
        return "relevance_score < 0.6"
    if len(item.get("summary", "")) < SUMMARY_MIN_LEN:
        return "summary too short"
    if len(item.get("tags", [])) < TAGS_MIN_COUNT:
        return "tags too few"
    if not str(item.get("url", "")).startswith("https://"):
        return "url invalid"
    return None


def load_existing_urls() -> set[str]:
    """articles/ 存量 url 集合（优先 index.json，缺失则扫描文件）。"""
    index = read_json(INDEX_FILE, {})
    if isinstance(index, dict) and isinstance(index.get("articles"), list):
        return {a["url"] for a in index["articles"] if a.get("url")}
    urls: set[str] = set()
    if ARTICLES_DIR.exists():
        for path in ARTICLES_DIR.glob("*.json"):
            if path.name.startswith("_") or path.name == "index.json":
                continue
            data = read_json(path, {})
            if isinstance(data, dict) and data.get("url"):
                urls.add(data["url"])
    return urls


def organize(items: list[dict[str, Any]],
             existing_urls: set[str]) -> tuple[list[dict[str, Any]],
                                               list[dict[str, Any]]]:
    """门控 + url 去重，返回 (通过集, 丢弃集)。"""
    passed: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []
    seen_urls = set(existing_urls)
    for item in items:
        reason = gate_item(item)
        if reason is None and item["url"] in seen_urls:
            reason = "duplicate url"
        if reason:
            record = {
                "url": item["url"],
                "source": item["source"],
                "reason": reason,
            }
            if reason == "relevance_score < 0.6":
                record["relevance_score"] = item.get("relevance_score")
            filtered.append(record)
            logger.info("[gate] 丢弃 %s — %s", item["url"], reason)
            continue
        seen_urls.add(item["url"])
        passed.append(item)
    logger.info("[organize] 通过 %d 条，丢弃 %d 条", len(passed), len(filtered))
    return passed, filtered


# --------------------------------------------------------------------------- #
# Step 4 Save — article / index / _filtered
# --------------------------------------------------------------------------- #
def slugify(title: str) -> str:
    """title → 全小写连字符 slug，去停用词。"""
    words = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-").split("-")
    slug = "-".join(w for w in words if w and w not in SLUG_STOPWORDS)
    return slug or "untitled"


def build_meta(item: dict[str, Any]) -> dict[str, Any]:
    """meta 透传：GitHub 与 HN 各自按 organizer 约定的字段集组装。"""
    if item["source"] == "github-hot-repos":
        return {
            "stars": item.get("stars"),
            "language": item.get("language"),
            "topics": item.get("topics") or [],
            "pushed_at": item.get("updated_at"),
        }
    return {
        "author": item.get("author"),
        "comments": item.get("comments"),
        "time": item.get("time"),
    }


def build_article(item: dict[str, Any], organized_at: str) -> dict[str, Any]:
    """12 字段标准知识条目（剥离 score_breakdown，补 organized_at / meta）。"""
    return {
        "id": item["id"],
        "title": item["title"],
        "source": item["source"],
        "url": item["url"],
        "category": item["category"],
        "collected_at": item["collected_at"],
        "analyzed_at": item["analyzed_at"],
        "organized_at": organized_at,
        "summary": item["summary"],
        "tags": item["tags"],
        "relevance_score": item["relevance_score"],
        "meta": build_meta(item),
    }


def save_articles(date: str, items: list[dict[str, Any]],
                  dry_run: bool) -> list[Path]:
    """落盘 article 并更新 index.json，返回当日新 article 路径。"""
    organized_at = now_iso()
    index = read_json(INDEX_FILE, {})
    entries: list[dict[str, Any]] = []
    if isinstance(index, dict) and isinstance(index.get("articles"), list):
        entries = list(index["articles"])

    written: list[Path] = []
    for item in items:
        article = build_article(item, organized_at)
        filename = f"{date}-{item['source']}-{slugify(item['title'])}.json"
        path = ARTICLES_DIR / filename
        if not dry_run:
            write_json(path, article)
        written.append(path)
        entries.append({
            "id": article["id"],
            "title": article["title"],
            "source": article["source"],
            "url": article["url"],
            "category": article["category"],
            "file": filename,
            "tags": article["tags"],
            "relevance_score": article["relevance_score"],
            "organized_at": organized_at,
        })
        logger.info("[save] %s", filename)

    entries.sort(key=lambda e: e.get("organized_at", ""), reverse=True)
    if not dry_run and items:
        write_json(INDEX_FILE, {
            "updated_at": organized_at,
            "total_count": len(entries),
            "articles": entries,
        })
        logger.info("[index] total_count=%d", len(entries))
    return written


def save_filtered(date: str, filtered: list[dict[str, Any]],
                  dry_run: bool) -> None:
    """丢弃集追加写 articles/_filtered-{date}.json。"""
    if dry_run or not filtered:
        return
    path = ARTICLES_DIR / f"_filtered-{date}.json"
    existing = read_json(path, [])
    if not isinstance(existing, list):
        existing = []
    write_json(path, existing + filtered)
    logger.info("[filtered] %s 追加 %d 条", path.name, len(filtered))


# --------------------------------------------------------------------------- #
# 事后校验（设计决策 D2）
# --------------------------------------------------------------------------- #
def run_validation(paths: list[Path]) -> None:
    """subprocess 调 hooks/validate_json.py 校验当日新 article，失败仅警告。"""
    if not paths:
        return
    cmd = [sys.executable, str(VALIDATE_HOOK)] + [str(p) for p in paths]
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True,
                            text=True)
    if result.returncode == 0:
        logger.info("[validate] %d 个新 article 全部通过校验", len(paths))
    else:
        logger.warning("[validate] 校验发现问题（不中断，请人工排查）:\n%s%s",
                       result.stdout, result.stderr)


# --------------------------------------------------------------------------- #
# CLI 与主流程
# --------------------------------------------------------------------------- #
def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI 知识库四步流水线：Collect → Analyze → Organize → Save"
    )
    parser.add_argument(
        "--sources", default="github,hn",
        help="逗号分隔数据源：github / hn（默认 github,hn）",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="每源采集条数上限（默认 GitHub 20 / HN 10）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="采集+分析照常但不落任何文件，仅打印预览",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="输出 DEBUG 级日志",
    )
    parser.add_argument(
        "--no-validate", action="store_true",
        help="跳过保存后的 validate_json.py 事后校验",
    )
    return parser.parse_args(argv[1:])


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    date = today_str()
    errors = ErrorLog(date, args.dry_run)

    sources: list[str] = []
    for name in args.sources.split(","):
        name = name.strip().lower()
        if name not in SOURCE_MAP:
            logger.error("未知数据源 %r（可选: github / hn）", name)
            return 2
        if SOURCE_MAP[name] not in sources:
            sources.append(SOURCE_MAP[name])

    # ---- Step 1 Collect ----
    raw_items: list[dict[str, Any]] = []
    with httpx.Client(timeout=30.0) as client:
        for source in sources:
            if args.limit is not None:
                limit = args.limit
            else:
                limit = DEFAULT_LIMITS[source]
            if source == "github-hot-repos":
                items = collect_github(limit, errors, client)
            else:
                items = collect_hn(limit, errors, client)
            save_raw(source, date, items, args.dry_run)
            raw_items.extend(items)

    if not raw_items:
        logger.warning("未采集到任何条目，流程结束")
        errors.flush()
        return 1

    # ---- Step 2 Analyze ----
    try:
        provider = create_provider()
    except (ValueError, RuntimeError) as exc:
        logger.error("LLM provider 初始化失败: %s", exc)
        errors.flush()
        return 2
    enriched_items = analyze_all(provider, raw_items, errors)
    for source in sources:
        source_items = [i for i in enriched_items if i["source"] == source]
        if source_items:
            save_enriched(source, date, source_items, args.dry_run)

    # ---- Step 3 Organize ----
    existing_urls = load_existing_urls()
    passed, filtered = organize(enriched_items, existing_urls)

    # ---- Step 4 Save ----
    written = save_articles(date, passed, args.dry_run)
    save_filtered(date, filtered, args.dry_run)
    errors.flush()

    # ---- 事后校验（非 dry-run）----
    if not args.dry_run and not args.no_validate:
        run_validation(written)

    # ---- 汇总 / dry-run 预览 ----
    print()
    print("=" * 64)
    print(f"采集 {len(raw_items)} 条 | 分析成功 {len(enriched_items)} 条 | "
          f"过门控 {len(passed)} 条 | 丢弃 {len(filtered)} 条")
    if args.dry_run:
        print("[dry-run] 未落盘任何文件。将写入的 article 清单：")
        for path in written:
            print(f"  - {path.name}")
        if errors.records:
            print(f"[dry-run] 将记录 {len(errors.records)} 条 errors")
    else:
        print(f"raw/enriched/articles 已落盘（日期 {date}）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

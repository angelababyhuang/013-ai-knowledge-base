#!/usr/bin/env python3
"""Router 路由模式：两层意图分类 + 三处理器分发。

第一层（零成本）：关键词快速匹配，命中即路由，不调 LLM。
第二层（兜底）：LLM 意图分类，处理关键词未命中的模糊输入。

三种意图各自对应一个处理器：

- ``github_search``    调用 GitHub Search API（urllib.request，query 经 urllib.parse.quote 编码）
- ``knowledge_query``  从本地 ``knowledge/articles/index.json`` 检索
- ``general_chat``     调 LLM 直接回答

统一入口 ``route(query) -> str``。

LLM 调用复用 ``pipeline/model_client.py``：
- 文本生成走 ``quick_chat``（一句话返回模型文本）；
- 课程里的 ``chat_json`` 在本项目不存在，这里用 ``quick_chat`` + ``json.loads``
  自行解析（``_llm_json``），失败回退到安全默认值，等价于一个"软 chat_json"。

用法::

    from patterns.router import route
    print(route("帮我找 github 上的 agent 框架"))

也可直接运行本模块做自测::

    python patterns/router.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from pipeline.model_client import quick_chat  # noqa: E402

logger = logging.getLogger("router")

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
GITHUB_API = "https://api.github.com/search/repositories"
INDEX_FILE = _PROJECT_ROOT / "knowledge" / "articles" / "index.json"

INTENTS = ("github_search", "knowledge_query", "general_chat")

KEYWORD_RULES: Dict[str, List[str]] = {
    "github_search": [
        "github", "repo", "repository", "仓库", "开源项目", "开源",
        "star", "stars",
    ],
    "knowledge_query": [
        "知识库", "本地", "整理过", "整理的", "收藏", "之前采",
        "记不记得", "库里",
    ],
}

MAX_KNOWLEDGE_HITS = 5
DEFAULT_GITHUB_QUERY = "AI agent"


# --------------------------------------------------------------------------- #
# 第一层：关键词分类（零成本）
# --------------------------------------------------------------------------- #
def classify_by_keyword(query: str) -> Optional[str]:
    """关键词快速匹配。命中返回意图名，未命中返回 None。"""
    lowered = query.lower()
    for intent, keywords in KEYWORD_RULES.items():
        if any(kw.lower() in lowered for kw in keywords):
            return intent
    return None


# --------------------------------------------------------------------------- #
# 第二层：LLM 分类兜底
# --------------------------------------------------------------------------- #
_CLASSIFY_PROMPT = (
    "判断用户问题的意图，只返回以下三个标签之一，不要任何多余文字：\n"
    "- github_search：想搜索 GitHub 上的开源仓库/项目\n"
    "- knowledge_query：想查询本地知识库里已整理的内容\n"
    "- general_chat：其它闲聊或通用问题\n\n"
    "用户问题：{query}\n标签："
)


def classify_by_llm(query: str) -> str:
    """LLM 意图分类。解析失败或越界时安全回退到 general_chat。"""
    prompt = _CLASSIFY_PROMPT.format(query=query)
    raw = quick_chat(prompt, temperature=0.0).strip().lower()
    for intent in INTENTS:
        if intent in raw:
            return intent
    logger.warning("LLM 分类未命中已知意图，原始返回 %r，回退 general_chat", raw)
    return "general_chat"


def _llm_json(prompt: str, fallback: Any) -> Any:
    """软 chat_json：让 LLM 只输出 JSON 并解析；失败返回 fallback。

    项目无 chat_json，这里剥离 ``` 代码围栏后 json.loads 兜底。
    """
    raw = quick_chat(prompt, temperature=0.0).strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].lstrip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("LLM JSON 解析失败，原始 %r，使用 fallback", raw)
        return fallback


# --------------------------------------------------------------------------- #
# 处理器 1：github_search
# --------------------------------------------------------------------------- #
def _extract_search_term(query: str) -> str:
    """从自然语言里剥离触发关键词，剩下的作为搜索词。"""
    term = query.lower()
    for kw in KEYWORD_RULES["github_search"]:
        term = term.replace(kw.lower(), " ")
    for ch in "帮我找一下的上有里请麻烦？?":
        term = term.replace(ch, " ")
    term = term.strip()
    return term or DEFAULT_GITHUB_QUERY


def handle_github_search(query: str) -> str:
    """调用 GitHub Search API，返回热门仓库清单（urllib.request）。"""
    term = _extract_search_term(query)
    encoded_q = urllib.parse.quote(term)
    url = (
        f"{GITHUB_API}?q={encoded_q}"
        "&sort=stars&order=desc&per_page=5"
    )
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    logger.info("[github_search] 搜索 %r -> %s", term, url)
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError) as exc:
        logger.error("GitHub API 请求失败: %s", exc)
        return f"GitHub 搜索失败：{exc}"
    except json.JSONDecodeError as exc:
        logger.error("GitHub 响应解析失败: %s", exc)
        return f"GitHub 响应解析失败：{exc}"

    items: List[Dict[str, Any]] = data.get("items", [])
    if not items:
        return f"未找到与「{term}」相关的仓库。"

    total = data.get("total_count", len(items))
    lines = [f"GitHub 搜索「{term}」共 {total} 个，Top {len(items)}："]
    for idx, item in enumerate(items, 1):
        lines.append(
            f"{idx}. {item.get('full_name')}  ★{item.get('stargazers_count')}\n"
            f"   {item.get('description') or '（无描述）'}\n"
            f"   {item.get('html_url')}"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 处理器 2：knowledge_query
# --------------------------------------------------------------------------- #
def _tokenize(query: str) -> List[str]:
    cleaned = query.lower()
    for ch in "，。、,.!?？：:的帮我在从找查一下请有没有":
        cleaned = cleaned.replace(ch, " ")
    return [t for t in cleaned.split() if len(t) >= 2]


def handle_knowledge_query(query: str) -> str:
    """从本地 index.json 按标题/标签命中检索。"""
    if not INDEX_FILE.exists():
        return f"知识库索引不存在：{INDEX_FILE}"

    try:
        index = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.error("index.json 解析失败: %s", exc)
        return f"知识库索引解析失败：{exc}"

    articles: List[Dict[str, Any]] = index.get("articles", [])
    tokens = _tokenize(query)
    if not tokens:
        tokens = [query.strip().lower()]

    scored: List[tuple[int, Dict[str, Any]]] = []
    for art in articles:
        title = (art.get("title") or "").lower()
        tags = " ".join(art.get("tags") or []).lower()
        haystack = f"{title} {tags}"
        score = sum(1 for t in tokens if t in haystack)
        if score > 0:
            scored.append((score, art))

    if not scored:
        return f"知识库中未找到与「{query}」相关的条目。"

    scored.sort(key=lambda x: x[0], reverse=True)
    hits = scored[:MAX_KNOWLEDGE_HITS]
    lines = [f"知识库命中 {len(hits)} 条（共 {index.get('total_count', len(articles))}）："]
    for score, art in hits:
        tags = ", ".join(art.get("tags") or [])
        lines.append(
            f"- [{art.get('relevance_score'):.2f}] {art.get('title')}\n"
            f"  tags: {tags}\n  {art.get('url')}"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 处理器 3：general_chat
# --------------------------------------------------------------------------- #
def handle_general_chat(query: str) -> str:
    """直接调 LLM 回答。"""
    return quick_chat(query)


# --------------------------------------------------------------------------- #
# 路由总入口
# --------------------------------------------------------------------------- #
HANDLERS = {
    "github_search": handle_github_search,
    "knowledge_query": handle_knowledge_query,
    "general_chat": handle_general_chat,
}


def route(query: str) -> str:
    """统一入口：两层分类 → 分发到对应处理器。

    第一层关键词命中则零成本路由；否则第二层 LLM 兜底分类。
    """
    query = (query or "").strip()
    if not query:
        return "请输入你的问题。"

    intent = classify_by_keyword(query)
    if intent is None:
        logger.info("[layer1] 关键词未命中，回退 LLM 分类")
        intent = classify_by_llm(query)
    logger.info("[route] %r -> %s", query, intent)

    return HANDLERS[intent](query)


# --------------------------------------------------------------------------- #
# 自测入口
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    samples = [
        "帮我找 github 上的 agent 框架",
        "知识库里有没有关于 RAG 的整理",
        "用一句话解释什么是 LLM Agent",
    ]
    for q in samples:
        print("=" * 70)
        print("Q:", q)
        print("-" * 70)
        try:
            print(route(q))
        except Exception as exc:
            logger.error("路由处理异常: %s", exc)
            print(f"处理失败：{exc}")
        print()

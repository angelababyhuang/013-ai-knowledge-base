#!/usr/bin/env python3
"""MCP Server：搜索本地 AI 知识库（knowledge/articles/）。

JSON-RPC 2.0 over stdio（换行分隔 JSON），纯 Python 标准库，无第三方依赖。
协议约定：stdout 只写协议 JSON（一行一个消息），日志一律走 stderr。
"""

import json
import logging
import sys
from collections import Counter
from pathlib import Path

# ---------- 路径与日志 ----------

PROJECT_ROOT = Path(__file__).resolve().parent
ARTICLES_DIR = PROJECT_ROOT / "knowledge" / "articles"

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("mcp-knowledge-server")

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "mcp-knowledge-server", "version": "1.0.0"}

# 文章必备字段（字段校验）：四者皆非空才算真·文章，自动排除 index/_filtered/test 等
REQUIRED_FIELDS = ("id", "title", "summary", "source")

# 非文章文件兜底：hook-test.json 恰好满足字段校验，按文件名守卫排除
def _is_article_filename(name: str) -> bool:
    if name == "index.json":
        return False
    if name.startswith("_"):
        return False
    # 按 - / _ / . 切词匹配 "test"，避免误伤 slug 含 latest/protest 的合法文章
    tokens = name.replace("-", " ").replace("_", " ").replace(".", " ").split()
    if "test" in tokens:
        return False
    return True


# ---------- 数据加载 ----------

_ARTICLES: list = []


def load_articles() -> list:
    """扫描 knowledge/articles/*.json，字段校验识别文章，缓存到内存。"""
    articles = []
    if not ARTICLES_DIR.is_dir():
        log.warning("articles 目录不存在: %s", ARTICLES_DIR)
        return articles
    for path in sorted(ARTICLES_DIR.glob("*.json")):
        if not _is_article_filename(path.name):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("跳过无法解析的文件 %s: %s", path.name, exc)
            continue
        if not isinstance(data, dict):
            continue
        if all(data.get(f) for f in REQUIRED_FIELDS):
            articles.append(data)
    log.info("已加载 %d 篇文章（来自 %s）", len(articles), ARTICLES_DIR)
    return articles


def reload_articles() -> None:
    global _ARTICLES
    _ARTICLES = load_articles()


# ---------- 三个工具 ----------

def search_articles(keyword: str, limit: int = 5) -> list:
    """按关键词搜 title+summary，title 命中优先，同组按 relevance_score 降序。"""
    kw = keyword.lower()

    def _score(article: dict) -> float:
        value = article.get("relevance_score")
        return value if isinstance(value, (int, float)) else 0.0

    title_hits = []
    summary_hits = []
    for article in _ARTICLES:
        title = str(article.get("title", "")).lower()
        summary = str(article.get("summary", "")).lower()
        if kw in title:
            title_hits.append(article)
        elif kw in summary:
            summary_hits.append(article)
    title_hits.sort(key=_score, reverse=True)
    summary_hits.sort(key=_score, reverse=True)

    slim_keys = ("id", "title", "source", "url", "summary", "tags",
                 "relevance_score", "category")
    return [
        {k: a.get(k) for k in slim_keys}
        for a in (title_hits + summary_hits)[:limit]
    ]


def get_article(article_id: str):
    """按 id 精确匹配，返回完整 article；未命中返回未找到提示。"""
    for article in _ARTICLES:
        if article.get("id") == article_id:
            return article
    return {"found": False, "message": f"未找到 id 为 {article_id!r} 的文章"}


def knowledge_stats() -> dict:
    """总数 / 来源分布 / 热门标签 / 平均相关性。"""
    by_source = Counter()
    tag_counter = Counter()
    scores = []
    for article in _ARTICLES:
        by_source[article.get("source", "unknown")] += 1
        tags = article.get("tags")
        if isinstance(tags, list):
            tag_counter.update(str(t) for t in tags)
        value = article.get("relevance_score")
        if isinstance(value, (int, float)):
            scores.append(value)
    avg = round(sum(scores) / len(scores), 2) if scores else 0.0
    return {
        "total": len(_ARTICLES),
        "by_source": dict(by_source),
        "top_tags": [
            {"tag": tag, "count": count}
            for tag, count in tag_counter.most_common(10)
        ],
        "avg_relevance_score": avg,
    }


TOOLS = [
    {
        "name": "search_articles",
        "description": "按关键词搜索知识库文章的标题与摘要，title 命中优先、relevance_score 降序。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词（大小写不敏感，子串匹配）"},
                "limit": {"type": "integer", "description": "返回条数上限，默认 5", "default": 5},
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_article",
        "description": "按文章 id 精确获取完整知识条目（12 字段）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "article_id": {"type": "string", "description": "文章 id（如 mikehasa/agentacct）"},
            },
            "required": ["article_id"],
        },
    },
    {
        "name": "knowledge_stats",
        "description": "知识库统计：总数、来源分布、热门标签、平均相关性评分。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

_TOOL_HANDLERS = {
    "search_articles": search_articles,
    "get_article": get_article,
    "knowledge_stats": knowledge_stats,
}


# ---------- JSON-RPC 层 ----------

class JsonRpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _call_tool(name: str, arguments):
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        raise JsonRpcError(-32602, f"Unknown tool: {name!r}")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise JsonRpcError(-32602, "arguments 必须是 object")

    if name == "search_articles":
        keyword = arguments.get("keyword")
        if not isinstance(keyword, str) or not keyword:
            raise JsonRpcError(-32602, "search_articles 需要非空字符串参数 keyword")
        limit = arguments.get("limit", 5)
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise JsonRpcError(-32602, "limit 必须是正整数")
        return handler(keyword, limit)
    if name == "get_article":
        article_id = arguments.get("article_id")
        if not isinstance(article_id, str) or not article_id:
            raise JsonRpcError(-32602, "get_article 需要非空字符串参数 article_id")
        return handler(article_id)
    return handler()


def handle_request(message: dict):
    """路由 JSON-RPC 方法，返回 result 值；notification 与错误由调用方处理。"""
    method = message.get("method")
    if not isinstance(method, str):
        raise JsonRpcError(-32600, "Invalid Request: 缺少 method")

    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": SERVER_INFO,
            "capabilities": {"tools": {}},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        params = message.get("params") or {}
        if not isinstance(params, dict):
            raise JsonRpcError(-32602, "tools/call 的 params 必须是 object")
        name = params.get("name")
        if not isinstance(name, str):
            raise JsonRpcError(-32602, "tools/call 缺少工具名 name")
        payload = _call_tool(name, params.get("arguments"))
        return {
            "content": [
                {"type": "text", "text": json.dumps(payload, ensure_ascii=False)}
            ]
        }
    if method.startswith("notifications/"):
        return None  # 通知语义，无 id 时不响应；带 id 时按空 result 处理
    raise JsonRpcError(-32601, "Method not found")


def _send(message: dict) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    reload_articles()
    log.info("MCP knowledge server 已启动，等待 stdin 请求…")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _send({"jsonrpc": "2.0", "id": None,
                   "error": {"code": -32700, "message": "Parse error"}})
            continue
        if not isinstance(message, dict):
            _send({"jsonrpc": "2.0", "id": None,
                   "error": {"code": -32600, "message": "Invalid Request"}})
            continue

        msg_id = message.get("id")
        is_notification = "id" not in message
        try:
            result = handle_request(message)
        except JsonRpcError as exc:
            if is_notification:
                log.warning("notification 出错（不响应）: %s", exc.message)
                continue
            _send({"jsonrpc": "2.0", "id": msg_id,
                   "error": {"code": exc.code, "message": exc.message}})
            continue
        except Exception as exc:  # noqa: BLE001 - 兜底内部错误
            log.exception("内部错误")
            if is_notification:
                continue
            _send({"jsonrpc": "2.0", "id": msg_id,
                   "error": {"code": -32603, "message": f"Internal error: {exc}"}})
            continue

        if is_notification:
            continue  # notification 不响应
        _send({"jsonrpc": "2.0", "id": msg_id, "result": result})


if __name__ == "__main__":
    main()

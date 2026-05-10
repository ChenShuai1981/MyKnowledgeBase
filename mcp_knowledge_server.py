#!/usr/bin/env python3
"""MCP Server for searching a local knowledge base (JSON articles).

Protocol: JSON-RPC 2.0 over stdio — no third-party dependencies.

Usage:
    python mcp_knowledge_server.py
    # or register in Claude Code / OpenCode MCP config:
    # {"mcpServers": {"knowledge": {"command": "python3", "args": ["mcp_knowledge_server.py"]}}}
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# ---- constants ------------------------------------------------------------

ARTICLES_DIR = Path(os.getenv("KNOWLEDGE_ARTICLES_DIR", "knowledge/articles"))
PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "knowledge-base-server"
SERVER_VERSION = "0.1.0"

# ---- article cache --------------------------------------------------------


def _load_articles() -> list[dict[str, Any]]:
    """Load all JSON articles from the articles directory into memory."""
    articles: list[dict[str, Any]] = []
    if not ARTICLES_DIR.is_dir():
        _log(f"WARN: articles directory not found: {ARTICLES_DIR}")
        return articles

    for fpath in sorted(ARTICLES_DIR.glob("*.json")):
        try:
            article = json.loads(fpath.read_text(encoding="utf-8"))
            if isinstance(article, dict):
                articles.append(article)
        except (json.JSONDecodeError, OSError) as exc:
            _log(f"WARN: skipping {fpath.name}: {exc}")

    _log(f"Loaded {len(articles)} articles from {ARTICLES_DIR}")
    return articles


_articles_cache: list[dict[str, Any]] = []


def _refresh_cache() -> None:
    """Reload the article cache from disk."""
    global _articles_cache
    _articles_cache = _load_articles()


# ---- stdio helpers --------------------------------------------------------


def _log(msg: str) -> None:
    """Write a log message to stderr (avoids polluting stdout JSON-RPC)."""
    print(msg, file=sys.stderr, flush=True)


def _send(data: dict[str, Any]) -> None:
    """Send a JSON-RPC response/message to stdout."""
    line = json.dumps(data, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _read_message() -> dict[str, Any] | None:
    """Read one JSON-RPC message from stdin.  Returns None on EOF / empty."""
    line = sys.stdin.readline()
    if not line:
        return None
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError as exc:
        _log(f"ERROR: invalid JSON on stdin: {exc}")
        return None


# ---- JSON-RPC helpers -----------------------------------------------------


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 error response."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _rpc_result(request_id: Any, result: Any) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 success response."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


# ---- MCP handlers ---------------------------------------------------------


def _handle_initialize(msg_id: Any, _params: dict[str, Any]) -> dict[str, Any]:
    """Handle the MCP initialize request."""
    _refresh_cache()
    return _rpc_result(msg_id, {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
        },
    })


def _handle_tools_list(msg_id: Any, _params: dict[str, Any]) -> dict[str, Any]:
    """Return the list of available tools."""
    tools = [
        {
            "name": "search_articles",
            "description": "按关键词搜索知识库文章标题和摘要，返回匹配的文章列表",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词，支持中文和英文",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量上限（默认 5）",
                        "default": 5,
                    },
                },
                "required": ["keyword"],
            },
        },
        {
            "name": "get_article",
            "description": "按文章 ID 获取文章完整内容",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "article_id": {
                        "type": "string",
                        "description": "文章 ID，例如 github-20260326-001",
                    },
                },
                "required": ["article_id"],
            },
        },
        {
            "name": "knowledge_stats",
            "description": "返回知识库统计信息（文章总数、来源分布、热门标签 Top10）",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
    ]
    return _rpc_result(msg_id, {"tools": tools})


def _handle_tools_call(msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a tools/call request to the correct handler."""
    tool_name = params.get("name", "")
    arguments = params.get("arguments", {})

    if tool_name == "search_articles":
        return _tool_search_articles(msg_id, arguments)
    elif tool_name == "get_article":
        return _tool_get_article(msg_id, arguments)
    elif tool_name == "knowledge_stats":
        return _tool_knowledge_stats(msg_id, arguments)
    else:
        return _rpc_error(msg_id, -32601, f"Unknown tool: {tool_name}")


# ---- tool implementations -------------------------------------------------


def _tool_search_articles(msg_id: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Search articles by keyword in title and summary."""
    keyword = args.get("keyword", "").strip().lower()
    limit = max(1, min(50, int(args.get("limit", 5))))

    if not keyword:
        return _rpc_error(msg_id, -32602, 'Missing required parameter: "keyword"')

    results: list[dict[str, Any]] = []
    for article in _articles_cache:
        title = (article.get("title") or "").lower()
        summary = (article.get("summary") or "").lower()
        tags_str = " ".join(article.get("tags") or []).lower()

        if keyword in title or keyword in summary or keyword in tags_str:
            results.append({
                "id": article.get("id", ""),
                "title": article.get("title", ""),
                "source": article.get("source", ""),
                "score": article.get("score", 0),
                "tags": article.get("tags", []),
                "summary": (article.get("summary") or "")[:300],
                "source_url": article.get("source_url", ""),
            })

    # Sort: higher score first (better match), then alphabetically
    results.sort(key=lambda r: (-r.get("score", 0), r.get("title", "")))

    shown = results[:limit]
    text = _format_search_results(keyword, shown, len(results))
    return _rpc_result(msg_id, {"content": [{"type": "text", "text": text}]})


def _format_search_results(keyword: str, items: list[dict[str, Any]], total: int) -> str:
    """Format search results as readable Markdown."""
    if not items:
        return f"未找到与「{keyword}」相关的文章。"

    lines = [f"## 搜索「{keyword}」({len(items)}/{total} 条结果)\n"]
    for i, item in enumerate(items, 1):
        lines.append(f"### {i}. {item['title']}")
        lines.append(f"- **ID**: `{item['id']}`")
        lines.append(f"- **来源**: {item['source']}  |  **评分**: {item['score']}/10")
        lines.append(f"- **标签**: {', '.join(item['tags'])}")
        lines.append(f"- **链接**: {item['source_url']}")
        lines.append(f"- **摘要**: {item['summary']}")
        lines.append("")
    return "\n".join(lines)


def _tool_get_article(msg_id: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Get full article content by ID."""
    article_id = (args.get("article_id") or "").strip()

    if not article_id:
        return _rpc_error(msg_id, -32602, 'Missing required parameter: "article_id"')

    for article in _articles_cache:
        if article.get("id") == article_id:
            text = _format_article_detail(article)
            return _rpc_result(msg_id, {"content": [{"type": "text", "text": text}]})

    return _rpc_result(msg_id, {
        "content": [{"type": "text", "text": f"未找到 ID 为 `{article_id}` 的文章。"}],
    })


def _format_article_detail(article: dict[str, Any]) -> str:
    """Format a single article as detailed Markdown."""
    lines = [
        f"# {article.get('title', 'Untitled')}",
        "",
        f"- **ID**: `{article.get('id', '')}`",
        f"- **来源**: {article.get('source', '')}",
        f"- **评分**: {article.get('score', 0)}/10",
        f"- **状态**: {article.get('status', '')}",
        f"- **标签**: {', '.join(article.get('tags', []))}",
        f"- **链接**: {article.get('source_url', '')}",
        f"- **创建时间**: {article.get('created_at', '')}",
        "",
        "## 摘要",
        "",
        article.get("summary", "(无摘要)"),
    ]
    return "\n".join(lines)


def _tool_knowledge_stats(msg_id: Any, _args: dict[str, Any]) -> dict[str, Any]:
    """Return knowledge base statistics."""
    total = len(_articles_cache)
    sources = Counter(a.get("source", "unknown") for a in _articles_cache)
    statuses = Counter(a.get("status", "unknown") for a in _articles_cache)
    all_tags: Counter[str] = Counter()
    total_score = 0
    scored = 0

    for article in _articles_cache:
        for tag in article.get("tags", []):
            all_tags[tag.lower()] += 1
        score = article.get("score")
        if isinstance(score, (int, float)) and score > 0:
            total_score += score
            scored += 1

    lines = [
        "# 知识库统计",
        "",
        f"## 总览",
        f"- **文章总数**: {total}",
        f"- **平均评分**: {round(total_score / scored, 1) if scored else 'N/A'}",
        "",
        "## 来源分布",
    ]
    for src, count in sources.most_common():
        lines.append(f"- **{src}**: {count} 篇")

    lines.extend(["", "## 状态分布", ""])
    for st, count in statuses.most_common():
        lines.append(f"- **{st}**: {count} 篇")

    lines.extend(["", "## 热门标签 Top 10", ""])
    for tag, count in all_tags.most_common(10):
        lines.append(f"- **{tag}**: {count} 次")

    text = "\n".join(lines)
    return _rpc_result(msg_id, {"content": [{"type": "text", "text": text}]})


# ---- notifications --------------------------------------------------------


def _send_initialized() -> None:
    """Send the initialized notification (required by MCP spec)."""
    _send({"jsonrpc": "2.0", "method": "notifications/initialized"})


# ---- main loop ------------------------------------------------------------


def _dispatch(msg: dict[str, Any]) -> dict[str, Any] | None:
    """Route an incoming JSON-RPC message to the appropriate handler.

    Returns a response dict, or None for notifications.
    """
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params", {})

    if method == "initialize":
        return _handle_initialize(msg_id, params)
    elif method == "tools/list":
        return _handle_tools_list(msg_id, params)
    elif method == "tools/call":
        return _handle_tools_call(msg_id, params)
    elif method == "notifications/initialized":
        _log("Client initialized.")
        return None
    else:
        _log(f"WARN: unknown method: {method}")
        return _rpc_error(msg_id, -32601, f"Method not found: {method}")


def main() -> None:
    """Run the MCP server main loop on stdio."""
    _log(f"Starting {SERVER_NAME} v{SERVER_VERSION}")
    _log(f"Articles dir: {ARTICLES_DIR.resolve()}")
    _refresh_cache()

    try:
        while True:
            msg = _read_message()
            if msg is None:
                break

            response = _dispatch(msg)
            if response is not None:
                _send(response)
    except KeyboardInterrupt:
        _log("Server shutting down.")
    except BrokenPipeError:
        _log("Client disconnected.")
    except Exception:
        _log(f"FATAL: unhandled exception")
        import traceback
        traceback.print_exc(file=sys.stderr)


if __name__ == "__main__":
    main()

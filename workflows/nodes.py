"""LangGraph 工作流的 5 个节点函数。

每个节点是纯函数：接收 KBState，返回部分状态更新的 dict。
"""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from workflows.model_client import accumulate_usage, chat, chat_json
from workflows.state import KBState

logger = logging.getLogger(__name__)

ARTICLES_DIR = Path(_project_root) / "knowledge" / "articles"


# ═══════════════════════════════════════════════════════════════════════════
# 节点 1: 采集
# ═══════════════════════════════════════════════════════════════════════════


def collect_node(state: KBState) -> dict[str, Any]:
    """调用 GitHub Search API 采集 AI 相关仓库，返回 sources 列表。"""
    print("[CollectNode] 开始采集 GitHub 仓库...")

    query = "ai+agent+llm+stars:>100"
    url = (
        "https://api.github.com/search/repositories"
        f"?q={query}&sort=stars&order=desc&per_page=20"
    )

    token = os.getenv("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "KnowledgeBase-Collector/1.0",
    }
    if token:
        headers["Authorization"] = f"token {token}"

    req = urllib.request.Request(url, headers=headers)
    ctx = ssl.create_default_context()

    try:
        with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        logger.error("GitHub API 请求失败: %s", e)
        return {"sources": [], "cost_tracker": state.get("cost_tracker", {})}

    now = datetime.now(timezone.utc).isoformat()
    date_str = datetime.now().strftime("%Y%m%d")
    sources: list[dict[str, Any]] = []
    for i, repo in enumerate(data.get("items", [])[:20]):
        sources.append({
            "id": f"github-{date_str}-{i + 1:03d}",
            "title": repo["full_name"],
            "source": "github",
            "source_url": repo["html_url"],
            "author": repo["owner"]["login"],
            "published_at": repo.get("pushed_at", ""),
            "raw_description": repo.get("description", "") or "",
            "stars": repo.get("stargazers_count", 0),
            "language": repo.get("language", ""),
            "topics": repo.get("topics", []),
            "collected_at": now,
        })

    print(f"[CollectNode] 采集到 {len(sources)} 条仓库")
    return {"sources": sources, "cost_tracker": state.get("cost_tracker", {})}


# ═══════════════════════════════════════════════════════════════════════════
# 节点 2: 分析
# ═══════════════════════════════════════════════════════════════════════════

ANALYZE_PROMPT = """分析以下 GitHub 仓库，返回 JSON：
{{
  "summary": "2-3 句中文技术摘要，说明核心功能和价值",
  "tags": ["标签1", "标签2"],
  "score": 0.85
}}

仓库名称: {title}
描述: {description}
Topics: {topics}

评分标准 (0-1):
- 0.9-1.0: 突破性创新，高价值
- 0.7-0.9: 优秀项目
- 0.5-0.7: 普通有用
- <0.5: 低质量

可用标签: agent, rag, mcp, llm, fine-tuning, prompt-engineering, multi-agent, tool-use, evaluation, deployment, security, reasoning, code-generation, vision, audio, data-engineering"""

ANALYZE_SYSTEM = "你是一个 AI 技术分析师。严格按 JSON 格式输出，不包含多余内容。"


def analyze_node(state: KBState) -> dict[str, Any]:
    """对每条数据用 LLM 生成中文摘要、标签、评分。"""
    sources = state.get("sources", [])
    print(f"[AnalyzeNode] 分析 {len(sources)} 条数据...")

    tracker = dict(state.get("cost_tracker", {}))
    analyses: list[dict[str, Any]] = []

    for item in sources:
        prompt = ANALYZE_PROMPT.format(
            title=item["title"],
            description=item.get("raw_description", ""),
            topics=", ".join(item.get("topics", [])),
        )
        result, usage = chat_json(prompt, system=ANALYZE_SYSTEM)
        tracker = accumulate_usage(tracker, usage)

        score = result.get("score", 0.5)
        if not isinstance(score, (int, float)):
            score = 0.5
        score = max(0.0, min(1.0, float(score)))

        analyses.append({
            **item,
            "summary": result.get("summary") or item.get("raw_description", ""),
            "tags": result.get("tags") or ["llm"],
            "score": score,
            "status": "analyzed",
        })

    print(f"[AnalyzeNode] 分析完成: {len(analyses)} 条")
    return {"analyses": analyses, "cost_tracker": tracker}


# ═══════════════════════════════════════════════════════════════════════════
# 节点 3: 整理
# ═══════════════════════════════════════════════════════════════════════════

ORGANIZE_FIX_PROMPT = """请根据审核反馈修正以下知识条目。

当前条目:
标题: {title}
摘要: {summary}
标签: {tags}
评分: {score}

审核反馈: {feedback}

请根据反馈定向优化。返回 JSON：
{{
  "summary": "修正后的中文摘要",
  "tags": ["标签1", "标签2"],
  "score": 0.85
}}
只返回 JSON。"""

ORGANIZE_SYSTEM = "你是一个 AI 编辑。根据反馈修正内容，返回 JSON。"


def organize_node(state: KBState) -> dict[str, Any]:
    """过滤低分条目、按 URL 去重、如有审核反馈则用 LLM 修正。"""
    analyses = state.get("analyses", [])
    iteration = state.get("iteration", 0)
    feedback = state.get("review_feedback", "")
    print(f"[OrganizeNode] 整理 {len(analyses)} 条 (iteration={iteration})...")

    tracker = dict(state.get("cost_tracker", {}))
    threshold = 0.6

    # Step 1: 过滤低分
    filtered = [a for a in analyses if a.get("score", 0) >= threshold]

    # Step 2: 按 source_url 去重
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in filtered:
        url = item.get("source_url", "")
        if url in seen:
            continue
        seen.add(url)
        deduped.append(item)

    # Step 3: 有反馈时用 LLM 修正
    if iteration > 0 and feedback.strip():
        fixed: list[dict[str, Any]] = []
        for item in deduped:
            prompt = ORGANIZE_FIX_PROMPT.format(
                title=item["title"],
                summary=item.get("summary", ""),
                tags=", ".join(item.get("tags", [])),
                score=item.get("score", 0.5),
                feedback=feedback,
            )
            result, usage = chat_json(prompt, system=ORGANIZE_SYSTEM)
            tracker = accumulate_usage(tracker, usage)
            if result:
                item = {
                    **item,
                    "summary": result.get("summary", item["summary"]),
                    "tags": result.get("tags", item["tags"]),
                    "score": result.get("score", item["score"]),
                }
            fixed.append(item)
        deduped = fixed

    # 统一字段，构建 articles
    now = datetime.now(timezone.utc).isoformat()
    articles: list[dict[str, Any]] = []
    for item in deduped:
        articles.append({
            "id": item.get("id", "unknown-000"),
            "title": item.get("title", ""),
            "source": item.get("source", "github"),
            "source_url": item.get("source_url", ""),
            "author": item.get("author", ""),
            "published_at": item.get("published_at", ""),
            "collected_at": item.get("collected_at", ""),
            "summary": item.get("summary", ""),
            "score": item.get("score", 0),
            "tags": item.get("tags", []),
            "status": "organized",
            "updated_at": now,
        })

    print(f"[OrganizeNode] 过滤后: {len(articles)} 条")
    return {"articles": articles, "cost_tracker": tracker}


# ═══════════════════════════════════════════════════════════════════════════
# 节点 4: 审核
# ═══════════════════════════════════════════════════════════════════════════

REVIEW_PROMPT = """请从以下四个维度审核这条知识条目，返回 JSON。

条目内容:
标题: {title}
摘要: {summary}
标签: {tags}
评分: {score}

维度（每项 0-1）:
- summary_quality: 摘要是否准确、完整、流畅
- tag_accuracy: 标签是否准确匹配内容
- classification: 分类是否合理
- consistency: 内容是否一致、无矛盾

返回格式:
{{
  "scores": {{
    "summary_quality": 0.0,
    "tag_accuracy": 0.0,
    "classification": 0.0,
    "consistency": 0.0
  }},
  "overall_score": 0.0,
  "passed": false,
  "feedback": ""
}}

overall_score = 四维平均分，passed = overall_score >= 0.7
反馈指出具体改进方向。只返回 JSON。"""

REVIEW_SYSTEM = "你是一个严格的质量审核员。按 JSON 格式输出评分。"


def review_node(state: KBState) -> dict[str, Any]:
    """LLM 四维度评分审核。iteration >= 2 时强制通过。"""
    articles = state.get("articles", [])
    iteration = state.get("iteration", 0)
    print(f"[ReviewNode] 审核 {len(articles)} 条 (iteration={iteration})...")

    tracker = dict(state.get("cost_tracker", {}))

    # iteration >= 2 强制通过（最多 3 轮）
    if iteration >= 2:
        print("[ReviewNode] iteration >= 2，强制通过")
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
            "cost_tracker": tracker,
        }

    if not articles:
        return {
            "review_passed": True,
            "review_feedback": "无内容，自动通过",
            "iteration": iteration + 1,
            "cost_tracker": tracker,
        }

    total_score = 0.0
    all_feedback: list[str] = []

    for article in articles:
        prompt = REVIEW_PROMPT.format(
            title=article.get("title", ""),
            summary=article.get("summary", ""),
            tags=", ".join(article.get("tags", [])),
            score=article.get("score", 0),
        )
        result, usage = chat_json(prompt, system=REVIEW_SYSTEM)
        tracker = accumulate_usage(tracker, usage)

        overall = result.get("overall_score", 0) or 0
        fb = result.get("feedback", "") or ""
        total_score += overall
        if fb:
            title_short = article.get("title", "")[:30]
            all_feedback.append(f"[{title_short}...] {fb}")

    avg_score = total_score / len(articles) if articles else 0.0
    passed = avg_score >= 0.7

    print(f"[ReviewNode] 平均分: {avg_score:.3f}, 通过: {passed}")

    return {
        "review_passed": passed,
        "review_feedback": "\n".join(all_feedback) if not passed else "",
        "iteration": iteration + 1,
        "cost_tracker": tracker,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 节点 4-Test: 测试用审核（不调 LLM）
# ═══════════════════════════════════════════════════════════════════════════


def review_node_test(state: KBState) -> dict[str, Any]:
    """测试用审核节点：前 2 次强制不通过，第 3 次强制通过。"""
    articles = state.get("articles", [])
    iteration = state.get("iteration", 0)
    print(f"[ReviewNodeTest] 审核 {len(articles)} 条 (iteration={iteration})...")

    tracker = state.get("cost_tracker", {})

    if iteration >= 2:
        passed = True
        feedback = ""
        print(f"[ReviewNodeTest] iteration={iteration} >= 2 → review_passed=True（强制通过）")
    elif iteration == 1:
        passed = False
        feedback = "摘要不够精炼，标签选择有偏差，需要优化后再审。"
        print(f"[ReviewNodeTest] iteration={iteration} → review_passed=False（第 2 次模拟不通过）")
    else:
        passed = False
        feedback = "摘要内容过短，缺少核心技术亮点描述，标签分类不够准确。"
        print(f"[ReviewNodeTest] iteration={iteration} → review_passed=False（第 1 次模拟不通过）")

    return {
        "review_passed": passed,
        "review_feedback": feedback if not passed else "",
        "iteration": iteration + 1,
        "cost_tracker": tracker,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 节点 5: 保存
# ═══════════════════════════════════════════════════════════════════════════


def save_node(state: KBState) -> dict[str, Any]:
    """将 articles 写入 JSON 文件，同时更新 index.json 索引。"""
    articles = state.get("articles", [])
    print(f"[SaveNode] 保存 {len(articles)} 条到 {ARTICLES_DIR}...")

    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    saved: list[str] = []
    index: list[dict[str, Any]] = []

    for article in articles:
        article_id = article.get("id", "") or "unknown-000"
        filename = f"{article_id}.json"
        filepath = ARTICLES_DIR / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(article, f, ensure_ascii=False, indent=2)
        saved.append(filename)

        index.append({
            "id": article_id,
            "title": article.get("title", ""),
            "source_url": article.get("source_url", ""),
            "summary": (article.get("summary", "") or "")[:100],
            "tags": article.get("tags", []),
            "score": article.get("score", 0),
            "saved_at": now,
        })

    # 合并已有索引
    index_path = ARTICLES_DIR / "index.json"
    existing_index: list[dict] = []
    if index_path.exists():
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                existing_index = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    merged = existing_index + index
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"[SaveNode] 已保存 {len(saved)} 个文件，索引共 {len(merged)} 条")
    return {"cost_tracker": state.get("cost_tracker", {})}

"""审核节点：对 analyses 进行 5 维度评分，代码重算加权总分。

审核对象是 state["analyses"]（非 articles），
每次最多审核前 5 条，LLM 调用失败时自动通过不阻塞流程。
"""

from __future__ import annotations

import logging
from typing import Any

from workflows.model_client import (
    BudgetExceededError,
    accumulate_usage,
    chat_json,
)
from workflows.state import KBState

logger = logging.getLogger(__name__)

# 5 维度权重配置（总和 = 1.0）
WEIGHTS: dict[str, float] = {
    "summary_quality": 0.25,
    "technical_depth": 0.25,
    "relevance": 0.20,
    "originality": 0.15,
    "formatting": 0.15,
}

REVIEW_PROMPT = """Rate the following analysis entry on 5 dimensions (1-10 scale), return JSON.

Analysis:
Title: {title}
Summary: {summary}
Tags: {tags}
Score: {score}

Dimensions (1-10, integer):
- summary_quality: Is the summary accurate, complete, and fluent?
- technical_depth: How deep is the technical analysis?
- relevance: How relevant is this to an AI knowledge base?
- originality: How novel or original is this project?
- formatting: How well-formatted and structured is the entry?

Return format:
{{
  "scores": {{
    "summary_quality": 7,
    "technical_depth": 7,
    "relevance": 7,
    "originality": 7,
    "formatting": 7
  }},
  "feedback": "Specific suggestions for improvement (or empty string if none)"
}}
Only return valid JSON. No extra text."""

REVIEW_SYSTEM = "You are a strict quality reviewer. Rate each dimension 1-10 and return only JSON."

REVIEWER_PASS_THRESHOLD = 7.0

def review_node(state: KBState) -> dict[str, Any]:
    """审核 analyses，5 维度加权评分 >= REVIEWER_PASS_THRESHOLD 通过。

    Returns:
        {review_passed, review_feedback, iteration, cost_tracker}
    """
    analyses = state.get("analyses", [])
    iteration = state.get("iteration", 0)
    plan = state.get("plan", {}) or {}
    max_iterations = int(plan.get("max_iterations", 3))
    print(f"[ReviewNode] 审核 {len(analyses)} 条 analyses (iteration={iteration})...")

    tracker = dict(state.get("cost_tracker", {}))

    # 超过 max_iterations 则强制通过
    if iteration >= max_iterations - 1:
        print("[ReviewNode] iteration >= 2，强制通过")
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
            "cost_tracker": tracker,
        }

    if not analyses:
        return {
            "review_passed": True,
            "review_feedback": "无内容，自动通过",
            "iteration": iteration + 1,
            "cost_tracker": tracker,
        }

    # 最多审核前 5 条（控 token 消耗）
    target = analyses[:5]
    total_weighted = 0.0
    reviewed_count = 0
    all_feedback: list[str] = []

    for item in target:
        prompt = REVIEW_PROMPT.format(
            title=item.get("title", ""),
            summary=item.get("summary", ""),
            tags=", ".join(item.get("tags", [])),
            score=item.get("score", 0),
        )
        try:
            result, usage = chat_json(prompt, system=REVIEW_SYSTEM, temperature=0.1, node_name="reviewer")
        except BudgetExceededError:
            raise
        except Exception:
            logger.warning("LLM 调用异常，跳过审核: %s", item.get("id", ""))
            result, usage = {}, {}

        tracker = accumulate_usage(tracker, usage)

        # LLM 失败 / 解析失败时跳过此条（视为已通过，不参与评分）
        scores = result.get("scores", {}) if result else {}
        if not scores or not isinstance(scores, dict):
            logger.info("评分数据无效，跳过该条目: %s", item.get("id", ""))
            continue

        # 代码重算加权总分（不信任 LLM 算术）
        weighted = sum(scores.get(k, 5) * v for k, v in WEIGHTS.items())
        weighted = max(1.0, min(10.0, weighted))
        total_weighted += weighted
        reviewed_count += 1

        fb = result.get("feedback", "") or ""
        if fb:
            title_short = item.get("title", "")[:40]
            all_feedback.append(f"[{title_short}] {fb}")

    avg_weighted = total_weighted / reviewed_count if reviewed_count > 0 else 10.0
    passed = avg_weighted >= REVIEWER_PASS_THRESHOLD

    print(
        f"[ReviewNode] 实际评分 {reviewed_count} 条，"
        f"加权平均: {avg_weighted:.2f}/10, 通过: {passed}"
    )

    return {
        "review_passed": passed,
        "review_feedback": "\n".join(all_feedback) if not passed else "",
        "iteration": iteration + 1,
        "cost_tracker": tracker,
    }

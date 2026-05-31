"""修改节点：根据审核反馈修正 analyses，供下一轮审核循环。

读 state["analyses"] + state["review_feedback"]，
将 feedback 注入 prompt 调 LLM 定向修改。
temperature=0.4 允许适度创造性改写。
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

REVISE_ITEM_PROMPT = """You are an AI editor. Revise this analysis entry based on the review feedback.

REVIEW FEEDBACK:
{feedback}

ENTRY:
Title: {title}
Summary: {summary}
Tags: {tags}
Score: {score}

Instructions:
- Fix the entry according to the feedback above.
- Improve the summary to be more accurate, complete, and fluent.
- Adjust tags to better match content.
- Update the score if justified.
- Return only JSON, no extra text.

Return format:
{{
  "summary": "revised summary",
  "tags": ["tag1", "tag2"],
  "score": 0.85
}}"""

REVISE_SYSTEM = "You are an AI editor that revises analysis entries based on feedback. Return only valid JSON."


def revise_node(state: KBState) -> dict[str, Any]:
    """根据审核反馈逐条修正 analyses。

    Returns:
        analyses 或 feedback 为空时返回 {}；
        否则返回 {"analyses": improved, "cost_tracker": tracker}
    """
    analyses = state.get("analyses", [])
    feedback = state.get("review_feedback", "")
    print(
        f"[ReviseNode] 修正 {len(analyses)} 条 analyses, "
        f"feedback长度={len(feedback)}..."
    )

    if not analyses or not feedback.strip():
        print("[ReviseNode] analyses 或 feedback 为空，跳过")
        return {}

    tracker = dict(state.get("cost_tracker", {}))
    improved: list[dict[str, Any]] = []

    for item in analyses:
        prompt = REVISE_ITEM_PROMPT.format(
            feedback=feedback,
            title=item.get("title", ""),
            summary=item.get("summary", ""),
            tags=", ".join(item.get("tags", [])),
            score=item.get("score", 0.5),
        )
        try:
            result, usage = chat_json(prompt, system=REVISE_SYSTEM, temperature=0.4, node_name="reviser")
        except BudgetExceededError:
            raise
        except Exception:
            logger.warning("LLM 调用异常，保留原条目: %s", item.get("id", ""))
            result, usage = {}, {}

        tracker = accumulate_usage(tracker, usage)

        if result and isinstance(result, dict):
            summary = result.get("summary", item.get("summary", ""))
            tags = result.get("tags", item.get("tags", []))
            score = result.get("score", item.get("score", 0.5))
            if not isinstance(score, (int, float)):
                score = 0.5
            score = max(0.0, min(1.0, float(score)))
            improved.append({
                **item,
                "summary": summary,
                "tags": tags if isinstance(tags, list) else item.get("tags", []),
                "score": score,
                "status": "revised",
            })
        else:
            improved.append(item)

    modified = sum(1 for i in improved if i.get("status") == "revised")
    print(f"[ReviseNode] 修改完成: {modified} 条被修正, 共 {len(improved)} 条")

    return {"analyses": improved, "cost_tracker": tracker}

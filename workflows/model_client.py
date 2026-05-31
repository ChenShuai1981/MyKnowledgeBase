"""Workflows 专用的 LLM 客户端封装。

提供给 nodes.py 的简洁接口：
- chat(prompt, system=...) -> (text, usage)
- chat_json(prompt, system=...) -> (parsed_json, usage)
- accumulate_usage(tracker, usage) -> new_tracker
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import Any

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from pipeline.model_client import chat as _pipeline_chat

from tests.cost_guard import BudgetExceededError, CostGuard

logger = logging.getLogger(__name__)


# ── 全局 CostGuard 实例（懒加载）───────────────────────────────────────────────

_cost_guard: CostGuard | None = None


def get_cost_guard() -> CostGuard:
    """获取全局 CostGuard 实例（懒加载），首次调用时创建。"""
    global _cost_guard  # noqa: PLW0603
    if _cost_guard is None:
        budget = float(os.getenv("BUDGET_YUAN", "1.0"))
        _cost_guard = CostGuard(budget_yuan=budget)
    return _cost_guard


# ── LLM 调用 ──────────────────────────────────────────────────────────────────


def chat(
    prompt: str,
    system: str = "你是一个 AI 技术分析助手。",
    temperature: float = 0.7,
    node_name: str = "unknown",
) -> tuple[str, dict[str, Any]]:
    """调用 LLM，返回 (文本内容, token 用量)。

    自动通过全局 CostGuard 记录 token 用量并检查预算。
    超预算时抛出 BudgetExceededError。
    """
    result = _pipeline_chat(prompt, system=system, temperature=temperature)
    usage = result["usage"]

    # 记录 + 预算检查
    guard = get_cost_guard()
    guard.record(node_name, usage, model="")
    guard.check()

    return result["content"], usage


def chat_json(
    prompt: str,
    system: str = "你是一个 AI 技术分析助手。",
    temperature: float = 0.7,
    node_name: str = "unknown",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """调用 LLM 并解析 JSON，返回 (解析结果, token 用量)。

    解析失败时返回空 dict，不抛出异常。
    自动清除 markdown 代码块标记。
    """
    content, usage = chat(prompt, system=system, temperature=temperature, node_name=node_name)
    cleaned = re.sub(r"^```(?:json)?\s*", "", content.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned), usage
    except json.JSONDecodeError:
        logger.warning("chat_json 解析失败: %s", content[:100])
        return {}, usage


def accumulate_usage(
    tracker: dict[str, Any],
    usage: dict[str, Any],
) -> dict[str, Any]:
    """累加 token 用量到追踪器，返回新字典（纯函数）。"""
    return {
        "total_input_tokens": tracker.get("total_input_tokens", 0)
        + usage.get("prompt_tokens", 0),
        "total_output_tokens": tracker.get("total_output_tokens", 0)
        + usage.get("completion_tokens", 0),
        "estimated_cost_usd": round(
            tracker.get("estimated_cost_usd", 0.0) + _estimate_cost(usage), 8
        ),
        "llm_calls": tracker.get("llm_calls", 0) + 1,
        "model": tracker.get("model", ""),
        "currency": "USD",
    }


def _estimate_cost(usage: dict[str, Any]) -> float:
    """粗略估算单次调用成本（USD），使用默认价格。"""
    prompt_cost = usage.get("prompt_tokens", 0) / 1000 * 0.002
    completion_cost = usage.get("completion_tokens", 0) / 1000 * 0.006
    return prompt_cost + completion_cost

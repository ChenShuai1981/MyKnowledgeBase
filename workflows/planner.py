"""Planner Agent — 根据目标产量选择执行策略。

只规划不执行（Plan, don't execute），
输出 plan dict 写入 state，下游节点读取它调整行为。
"""

from __future__ import annotations

import os
from typing import Any

from workflows.state import KBState


def plan_strategy(target_count: int | None = None) -> dict[str, Any]:
    """根据目标采集量返回执行策略。

    Args:
        target_count: 目标采集条目数，默认从环境变量 PLANNER_TARGET_COUNT 读取（默认 10）

    Returns:
        {
            "strategy": "lite" | "standard" | "full",
            "per_source_limit": int,       # 每个来源最多采集数
            "relevance_threshold": float,  # 相关性过滤阈值
            "max_iterations": int,         # 最大审核迭代次数
            "rationale": str,              # 为什么这么选
        }
    """
    if target_count is None:
        raw = os.getenv("PLANNER_TARGET_COUNT", "10")
        try:
            target_count = int(raw)
        except (ValueError, TypeError):
            target_count = 10

    if target_count < 10:
        return {
            "strategy": "lite",
            "per_source_limit": 5,
            "relevance_threshold": 0.7,
            "max_iterations": 1,
            "rationale": (
                f"目标 {target_count} 条（<10），轻量模式："
                "低采集量、高相关性阈值、最少迭代，快速产出"
            ),
        }

    if target_count < 20:
        return {
            "strategy": "standard",
            "per_source_limit": 10,
            "relevance_threshold": 0.5,
            "max_iterations": 2,
            "rationale": (
                f"目标 {target_count} 条（10≤n<20），标准模式："
                "中等采集量、中等阈值，允许一次重审迭代"
            ),
        }

    return {
        "strategy": "full",
        "per_source_limit": 20,
        "relevance_threshold": 0.4,
        "max_iterations": 3,
        "rationale": (
            f"目标 {target_count} 条（≥20），全面模式："
            "高采集量、低相关性阈值、最多三次迭代，覆盖更广"
        ),
    }


def planner_node(state: KBState) -> dict[str, Any]:
    """LangGraph 节点包装：调用 plan_strategy，输出 plan 到 state。"""
    plan = plan_strategy()
    print(f"[PlannerNode] 策略: {plan['strategy']}, "
          f"per_source_limit={plan['per_source_limit']}, "
          f"relevance_threshold={plan['relevance_threshold']}, "
          f"max_iterations={plan['max_iterations']}")
    return {"plan": plan}

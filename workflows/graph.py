"""LangGraph 工作流组装。

线性边: collect → analyze → organize → review
条件边:
  - review → organize（通过，重新整理）| revise（修改）| human_flag（兜底）
  - organize → save（通过）| review（继续审核）
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from langgraph.graph import END, StateGraph

from workflows.human_flag import human_flag_node
from workflows.nodes import (
    analyze_node,
    collect_node,
    organize_node,
    save_node,
)
from workflows.reviser import revise_node
from workflows.reviewer import review_node
from workflows.state import KBState

logger = logging.getLogger(__name__)


def route_after_review(state: KBState) -> str:
    """三路条件路由器。"""
    if state.get("review_passed"):
        return "organize"
    if state.get("iteration", 0) >= 3:
        return "human_flag"
    return "revise"


def route_after_organize(state: KBState) -> str:
    """organize 后条件路由：审核已通过 → save，否则 → review。"""
    if state.get("review_passed"):
        return "save"
    return "review"


def build_graph() -> StateGraph:
    """构建并编译 LangGraph 工作流，返回可调用的 app。"""
    graph = StateGraph(KBState)

    # ── 注册节点 ──
    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("organize", organize_node)
    graph.add_node("review", review_node)
    graph.add_node("revise", revise_node)
    graph.add_node("human_flag", human_flag_node)
    graph.add_node("save", save_node)

    # ── 线性边 ──
    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "organize")
    graph.add_edge("revise", "review")
    graph.add_edge("human_flag", END)

    # ── 条件边 ──
    graph.add_conditional_edges(
        "review",
        route_after_review,
        {
            "organize": "organize",
            "revise": "revise",
            "human_flag": "human_flag",
        },
    )
    graph.add_conditional_edges(
        "organize",
        route_after_organize,
        {
            "save": "save",
            "review": "review",
        },
    )

    graph.add_edge("save", END)

    # ── 入口 ──
    graph.set_entry_point("collect")

    return graph.compile()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    initial_state: KBState = {
        "sources": [],
        "analyses": [],
        "articles": [],
        "review_feedback": "",
        "review_passed": False,
        "iteration": 0,
        "cost_tracker": {},
    }

    app = build_graph()

    print("\n====== LangGraph 工作流执行 ======\n")

    for step, output in enumerate(app.stream(initial_state)):
        for node_name, result in output.items():
            if result is None:
                continue
            cost = result.get("cost_tracker", {})
            tokens = cost.get("total_input_tokens", 0) + cost.get(
                "total_output_tokens", 0
            )
            calls = cost.get("llm_calls", 0)

            if node_name == "collect":
                count = len(result.get("sources", []))
                print(f"[Step {step}] CollectNode — 采集 {count} 条仓库")

            elif node_name == "analyze":
                count = len(result.get("analyses", []))
                print(f"[Step {step}] AnalyzeNode — 分析 {count} 条，Token: {tokens}")

            elif node_name == "organize":
                count = len(result.get("articles", []))
                fb = result.get("review_feedback", "")
                tag = " (带反馈修正)" if fb else ""
                print(
                    f"[Step {step}] OrganizeNode — 整理 {count} 条{tag}"
                )

            elif node_name == "review":
                passed = result.get("review_passed", False)
                iteration = result.get("iteration", 0)
                status = "✅ 通过" if passed else "❌ 不通过"
                print(
                    f"[Step {step}] ReviewNode — 审核: {status}, "
                    f"iteration={iteration}, Token: {tokens}, "
                    f"LLM调用: {calls}"
                )

            elif node_name == "revise":
                count = len(result.get("analyses", []))
                print(f"[Step {step}] ReviseNode — 修正 {count} 条，Token: {tokens}")

            elif node_name == "human_flag":
                print(f"[Step {step}] HumanFlagNode — ⚠️ 需人工介入")

            elif node_name == "save":
                print(f"[Step {step}] SaveNode — 已保存，总Token: {tokens}")

    print("\n====== 工作流执行完毕 ======\n")

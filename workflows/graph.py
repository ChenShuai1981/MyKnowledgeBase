"""LangGraph 工作流组装。

线性边: collect → analyze → organize → review
条件边: review 后根据 review_passed 分支到 save(通过) 或 organize(回修)
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

from workflows.nodes import (
    analyze_node,
    collect_node,
    organize_node,
    review_node,
    # review_node_test,
    save_node,
)
from workflows.state import KBState

logger = logging.getLogger(__name__)


def _review_router(state: KBState) -> str:
    """条件边路由器：审核通过 → save，否则回 organize 修正。"""
    if state.get("review_passed"):
        return "save"
    return "organize"


def build_graph() -> StateGraph:
    """构建并编译 LangGraph 工作流，返回可调用的 app。"""
    graph = StateGraph(KBState)

    # ── 注册节点 ──
    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("organize", organize_node)
    graph.add_node("review", review_node)
    graph.add_node("save", save_node)

    # ── 线性边 ──
    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "organize")
    graph.add_edge("organize", "review")

    # ── 条件边 ──
    graph.add_conditional_edges(
        "review",
        _review_router,
        {
            "save": "save",
            "organize": "organize",
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

            elif node_name == "save":
                print(f"[Step {step}] SaveNode — 已保存，总Token: {tokens}")

    print("\n====== 工作流执行完毕 ======\n")

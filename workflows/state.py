"""LangGraph 工作流共享状态定义

遵循"报告式通信"原则：每个字段承载的是已聚合的结构化摘要，
而非原始中间数据，确保节点间传递的是信息密度最高的产物。
"""

from __future__ import annotations

from typing import TypedDict


class KBState(TypedDict):
    """LangGraph 审核循环的共享状态。

    各字段按流水线阶段组织，从采集 → 分析 → 整理 → 审核，
    后置字段依赖前置字段的产出。
    """

    # ── 采集阶段 ────────────────────────────────────────────────────────────

    sources: list[dict]
    """采集到的原始数据摘要列表。

    每条记录包含标准化后的元信息（id, title, source, source_url,
    author, published_at, stars 等），
    而非完整的 HTTP 响应体。
    """

    # ── 分析阶段 ────────────────────────────────────────────────────────────

    analyses: list[dict]
    """LLM 分析后的结构化结果列表。

    每条记录在 sources 基础上追加了 LLM 产出的语义字段
    （summary, score, tags, audience, status），
    是原始数据经过 Agent 提炼后的信息浓缩产物。
    """

    # ── 整理阶段 ────────────────────────────────────────────────────────────

    articles: list[dict]
    """格式化、去重后的最终知识条目列表。

    已过滤重复项，字段标准化（id, title, summary, tags, score,
    audience, source_url 等），可直接写入存储层。
    """

    # ── 审核阶段 ────────────────────────────────────────────────────────────

    review_feedback: str
    """Supervisor 审核反馈意见。

    描述当前 articles 存在的问题及改进方向，
    为空字符串表示尚未审核或无反馈。
    """

    review_passed: bool
    """审核是否通过。

    True 表示质量达标，可退出审核循环进入持久化；
    False 表示需根据 feedback 重做分析。
    """

    iteration: int
    """当前审核循环次数（从 0 开始计数）。

    每次审核不通过后递增，iteration >= 3 时强制结束循环，
    无论 review_passed 是否为 True。
    """

    needs_human_review: bool
    """
    新增：HumanFlag 节点设为 True
    循环必须有出口。超过 max_iterations 还没通过，说明问题不在“质量”而在“数据”，需要人工判断。
    HumanFlag 节点把问题条目写到独立目录，不污染主知识库。
    """
    # ── 成本追踪 ────────────────────────────────────────────────────────────

    cost_tracker: dict
    """Token 用量追踪。

    结构示例：
    {
        "total_input_tokens": int,
        "total_output_tokens": int,
        "estimated_cost_usd": float,
        "llm_calls": int,
        "model": str,           // 使用的模型名称
        "currency": "USD",
    }
    """

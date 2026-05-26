"""Supervisor 模式 — Worker 产出 + Supervisor 质量审核循环

流程:
  1. Worker Agent 生成分析报告 (JSON)
  2. Supervisor Agent 评分 (准确性/深度/格式)
  3. score >= 7 → 通过；否则带反馈重做，最多 3 轮
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from pipeline.model_client import chat

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
PASS_THRESHOLD = 7


def _worker(task: str, feedback: str | None = None) -> str:
    """Worker Agent：根据任务（及可选反馈）生成 JSON 分析报告。"""
    system = "你是一个 AI 技术分析师。请以 JSON 格式输出分析报告。"
    prompt = f"请分析以下技术主题，输出 JSON（包含 title, summary, key_points, conclusion 四个字段）。\n\n任务: {task}"
    if feedback:
        prompt += f"\n\n上次反馈: {feedback}\n请根据反馈优化分析报告。"
    prompt += "\n\n只输出 JSON，不要多余内容。"
    result = chat(prompt, system=system)
    return result["content"]


def _supervisor(report: str, task: str) -> dict[str, Any]:
    """Supervisor Agent：审核 Worker 报告，返回评分与反馈。"""
    system = "你是一个严格的质量审核员。请从三个维度评分并输出 JSON。"
    prompt = f"""审核以下分析报告，从三个维度评分（1-10）：

原始任务: {task}

报告内容:
{report}

返回 JSON，格式:
{{"accuracy": int, "depth": int, "format": int, "passed": bool, "score": int, "feedback": str}}

要求:
- score = (accuracy + depth + format) / 3
- passed = score >= 7
- feedback 指出具体改进方向

只输出 JSON。"""
    result = chat(prompt, system=system)
    try:
        data = json.loads(result["content"])
        data["score"] = data.get("score", 0)
        data["passed"] = data.get("passed", False)
        return data
    except (json.JSONDecodeError, KeyError):
        return {"accuracy": 0, "depth": 0, "format": 0, "passed": False, "score": 0, "feedback": "审核解析失败，请重试。"}


def supervisor(task: str, max_retries: int = 3) -> dict[str, Any]:
    """Supervisor 监督模式主入口。

    Args:
        task: 分析任务描述。
        max_retries: 最大重试次数（默认 3）。

    Returns:
        {"output": str, "attempts": int, "final_score": int, "warning": str | None}
    """
    feedback: str | None = None
    last_output = ""
    last_score = 0

    for attempt in range(max_retries + 1):
        logger.info("Worker 第 %d 次生成...", attempt + 1)
        output = _worker(task, feedback)
        last_output = output

        logger.info("Supervisor 第 %d 次审核...", attempt + 1)
        review = _supervisor(output, task)
        last_score = review.get("score", 0)

        if review.get("passed"):
            logger.info("审核通过，score=%d", last_score)
            return {
                "output": output,
                "attempts": attempt + 1,
                "final_score": last_score,
            }

        if attempt < max_retries:
            feedback = review.get("feedback", "请提升分析质量。")
            logger.warning("审核不通过，score=%d，反馈: %s", last_score, feedback)
        else:
            logger.warning("已达最大重试次数，强制返回。")

    return {
        "output": last_output,
        "attempts": max_retries + 1,
        "final_score": last_score,
        "warning": f"审核未通过（最终 score: {last_score}），已达最大重试次数，结果可能质量不足。",
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    test_task = "请分析 LangGraph 框架的优缺点和适用场景"
    result = supervisor(test_task)

    print("\n=== Supervisor 结果 ===")
    print(f"任务: {test_task}")
    print(f"尝试次数: {result['attempts']}")
    print(f"最终评分: {result['final_score']}")
    if result.get("warning"):
        print(f"警告: {result['warning']}")
    print(f"\n输出:\n{result['output']}")

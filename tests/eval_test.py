"""AI 知识库评估测试套件

pytest 用法:
    pytest tests/eval_test.py              # 仅运行本地/非 slow 测试
    pytest tests/eval_test.py -m slow       # 仅运行 LLM 测试
    pytest tests/eval_test.py -k "judge"    # 运行 LLM-as-Judge 测试
"""

import os
import re
import sys
from typing import Any, Callable

import pytest
from dotenv import load_dotenv

load_dotenv()

from workflows.model_client import chat


# ── 评估用例集 ────────────────────────────────────────────────────────────────

EVAL_CASES: list[dict[str, Any]] = [
    {
        "name": "正面-技术文章",
        "input": (
            "LoRA: Low-Rank Adaptation of Large Language Models explains a "
            "parameter-efficient fine-tuning method that freezes pretrained model "
            "weights and injects trainable rank decomposition matrices into "
            "Transformer layers. It reduces trainable parameters by 10,000x and "
            "GPU memory by 3x while matching or exceeding fine-tuning quality."
        ),
        "expected": {
            "has_summary": lambda t: len(t) > 30,
            "tags_in_output": lambda t: "lora" in t.lower() or "low-rank" in t.lower(),
            "has_relevance_score": lambda t: bool(re.search(r"[0-9]\s*分|相关性.*[0-9]", t)),
        },
    },
    {
        "name": "负面-无关内容",
        "input": (
            "Classic chocolate chip cookies: Mix 2 cups flour, 1 cup butter, "
            "1 cup sugar, 2 eggs, 1 tsp vanilla, 2 cups chocolate chips. "
            "Bake at 350°F for 10 minutes. Perfect for dessert."
        ),
        "expected": {
            "acknowledges_irrelevant": lambda t: "无" in t
            or "不相关" in t or "低" in t
        },
    },
    {
        "name": "边界-极短输入",
        "input": "AI",
        "expected": {
            "no_crash": lambda t: isinstance(t, str) and len(t) > 0,
        },
    },
]


# ── 本地测试（不调用 LLM）────────────────────────────────────────────────────────

def test_eval_cases_structure() -> None:
    """验证 EVAL_CASES 结构完整性（不调用 LLM）"""
    assert len(EVAL_CASES) >= 3, f"需要至少 3 个用例，实际 {len(EVAL_CASES)}"

    for case in EVAL_CASES:
        assert "name" in case, "每个用例必须有 name"
        assert "input" in case, "每个用例必须有 input"
        assert "expected" in case, "每个用例必须有 expected"

        expected = case["expected"]
        assert isinstance(expected, dict), "expected 必须是 dict"

        for key, check in expected.items():
            assert callable(check), f"'{key}' 的检查器必须是可调用对象"


# ── LLM 分析测试（标记 slow）─────────────────────────────────────────────────────

ANALYZE_PROMPT = """分析以下内容，返回：
- 技术摘要（中文，50 字以内）
- 相关标签（3-5 个）
- 相关性评分（0-10）
- 一句话核心洞察

内容：
{input}"""


@pytest.mark.slow
@pytest.mark.parametrize("case", EVAL_CASES, ids=lambda c: c["name"])
def test_analyze_case(case: dict[str, Any]) -> None:
    """对每个 EVAL_CASE 调用 LLM 分析并验证"""
    text, usage = chat(
        ANALYZE_PROMPT.format(input=case["input"]),
        system="你是一个 AI 技术分析专家。返回纯文本，不要用 JSON。",
    )

    assert isinstance(text, str) and len(text) > 0, "LLM 返回空结果"
    assert usage.get("prompt_tokens", 0) > 0, "token 用量异常"

    for key, check in case["expected"].items():
        assert check(text), f"[{case['name']}] 断言 '{key}' 失败"


# ── LLM-as-Judge 测试 ──────────────────────────────────────────────────────────

JUDGE_PROMPT = """你是一个严格的评审专家。请对以下 AI 分析结果进行打分（1-10 分）。

评分标准：
- 摘要质量（是否准确、完整）
- 技术深度（是否抓住核心）
- 相关性（是否与 AI 领域相关）
- 完整性（是否包含必要信息）

分析输入：{input_text}
分析输出：{analysis_text}

只返回一个 1-10 的整数分数，不要其他文字。"""


@pytest.mark.slow
def test_llm_as_judge() -> None:
    """LLM 分析后由 LLM 评审打分，断言分数 >= 5"""
    case = EVAL_CASES[0]
    analysis, _ = chat(
        ANALYZE_PROMPT.format(input=case["input"]),
        system="你是一个 AI 技术分析专家。",
    )

    judge_text, _ = chat(
        JUDGE_PROMPT.format(input_text=case["input"][:200], analysis_text=analysis[:500]),
        system="你是一个严格的评审专家。只返回数字。",
    )

    match = re.search(r"[0-9]+", judge_text.strip())
    assert match, f"无法从评审响应中解析分数: {judge_text[:100]}"

    score = float(match.group())
    assert score >= 5, f"LLM Judge 评分 {score} < 5，分析质量不达标"
    assert score <= 10, f"LLM Judge 评分 {score} > 10，超出范围"

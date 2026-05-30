import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class CostRecord:
    """单次 LLM 调用记录"""

    node_name: str
    prompt_tokens: int
    completion_tokens: int
    cost_yuan: float
    model: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BudgetExceededError(Exception):
    """预算超限异常"""

    def __init__(self, total_cost: float, budget: float):
        self.total_cost = total_cost
        self.budget = budget
        super().__init__(
            f"预算超限！当前总成本 ¥{total_cost:.4f} > 预算 ¥{budget:.4f}"
        )


class CostGuard:
    """多 Agent 预算守卫，三重保护机制：

    - record() 记录每次 LLM 调用
    - check() 检查预算状态（ok / warning / exceeded）
    - get_report() + save_report() 生成和保存成本报告
    """

    def __init__(
        self,
        budget_yuan: float = 1.0,
        alert_threshold: float = 0.8,
        input_price_per_million: float = 1.0,
        output_price_per_million: float = 2.0,
    ):
        self.budget_yuan = budget_yuan
        self.alert_threshold = alert_threshold
        self.input_price_per_million = input_price_per_million
        self.output_price_per_million = output_price_per_million
        self.records: list[CostRecord] = []

    def _calc_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens / 1_000_000 * self.input_price_per_million
            + completion_tokens / 1_000_000 * self.output_price_per_million
        )

    def record(self, node_name: str, usage: dict, model: str = "") -> None:
        """记录一次 LLM 调用的 token 用量。

        usage 格式: {"prompt_tokens": int, "completion_tokens": int}
        """
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))

        record = CostRecord(
            node_name=node_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_yuan=self._calc_cost(prompt_tokens, completion_tokens),
            model=model,
        )
        self.records.append(record)

    @property
    def total_prompt_tokens(self) -> int:
        return sum(r.prompt_tokens for r in self.records)

    @property
    def total_completion_tokens(self) -> int:
        return sum(r.completion_tokens for r in self.records)

    @property
    def total_cost_yuan(self) -> float:
        return sum(r.cost_yuan for r in self.records)

    def check(self) -> dict:
        """检查预算状态。

        Returns:
            {"status": "ok"|"warning", "total_cost": float, "budget": float,
             "usage_ratio": float, "message": str}

        Raises:
            BudgetExceededError: 总成本超出预算
        """
        cost = self.total_cost_yuan
        ratio = cost / self.budget_yuan if self.budget_yuan > 0 else float("inf")

        if cost > self.budget_yuan:
            raise BudgetExceededError(cost, self.budget_yuan)

        if ratio >= self.alert_threshold:
            return {
                "status": "warning",
                "total_cost": round(cost, 6),
                "budget": self.budget_yuan,
                "usage_ratio": round(ratio, 4),
                "message": f"成本已达预算的 {ratio * 100:.1f}%，¥{cost:.4f} / ¥{self.budget_yuan:.4f}",
            }

        return {
            "status": "ok",
            "total_cost": round(cost, 6),
            "budget": self.budget_yuan,
            "usage_ratio": round(ratio, 4),
            "message": f"成本正常，¥{cost:.4f} / ¥{self.budget_yuan:.4f}",
        }

    def get_report(self) -> dict:
        """生成成本报告（按节点分组统计）。"""
        by_node: dict[str, dict] = {}
        for r in self.records:
            if r.node_name not in by_node:
                by_node[r.node_name] = {
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost_yuan": 0.0,
                }
            by_node[r.node_name]["calls"] += 1
            by_node[r.node_name]["prompt_tokens"] += r.prompt_tokens
            by_node[r.node_name]["completion_tokens"] += r.completion_tokens
            by_node[r.node_name]["cost_yuan"] += r.cost_yuan

        return {
            "total_cost_yuan": round(self.total_cost_yuan, 6),
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_calls": len(self.records),
            "budget_yuan": self.budget_yuan,
            "by_node": {
                node: {
                    **stats,
                    "cost_yuan": round(stats["cost_yuan"], 6),
                }
                for node, stats in by_node.items()
            },
        }

    def save_report(self, path: Optional[str] = None) -> str:
        """保存成本报告到 JSON 文件。

        Returns:
            写入的文件路径
        """
        if path is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = f"cost_report_{timestamp}.json"

        report = self.get_report()
        report["generated_at"] = datetime.now(timezone.utc).isoformat()

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        return os.path.abspath(path)


if __name__ == "__main__":
    # ── 测试 1：成本追踪正确 ──
    print("=== 测试 1：成本追踪 ===")
    guard = CostGuard(budget_yuan=1.0, alert_threshold=0.8)
    guard.record("analyzer", {"prompt_tokens": 500_000, "completion_tokens": 100_000})
    guard.record("reviewer", {"prompt_tokens": 200_000, "completion_tokens": 50_000})

    assert guard.total_prompt_tokens == 700_000, f"prompt_tokens 应为 700000，实际 {guard.total_prompt_tokens}"
    assert guard.total_completion_tokens == 150_000, f"completion_tokens 应为 150000，实际 {guard.total_completion_tokens}"

    expected_cost = (500_000 + 200_000) / 1_000_000 * 1.0 + (100_000 + 50_000) / 1_000_000 * 2.0
    assert abs(guard.total_cost_yuan - expected_cost) < 1e-9, (
        f"total_cost_yuan 应为 {expected_cost}，实际 {guard.total_cost_yuan}"
    )
    print(f"  ✅ total_prompt_tokens = {guard.total_prompt_tokens}")
    print(f"  ✅ total_cost_yuan = {guard.total_cost_yuan:.6f}\n")

    # ── 测试 2：预算超限检测 ──
    print("=== 测试 2：预算超限检测 ===")
    guard2 = CostGuard(budget_yuan=0.1, alert_threshold=0.8)
    guard2.record("analyzer", {"prompt_tokens": 500_000, "completion_tokens": 100_000})

    try:
        guard2.check()
        print("  ❌ 应该抛出 BudgetExceededError 但没有")
    except BudgetExceededError as e:
        print(f"  ✅ 正确抛出 BudgetExceededError: {e}\n")

    # ── 测试 3：预警阈值触发 ──
    print("=== 测试 3：预警阈值触发 ===")
    guard3 = CostGuard(budget_yuan=1.0, alert_threshold=0.5)
    guard3.record("organizer", {"prompt_tokens": 550_000, "completion_tokens": 0})

    try:
        result = guard3.check()
        assert result["status"] == "warning", f"状态应为 warning，实际 {result['status']}"
        assert result["usage_ratio"] >= 0.5, f"usage_ratio 应 >= 0.5，实际 {result['usage_ratio']}"
        print(f"  ✅ status = {result['status']}")
        print(f"  ✅ message = {result['message']}\n")
    except BudgetExceededError:
        print("  ❌ 不应抛出 BudgetExceededError\n")

    # ── 测试 4：状态正常 ──
    print("=== 测试 4：状态正常 ===")
    guard4 = CostGuard(budget_yuan=1.0, alert_threshold=0.8)
    guard4.record("collector", {"prompt_tokens": 100_000, "completion_tokens": 10_000})

    result = guard4.check()
    assert result["status"] == "ok", f"状态应为 ok，实际 {result['status']}"
    print(f"  ✅ status = {result['status']}\n")

    # ── 测试 5：get_report 按节点分组 ──
    print("=== 测试 5：成本报告 ===")
    report = guard.get_report()
    assert report["total_calls"] == 2
    assert "analyzer" in report["by_node"]
    assert "reviewer" in report["by_node"]
    assert report["by_node"]["analyzer"]["calls"] == 1
    assert report["by_node"]["reviewer"]["calls"] == 1
    print(f"  ✅ total_calls = {report['total_calls']}")
    print(f"  ✅ by_node keys = {list(report['by_node'].keys())}\n")

    # ── 测试 6：save_report 写盘 ──
    print("=== 测试 6：save_report ===")
    saved_path = guard.save_report("/tmp/cost_guard_test_report.json")
    assert os.path.exists(saved_path), f"文件不存在: {saved_path}"
    with open(saved_path, "r") as f:
        loaded = json.load(f)
    assert loaded["total_calls"] == 2
    os.remove(saved_path)
    print(f"  ✅ 报告已写入并删除: {saved_path}\n")

    print("=== 所有测试通过 ===")

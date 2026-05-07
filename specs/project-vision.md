# AI 知识库 · 项目愿景 v1.0

## 要做什么
- 每天定时抓取 GitHub Trending 前 20 条
- 根据 repo 的 topics 字段过滤，仅保留 AI 相关仓库（匹配关键词：ai, machine-learning, llm, deep-learning, nlp, computer-vision, generative-ai, transformer, neural-network 等）
- 用 Agent 对每个仓库进行分析，维度：技术类别、创新点、使用难度
- 输出人类可读的摘要文章，纯 Markdown 格式

## Markdown 知识条目字段
每篇包含以下固定结构：
1. **标题** — 知识条目名称
2. **仓库链接** — GitHub 仓库 URL
3. **技术类别** — 所属技术领域（如 LLM、CV、MLOps 等）
4. **创新点分析** — Agent 对技术创新的解读
5. **使用难度评级** — 入门 / 中等 / 进阶
6. **一句话摘要** — 核心要点概括
7. **日期** — 抓取日期（YYYY-MM-DD）

## 不做什么
- 不做前端展示界面（v1 仅产出 Markdown 文件）
- 不做 RSS / 邮件 / 消息推送
- 不追踪仓库后续更新（每日独立快照，不关联历史）
- 不做用户反馈、收藏、评分系统

## 边界 & 验收
- 每日最多产出 ≤20 篇 Markdown（受 topic 过滤影响，实际可能更少）
- 每篇 7 个字段完整，不出现空字段
- Agent 调用成本需设定模型选型和单日预算上限
- Markdown 文件按日期归档存储（如 `output/YYYY-MM-DD/`）

## 怎么验证
- 每天跑一次流水线，检查输出目录是否生成 N 篇 Markdown（0 < N ≤ 20）
- 随机抽查 3 篇，人工判断技术类别、创新点、使用难度评级是否合理
- 验证过滤逻辑：抽查被跳过（非 AI 相关）的仓库，确认跳过理由成立

# AI 知识库 · AGENTS.md v1.0

## 项目概述

每天自动抓取 GitHub Trending 中 AI 相关的仓库，用 Agent 分析后产出 Markdown 知识条目，归档到本地。

## 硬约束（不做什么）

- **不做前端展示界面** — v1 仅产出 Markdown 文件，不引入 Web 框架
- **不做 RSS / 邮件 / 消息推送** — 纯本地文件产出，不接任何通知渠道
- **不追踪仓库后续更新** — 每日独立快照，不做历史对比或变更追踪
- **不做用户反馈、收藏、评分系统** — 只产出，不交互

> Agent 在开发过程中若被问到以上功能，应明确拒绝或标记为 v2 计划外。

## 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 语言 | **Python 3.11+** | HTTP / API 调用、Markdown 生成、脚本编排都简洁 |
| HTTP | **httpx** (async) | GitHub API 调用，支持 async |
| LLM Agent | **OpenAI API** (GPT-4o-mini) | 性价比高，每天 20 篇分析成本可控 |
| 定时调度 | **macOS launchd** / **GitHub Actions** | 本地跑用 launchd，CI 跑用 Actions |
| 依赖管理 | **uv** 或 **pip + requirements.txt** | 轻量即可 |

> **单日成本预算上限**：$0.50。以 GPT-4o-mini 当前定价（$0.15/1M input, $0.60/1M output），20 篇分析约消耗 $0.02~$0.05/天，上限留有 10x 余量。若单次运行超限，流水线应报警并拒绝继续调用。

## 项目结构

```
.
├── specs/                  # 产品规格文档
│   └── project-vision.md
├── src/
│   ├── fetch.py            # 抓取 GitHub Trending，按 topics 过滤
│   ├── analyze.py          # 调用 Agent 分析单个仓库
│   ├── output.py           # 生成 / 写入 Markdown 文件
│   └── pipeline.py         # 串联 fetch → filter → analyze → output
├── output/
│   └── YYYY-MM-DD/         # 每日产出归档
│       ├── repo-name-1.md
│       └── ...
├── tests/
│   ├── test_fetch.py
│   ├── test_analyze.py
│   └── test_output.py
├── .env.example            # 环境变量模板
├── requirements.txt
└── AGENTS.md
```

## 数据流

```
GitHub Trending (25 repo/天)
       │
       ▼
  fetch.py: 取前 20 条
       │
       ▼
  fetch.py: topics 匹配 AI 关键词 → 过滤
       │
       ▼
  analyze.py: Agent 分析（技术类别 / 创新点 / 使用难度）
       │
       ▼
  output.py: 生成 Markdown，写入 output/YYYY-MM-DD/
```

## AI 关键词过滤规则

repo.topics 包含以下任一即视为 AI 相关：
`ai`, `machine-learning`, `llm`, `deep-learning`, `nlp`, `computer-vision`, `generative-ai`, `transformer`, `neural-network`, `ml`, `artificial-intelligence`

> 关键词放在 `src/config.py` 中维护，方便扩展。

## Markdown 输出模板

```markdown
# {标题}

- **仓库链接**: {url}
- **日期**: {YYYY-MM-DD}
- **技术类别**: {tech_category}
- **使用难度**: 入门 / 中等 / 进阶
- **一句话摘要**: {one_liner}

## 创新点分析

{innovation_analysis}
```

## Agent Prompt 约定

- 输入：仓库名称、描述、README（前 2000 字）、topics
- 输出：严格按字段输出，JSON 结构，便于 `output.py` 解析渲染
- 温度设为 0.3（分析类任务，降低发散）
- 单次调用超时 30s

## 开发约定

- **Python 代码风格**：遵循 PEP 8，使用 `ruff` 格式化 & lint
- **类型标注**：所有函数签名加 type hints
- **异常处理**：GitHub API 限流（403）要 retry + backoff；LLM 调用失败要 fallback 记录
- **日志**：使用 `logging` 模块，INFO 级别记录 pipeline 进度，ERROR 记录失败条目
- **环境变量**：`GITHUB_TOKEN`（可选，提高 API 限流）、`OPENAI_API_KEY`（必需），通过 `.env` 加载

## 编码规范

### 格式化与 lint

| 语言 | 格式化 | Lint |
|------|--------|------|
| Python | `ruff format` | `ruff check` |
| TypeScript | `prettier` | `ESLint strict` |

### 文档要求

- **Python**：所有公开函数使用 `docstring`
- **TypeScript**：所有公开函数使用 `JSDoc`

### 代码整洁

- **魔法字符串**：避免使用前缀字符串（如 `"index_xxx"`），应定义为常量
- **TODO 管理**：不允许 TODO 直接提交到 main，需转提 issue 并保留引用

### 测试要求

- 单测覆盖率 ≥ 80%（包括 glue code、异常处理分支）
- mock 代码覆盖率不计入

### CI 验证

- Jenkins 上运行 lint + 单测

## 每日运行方式

- **触发时间**：每天 0:00 自动执行
- **调度方式**：macOS launchd（本地）或 GitHub Actions scheduled workflow（CI）

```bash
# 本地运行（手动或 launchd 定时）
python -m src.pipeline

# 输出位置
ls output/$(date +%Y-%m-%d)/
```

## 验收检查清单

- [ ] `python -m src.pipeline` 一次跑通，无报错
- [ ] `output/` 当天目录下 0 < N ≤ 20 篇 Markdown
- [ ] 抽查 3 篇：7 个字段均非空，技术类别 / 难度评级合理
- [ ] 被跳过的仓库有日志说明跳过原因（非 AI 相关）

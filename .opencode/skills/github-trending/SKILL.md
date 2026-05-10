---
name: github-trending
description: 当需要采集 GitHub 热门开源项目时使用此技能
allowed-tools: Read, Grep, Glob, WebFetch
---

# GitHub Trending 采集技能

## 使用场景

采集 GitHub Trending 上的热门开源项目，按 AI/LLM/Agent 相关主题过滤，排除 Awesome 列表类仓库，生成结构化中文摘要并输出 JSON。

## 执行步骤

### 第 1 步：搜索热门仓库

调用 GitHub API 获取当前热门仓库列表：

```
GET https://api.github.com/search/repositories?q=stars:>100+created:>2025-01-01&sort=stars&order=desc&per_page=100
```

注意事项：
- 可通过 `page` 参数翻页（最大 1000 条结果）
- 注意 GitHub API 限流（未认证 60 次/小时，已认证 5000 次/小时）
- 建议设置 `Accept: application/vnd.github.v3+json` 请求头

### 第 2 步：提取信息

从 API 响应中提取每个仓库的关键字段：

- `full_name`（仓库全名，如 `owner/repo`）
- `html_url`（仓库链接）
- `description`（仓库描述）
- `stargazers_count`（Star 数量）
- `language`（主要编程语言）
- `topics`（主题标签列表）
- `created_at`（创建时间）
- `updated_at`（最后更新时间）

### 第 3 步：过滤

**纳入规则**：仓库的 `topics` 字段包含以下任一关键词即视为 AI 相关：

- `ai`、`machine-learning`、`llm`、`deep-learning`、`nlp`、`computer-vision`
- `generative-ai`、`transformer`、`neural-network`、`ml`、`artificial-intelligence`
- `agent`、`rag`、`langchain`、`llama`、`gpt`、`openai`、`prompt-engineering`

**排除规则**：符合以下任一条件的仓库予以排除：

- 仓库名或 `topics` 包含 `awesome`（排除 Awesome 列表类仓库）
- 仓库名或 `description` 包含 `interview`、`tutorial`、`course`、`roadmap`、`cheatsheet`、`best-practice`
- 仓库 `description` 为空
- `stargazers_count` < 50（过滤掉关注度过低的仓库）
- `created_at` 超过 18 个月（仅保留较新的活跃项目）

### 第 4 步：去重

对过滤后的仓库列表执行去重：

1. 按 `full_name` 去重（同一仓库只保留一条）
2. 对比 `knowledge/raw/` 目录下历史 JSON 文件中的 `items[].url`，排除已采集过的仓库
3. 如 `description` 高度相似（编辑距离 < 5 或 Jaccard 相似度 > 0.9），视为重复，仅保留 Star 数更高者

### 第 5 步：撰写中文摘要

为每个仓库生成中文摘要，使用以下公式：

```
**项目名** — 做什么（一句话概括核心功能）。为什么值得关注：{1-2 句话说明创新点或差异化优势}。
```

要求：
- 摘要控制在 80-150 字
- 基于 `description`、`topics` 和仓库 README 内容（如有）撰写
- 避免直接翻译英文描述，应提炼核心亮点

### 第 6 步：排序取 Top15

1. 按 `stargazers_count` 降序排列
2. 取前 15 个仓库作为最终输出
3. 若不足 15 个，则取全部

### 第 7 步：输出 JSON

将结果写入 `knowledge/raw/github-trending-YYYY-MM-DD.json`（日期为当天日期），JSON 结构如下：

```json
{
  "source": "github-trending",
  "skill": "github-trending",
  "collected_at": "YYYY-MM-DDThh:mm:ss",
  "items": [
    {
      "name": "owner/repo",
      "url": "https://github.com/owner/repo",
      "summary": "中文摘要内容",
      "stars": 12345,
      "language": "Python",
      "topics": ["ai", "llm", "agent"]
    }
  ]
}
```

## 注意事项

- **API 限流**：GitHub API 对未认证请求限制严格，建议配置 `GITHUB_TOKEN` 环境变量提高限额。
- **摘要质量**：中文摘要为人工可读内容，避免堆砌标签或照搬英文描述。
- **去重范围**：仅对比 `knowledge/raw/` 目录下的历史数据，不跨目录去重。
- **错误处理**：API 请求失败时重试 3 次（间隔 1s/2s/4s 指数退避），全部失败则降级写出空列表并记录 ERROR 日志。
- **空结果处理**：若当天无符合条件的仓库，仍生成 JSON 文件（items 为空数组），便于流水线后续步骤识别。
- **文件命名**：日期格式严格使用 `YYYY-MM-DD`，如 `github-trending-2026-05-09.json`。

## 输出格式

最终产物为单个 JSON 文件，路径为：

```
knowledge/raw/github-trending-YYYY-MM-DD.json
```

文件编码为 UTF-8，缩进 2 空格，`collected_at` 使用 ISO 8601 格式（含秒）。

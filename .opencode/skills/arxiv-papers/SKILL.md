---
name: arxiv-papers
description: 当需要采集 arxiv 热门论文时使用此技能
allowed-tools: Read, Grep, Glob, WebFetch
---

# ArXiv 热门论文采集技能

## 使用场景

采集 ArXiv 上的热门学术论文，按 AI/LLM/Agent 相关领域过滤，排除 Awesome 列表类仓库，生成结构化中文摘要并输出 JSON。

## 执行步骤

### 第 1 步：搜索热门论文

调用 ArXiv API 或爬取热门分类页面获取当前热门论文列表：

```
GET https://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=desc&max_results=100
```

或爬取 ArXiv 热门页面：
```
GET https://arxiv.org/list/popular/recent?skip=0&limit=100
```

注意事项：
- 可通过 `start` 参数翻页
- 优先关注 cs.AI、cs.CL、cs.LG、cs.CV、cs.NE 等 AI 相关分类
- 建议限制最近 6 个月内的论文

### 第 2 步：提取信息

从 API 响应中提取每个论文的关键字段：

- `id`（论文 ID，如 `arXiv:2501.12345`）
- `title`（论文标题）
- `abstract`（论文摘要）
- `authors`（作者列表）
- `published`（发布日期）
- `categories`（分类标签）
- `comment`（额外信息，如页数、代码链接）

### 第 3 步：过滤

**纳入规则**：论文的 `categories` 或标题/摘要包含以下任一关键词即视为 AI 相关：

- `cs.AI`（人工智能）、`cs.CL`（计算语言学）、`cs.LG`（机器学习）
- `cs.CV`（计算机视觉）、`cs.NE`（神经与进化计算）
- `stat.ML`（机器学习）、`math.OC`（优化与控制）
- LLM、Transformer、Agent、Multimodal、RLHF、RAG、Generative

**排除规则**：符合以下任一条件的论文予以排除：

- 论文标题或摘要包含 `awesome`（排除 Awesome 列表类论文）
- 论文标题包含 `survey`、`tutorial`、`lecture`、`course`（排除综述/教程类）
- 摘要过于简短（少于 100 字符）
- 发表时间超过 12 个月

### 第 4 步：去重

对过滤后的论文列表执行去重：

1. 按 `id` 去重（同一论文只保留一条）
2. 对比 `knowledge/raw/` 目录下历史 JSON 文件中的 `url`，排除已采集过的论文
3. 如标题高度相似（编辑距离 < 10），视为重复，仅保留发表时间更新者

### 第 5 步：撰写中文摘要

为每篇论文生成中文摘要，使用以下公式：

```
论文名：{中文翻译或原文}。做什么：{一句话概括核心方法或贡献}。为什么值得关注：{1-2 句话说明创新点或应用价值}。
```

要求：
- 摘要控制在 80-150 字
- 基于 `title`、`abstract` 和论文内容撰写
- 避免直接翻译英文摘要，应提炼核心亮点

### 第 6 步：排序取 Top15

1. 按论文引用数或热度降序排列（如无引用数据则按发表日期）
2. 取前 15 篇论文作为最终输出
3. 若不足 15 篇，则取全部

### 第 7 步：输出 JSON

将结果写入 `knowledge/raw/arxiv-papers-YYYY-MM-DD.json`（日期为当天日期），JSON 结构如下：

```json
{
  "source": "arxiv-papers",
  "skill": "arxiv-papers",
  "collected_at": "YYYY-MM-DDThh:mm:ss",
  "items": [
    {
      "name": "论文英文标题",
      "url": "https://arxiv.org/abs/xxxx.xxxxx",
      "summary": "中文摘要内容",
      "stars": 0,
      "category": "cs.AI",
      "keywords": ["llm", "transformer", "agent"]
    }
  ]
}
```

## 注意事项

- **API 限流**：ArXiv API 对请求频率有一定限制，建议添加适当延时
- **摘要质量**：中文摘要为人工可读内容，避免堆砌关键词或照搬英文摘要
- **去重范围**：仅对比 `knowledge/raw/` 目录下的历史数据，不跨目录去重
- **错误处理**：API 请求失败时重试 3 次（间隔 1s/2s/4s 指数退避），全部失败则降级写出空列表并记录 ERROR 日志
- **空结果处理**：若当天无符合条件的论文，仍生成 JSON 文件（items 为空数组），便于流水线后续步骤识别
- **文件命名**：日期格式严格使用 `YYYY-MM-DD`，如 `arxiv-papers-2026-05-10.json`

## 输出格式

最终产物为单个 JSON 文件，路径为：

```
knowledge/raw/arxiv-papers-YYYY-MM-DD.json
```

文件编码为 UTF-8，缩进 2 空格，`collected_at` 使用 ISO 8601 格式（含秒）。
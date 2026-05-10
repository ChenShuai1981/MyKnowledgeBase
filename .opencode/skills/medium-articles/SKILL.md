---
name: medium-articles
description: 当需要采集 medium 每日技术文章时使用此技能
allowed-tools: Read, Grep, Glob, WebFetch
---

# Medium 技术文章采集技能

## 使用场景

采集 Medium 上发布的热门 AI/LLM/Agent 技术文章，按主题过滤，排除 Awesome 列表类内容，生成结构化中文摘要并输出 JSON。

## 执行步骤

### 第 1 步：搜索热门技术文章

通过 Medium 标签页或搜索接口获取当日热门技术文章：

```
GET https://medium.com/_/api/tags/artificial-intelligence/latest?limit=100
GET https://medium.com/_/api/tags/machine-learning/latest?limit=100
GET https://medium.com/_/api/tags/programming/latest?limit=100
```

或通过 Medium RSS 源获取：
```
GET https://medium.com/feed/tag/artificial-intelligence
GET https://medium.com/feed/tag/machine-learning
GET https://medium.com/feed/tag/llm
```

注意事项：
- 优先搜索 `artificial-intelligence`、`machine-learning`、`data-science`、`llm`、`programming` 标签
- 建议设置 `User-Agent` 请求头模拟浏览器访问
- 注意 Medium 的反爬限制，控制请求频率（建议每次请求间隔 ≥ 2 秒）
- 可通过 `?limit=100` 参数提高单次获取数量

### 第 2 步：提取信息

从搜索结果中提取每篇文章的关键字段：

- `title`（文章标题）
- `url`（文章链接，如 `https://medium.com/@author/slug-xxxxx`）
- `author`（作者名称）
- `summary_raw`（原始摘要或副标题）
- `published_at`（发布时间）
- `claps`（鼓掌数，Medium 的热度指标）
- `reading_time`（预估阅读时间，单位分钟）
- `tags`（文章标签列表）
- `publication`（所属出版物，如 `Towards Data Science`，可为空）

### 第 3 步：过滤

**纳入规则**：文章标题、摘要或标签包含以下任一关键词即视为技术相关：

- `ai`、`artificial-intelligence`、`machine-learning`、`deep-learning`、`nlp`
- `llm`、`large-language-model`、`transformer`、`gpt`、`chatgpt`、`openai`
- `agent`、`ai-agent`、`multi-agent`、`autonomous-agent`
- `rag`、`retrieval-augmented-generation`、`vector-database`
- `langchain`、`llamaindex`、`prompt-engineering`、`fine-tuning`
- `generative-ai`、`computer-vision`、`neural-network`
- `mlops`、`model-deployment`、`inference`、`gpu`

**排除规则**：符合以下条件的文章予以排除：

- 标题或标签包含 `awesome`（排除 Awesome 列表类）
- 标题包含 `advertisement`、`sponsored`、`promoted`（排除广告/推广）
- 摘要为空或过短（少于 30 字符）
- `claps` < 10（排除低热度文章，可根据实际情况调整阈值）
- 发布时间超过 30 天（仅保留近期活跃内容）
- 纯个人随笔、非技术类（如 `life`、`travel`、`cooking` 等标签为主）

### 第 4 步：去重

对过滤后的文章列表执行去重：

1. 按 `url` 去重（同一文章只保留一条，忽略 URL 中的 query string 和 `#` 锚点）
2. 对比 `knowledge/raw/` 目录下历史 JSON 文件中的 `items[].url`，排除已采集过的文章
3. 如标题高度相似（编辑距离 < 10 或 Jaccard 相似度 > 0.85），视为重复，仅保留 `claps` 更高者

### 第 5 步：撰写中文摘要

为每篇文章生成中文摘要，使用以下公式：

```
文章名：{原标题}。做什么：{一句话概括核心内容}。为什么值得关注：{1-2 句话说明创新点、实用价值或与当前技术趋势的关联}。
```

要求：
- 摘要控制在 80-150 字
- 基于 `title`、`summary_raw`、`tags` 撰写
- 提炼文章核心观点和技术价值，避免流水账式翻译
- 若文章提出新框架/新思路，应点明其与已有方案的差异化

### 第 6 步：排序取 Top15

1. 按 `claps` 降序排列（claps 越高表示越受欢迎）
2. 若 `claps` 相同，按 `published_at` 降序排列（越新越靠前）
3. 取前 15 篇文章作为最终输出
4. 若不足 15 篇，则取全部

### 第 7 步：输出 JSON

将结果写入 `knowledge/raw/medium-articles-YYYY-MM-DD.json`（日期为当天日期），JSON 结构如下：

```json
{
  "source": "medium-articles",
  "skill": "medium-articles",
  "collected_at": "YYYY-MM-DDThh:mm:ss",
  "items": [
    {
      "name": "文章标题",
      "url": "https://medium.com/@author/article-slug",
      "summary": "中文摘要内容",
      "stars": 0,
      "category": "AI",
      "tags": ["llm", "agent", "rag"]
    }
  ]
}
```

字段说明：
- `name`：文章标题（原文）
- `url`：文章完整链接
- `summary`：第 5 步生成的中文摘要
- `stars`：固定为 0（Medium 无 Star 机制，使用 `claps` 作为排序依据）
- `category`：文章分类，取值 `AI`、`ML`、`工程`、`研究`、`工具`
- `tags`：从文章标签中提取的技术标签（小写英文，2-5 个）

## 注意事项

- **数据来源**：Medium 没有官方公开 API，通常通过 RSS 源（`medium.com/feed/tag/{tag}`）或标签页面获取数据。
- **爬取频率**：Medium 有反爬机制，建议控制请求频率（≥ 2 秒/次），避免 IP 被封。
- **摘要质量**：中文摘要为人工可读内容，应提炼文章核心观点，避免堆砌标签或照搬英文标题。
- **去重范围**：仅对比 `knowledge/raw/` 目录下的历史数据，不跨目录去重。
- **错误处理**：请求失败时重试 3 次（间隔 1s/2s/4s 指数退避），全部失败则降级写出空列表并记录 ERROR 日志。
- **空结果处理**：若当天无符合条件的文章，仍生成 JSON 文件（items 为空数组），便于流水线后续步骤识别。
- **文件命名**：日期格式严格使用 `YYYY-MM-DD`，如 `medium-articles-2026-05-10.json`。
- **claps 与 stars**：Medium 使用 `claps` 作为文章热度指标，输出 JSON 中 `stars` 字段固定为 0，排序依据 `claps`。

## 输出格式

最终产物为单个 JSON 文件，路径为：

```
knowledge/raw/medium-articles-YYYY-MM-DD.json
```

文件编码为 UTF-8，缩进 2 空格，`collected_at` 使用 ISO 8601 格式（含秒）。

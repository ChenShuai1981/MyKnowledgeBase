---
name: producthunt-daily
description: 当需要采集 Product Hunt 每日科技新闻时使用此技能
allowed-tools: Read, Grep, Glob, WebFetch
---

# Product Hunt 每日科技新闻采集技能

## 使用场景

采集 Product Hunt 当日热门科技产品，按 AI/LLM/Agent 相关类别过滤，排除 Awesome 列表类内容，生成结构化中文摘要并输出 JSON。

## 执行步骤

### 第 1 步：搜索热门科技新闻

调用 Product Hunt API 或爬取热门产品页面获取当日热门产品列表：

```
GET https://api.producthunt.com/v2/api/graphql?query={posts(first:100,order:POPULAR){edges{node{id,name,tagline,description,url,thumbnail{url},votesCount,categories{name},maker{name}}}}}
```

或爬取当日热门页面：
```
GET https://www.producthunt.com/
```

注意事项：
- 可通过 `cursor` 参数翻页
- 优先关注 AI、Developer Tools、Productivity、SaaS 等科技相关类别
- 建议限制当日发布的产品

### 第 2 步：提取信息

从 API 响应中提取每个产品的关键字段：

- `id`（产品 ID）
- `name`（产品名称）
- `tagline`（产品标语）
- `description`（产品描述）
- `url`（产品链接）
- `thumbnail`（产品图标）
- `votesCount`（投票数）
- `categories`（分类标签）
- `maker`（制作团队）

### 第 3 步：过滤

**纳入规则**：产品的 `categories` 或名称/描述包含以下任一关键词即视为科技/AI 相关：

- AI、Machine Learning、LLM、Chatbot、Productivity、Developer Tools
- SaaS、No-Code、Automation、API、Open Source
- Mobile App、Browser Extension、Mac、Windows、Linux

**排除规则**：符合以下条件的内容予以排除：

- 名称或描述包含 `awesome`（排除 Awesome 列表类）
- 名称包含 `tutorial`、`course`、`template`、`freebie`、`gift`（排除教程/模板类）
- 描述过于简短（少于 20 字符）
- 投票数低于 50

### 第 4 步：去重

对过滤后的产品列表执行去重：

1. 按 `id` 去重（同一产品只保留一条）
2. 对比 `knowledge/raw/` 目录下历史 JSON 文件中的 `url`，排除已采集过的产品
3. 如名称高度相似（编辑距离 < 5），视为重复，仅保留投票数更高者

### 第 5 步：撰写中文摘要

为每个产品生成中文摘要，使用以下公式：

```
产品名：{中文翻译或原文}。做什么：{一句话概括核心功能}。为什么值得关注：{1-2 句话说明创新点或差异化优势}。
```

要求：
- 摘要控制在 80-150 字
- 基于 `name`、`tagline`、`description` 撰写
- 避免直接翻译英文，应提炼核心亮点

### 第 6 步：排序取 Top15

1. 按 `votesCount` 降序排列
2. 取前 15 个产品作为最终输出
3. 若不足 15 个，则取全部

### 第 7 步：输出 JSON

将结果写入 `knowledge/raw/producthunt-daily-YYYY-MM-DD.json`（日期为当天日期），JSON 结构如下：

```json
{
  "source": "producthunt-daily",
  "skill": "producthunt-daily",
  "collected_at": "YYYY-MM-DDThh:mm:ss",
  "items": [
    {
      "name": "产品英文名称",
      "url": "https://www.producthunt.com/posts/xxx",
      "summary": "中文摘要内容",
      "stars": 0,
      "category": "AI",
      "tags": ["llm", "productivity", "api"]
    }
  ]
}
```

## 注意事项

- **API 限流**：Product Hunt API 有请求频率限制，建议添加适当延时
- **摘要质量**：中文摘要为人工可读内容，避免堆砌关键词或照搬英文描述
- **去重范围**：仅对比 `knowledge/raw/` 目录下的历史数据，不跨目录去重
- **错误处理**：API 请求失败时重试 3 次（间隔 1s/2s/4s 指数退避），全部失败则降级写出空列表并记录 ERROR 日志
- **空结果处理**：若当天无符合条件的科技产品，仍生成 JSON 文件（items 为空数组），便于流水线后续步骤识别
- **文件命名**：日期格式严格使用 `YYYY-MM-DD`，如 `producthunt-daily-2026-05-10.json`

## 输出格式

最终产物为单个 JSON 文件，路径为：

```
knowledge/raw/producthunt-daily-YYYY-MM-DD.json
```

文件编码为 UTF-8，缩进 2 空格，`collected_at` 使用 ISO 8601 格式（含秒）。
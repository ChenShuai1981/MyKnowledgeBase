---
name: weixin-tech
description: 当需要采集微信公众号每日技术文章时使用此技能
allowed-tools: Read, Grep, Glob, WebFetch
---

# 微信公众号技术文章采集技能

## 使用场景

采集微信公众号发布的热门技术文章，按 AI/LLM/Agent 相关主题过滤，排除广告和营销类内容，生成结构化中文摘要并输出 JSON。

## 执行步骤

### 第 1 步：搜索热门技术文章

通过微信搜索或第三方数据平台获取当日热门技术文章：

```
GET https://weixin.sogou.com/weixin?type=2&query=AI+技术&ie=utf8
```

或使用其他微信文章聚合平台：
```
GET https://article.gpt.cn/api/articles?category=tech&sort=hot&limit=100
```

注意事项：
- 优先搜索 AI、机器学习、大模型、程序员、技术等关键词
- 建议限制最近 7 天内发布的文章
- 部分平台需要登录或 API Token

### 第 2 步：提取信息

从搜索结果中提取每篇文章的关键字段：

- `id`（文章 ID）
- `title`（文章标题）
- `author`（作者/公众号名称）
- `abstract`（文章摘要）
- `url`（文章链接）
- `publishTime`（发布时间）
- `readCount`（阅读量）
- `likeCount`（点赞数）

### 第 3 步：过滤

**纳入规则**：文章标题或摘要包含以下任一关键词即视为技术相关：

- AI、人工智能、机器学习、深度学习、大模型、LLM
- ChatGPT、OpenAI、Claude、GPT
- Agent、智能体、LangChain、RAG
- Python、Java、Go、JavaScript、TypeScript
- 前端、后端、架构、DevOps、云原生

**排除规则**：符合以下条件的内容予以排除：

- 标题或摘要包含 `awesome`（排除 Awesome 列表类）
- 标题包含 `广告`、`推广`、`优惠券`、`抽奖`（排除营销类）
- 标题包含 `今日头条`、`快手`、`抖音`、`视频号`（排除短视频类）
- 摘要过于简短（少于 50 字符）
- 阅读量低于 1000（排除低热度文章）

### 第 4 步：去重

对过滤后的文章列表执行去重：

1. 按 `id` 或 `url` 去重（同一篇文章只保留一条）
2. 对比 `knowledge/raw/` 目录下历史 JSON 文件中的 `url`，排除已采集过的文章
3. 如标题高度相似（编辑距离 < 10），视为重复，仅保留阅读量更高者

### 第 5 步：撰写中文摘要

为每篇文章生成中文摘要，使用以下公式：

```
文章名：{标题}。做什么：{一句话概括核心内容}。为什么值得关注：{1-2 句话说明价值点或实用性}。
```

要求：
- 摘要控制在 80-150 字
- 基于 `title`、`abstract` 撰写
- 提炼文章核心观点和技术价值

### 第 6 步：排序取 Top15

1. 按 `readCount` 降序排列（如无阅读量则按发布时间）
2. 取前 15 篇文章作为最终输出
3. 若不足 15 篇，则取全部

### 第 7 步：输出 JSON

将结果写入 `knowledge/raw/weixin-tech-YYYY-MM-DD.json`（日期为当天日期），JSON 结构如下：

```json
{
  "source": "weixin-tech",
  "skill": "weixin-tech",
  "collected_at": "YYYY-MM-DDThh:mm:ss",
  "items": [
    {
      "name": "文章标题",
      "url": "https://mp.weixin.qq.com/s/xxx",
      "summary": "中文摘要内容",
      "stars": 0,
      "category": "AI",
      "tags": ["llm", "tutorial", "python"]
    }
  ]
}
```

## 注意事项

- **数据来源**：微信公众号文章通常需要通过第三方平台或微信搜索获取，部分平台有 API 限制
- **摘要质量**：中文摘要为人工可读内容，应提炼文章核心观点，避免流水账式总结
- **去重范围**：仅对比 `knowledge/raw/` 目录下的历史数据，不跨目录去重
- **错误处理**：API 请求失败时重试 3 次（间隔 1s/2s/4s 指数退避），全部失败则降级写出空列表并记录 ERROR 日志
- **空结果处理**：若当天无符合条件的文章，仍生成 JSON 文件（items 为空数组），便于流水线后续步骤识别
- **文件命名**：日期格式严格使用 `YYYY-MM-DD`，如 `weixin-tech-2026-05-10.json`

## 输出格式

最终产物为单个 JSON 文件，路径为：

```
knowledge/raw/weixin-tech-YYYY-MM-DD.json
```

文件编码为 UTF-8，缩进 2 空格，`collected_at` 使用 ISO 8601 格式（含秒）。
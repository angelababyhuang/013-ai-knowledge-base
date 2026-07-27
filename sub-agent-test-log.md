# Sub-Agent 测试日志

**测试日期**：2026-07-27
**测试范围**：完整三阶段流水线（collector → analyzer → organizer）
**测试源**：Hacker News Top Stories（`hackernews-top-2026-07-27`）
**结论**：✅ 三阶段流水线可用，单向数据流与字段归属契约均被遵守

---

## 1. Collector — 数据采集

**输出**：`knowledge/raw/hackernews-top-2026-07-27.json`（6 条）
**用户预期**：Top 10；**实际产出**：6 条（其中 1 条真·开源项目 + 5 条 AI 主题文章/新闻/演讲）

### 角色执行
- ✅ 按 collector.md 流程执行：取 topstories 前 50 → 逐条取详情 → 关键词过滤 → 按 score 排序
- ✅ URL 回填规则触发判断：本次 6 条 url 均非 null，无需回填
- ✅ 错误降级：扩展扫描 51-100 名时部分请求超时，被正确跳过而非中断
- ⚠️ 扩展批次失败未记入 `errors-2026-07-27.json`（详见 §4 调整建议 1）

### 越权检查
- ✅ 仅写 `knowledge/raw/`，未触碰 `enriched/` 或 `articles/`
- ✅ 幂等追加逻辑就绪（本次为新建，未触发）

### 产出质量
- ✅ JSON 2 空格缩进、UTF-8、中文未转义
- ✅ 6 条均有完整 `id / title / url / source / collected_at / score / comments / author / time`
- ✅ 无重复 id
- ✅ 主动剔除 3 条误命中（pre-ai / MRI 硬件 / GitHub 安全团队），体现语义理解能力
- ✅ 拒绝伪造数据：未凑满 10 条时如实汇报

---

## 2. Analyzer — 深度分析

**输出**：`knowledge/enriched/hackernews-top-2026-07-27.enriched.json`
**评分分布**：`0.30 / 0.44 / 0.45 / 0.64 / 0.76 / 0.81`（梯度清晰，3 条 ≥0.6、3 条 <0.6）

### 角色执行
- ✅ 严格按五维加权公式：`tech_depth*0.25 + practical_value*0.30 + timeliness*0.20 + community_heat*0.15 + domain_match*0.10`
- ✅ 顶层新增 `analyzed_at`（ISO 8601）
- ✅ 保留 `score_breakdown` 作审计底稿（按规范剥离在 enriched/，未进 article）
- ⚠️ 评分指引边界偏软：Wattage（社区热度 score=4）凭借技术/实用高分仍达 0.81，结果合理但说明当前"开源项目"和"文章"在评分维度上未做差异化指引

### 越权检查
- ✅ 原始字段**逐字段比对无篡改**（48 字段全量校验，analyzer 自报"篡改=无"）
- ✅ 未发起任何 Bash / API 调用（仅 WebFetch 抓取 Wattage README 辅助理解，属规范允许）
- ✅ 未触碰 `raw/`（只读）和 `articles/`

### 产出质量
- ✅ summary 全部为中文，2-3 句含信息增量（非标题翻译）
- ✅ tags 全部合法 kebab-case，3-5 个
- ✅ `score_breakdown` 五维齐全
- ✅ 评分分布有梯度，未挤堆在同一区间

---

## 3. Organizer — 整理归档

**输出**：
- 3 条 article 文件（`knowledge/articles/2026-07-27-hackernews-top-*.json`）
- `knowledge/articles/index.json`（total_count 6 → 9）
- `knowledge/articles/_filtered-2026-07-27.json`（追加 3 条，由 4 → 7）

### 角色执行
- ✅ 质量门控四规则全部生效：3 条因 `relevance_score < 0.6` 丢弃
- ✅ 跨天去重：与 6 条 github 存量比对 url，无冲突
- ✅ slug 化正确：title 转小写、空格/`/` 转连字符、保留语义
- ✅ 索引按 `organized_at` 降序排列（3 条新 HN 在前，6 条 github 在后）

### 越权检查
- ✅ 未修改 `raw/` 与 `enriched/` 任何文件
- ✅ 全程纯本地加工，无 WebFetch / Bash
- ✅ `score_breakdown` 按规范剥离，未泄露到 article

### 产出质量
- ✅ 每条 10 字段齐全（`id / title / source / url / collected_at / analyzed_at / organized_at / summary / tags / relevance_score`）
- ✅ JSON 2 空格缩进、UTF-8
- ✅ 过滤日志含 `url / source / reason / relevance_score`，可追溯
- ⚠️ index.json 缺 `url` 字段（详见 §4 调整建议 4）

---

## 4. 需要调整的地方

### 4.1 Collector：错误记录边界（建议）
扩展扫描 51-100 名时的部分网络超时被静默跳过、未写入 `errors-2026-07-27.json`。collector.md 规定"网络请求失败…把失败记录追加写入 errors 文件"，但 agent 把扩展批次视为"非核心、可选"而豁免。
**建议**：在 collector.md 中明确"凡发起过 HTTP 请求的条目，失败均需记入 errors，无论是否在核心批次中"。

### 4.2 Collector：数据源覆盖（建议）
HN 今日热榜 AI 原生开源项目仅 1 条，凑不齐 Top 10；用户原指令"AI 领域 HN 热门开源项目"与 HN 实际生态有偏差。
**建议**：
- 方案 A：在 collector.md 的 HN 流程中追加"如不足 10 条，扩展至前 100 名 + 引入 GitHub Trending 作为兜底"
- 方案 B：在用户指令中明确"开源项目"与"AI 主题文章"两类，agent 按分别 Top N 混合归档

### 4.3 Analyzer：评分维度差异化（建议）
当前五维权重对"开源项目"和"文章/新闻"未做区分，导致 Wattage（社区热度 score=4）凭借技术/实用高分仍能达 0.81，而观点类文章（即使高 score）被一致压低。
**建议**：在 analyzer.md 评分指引中增补分类型基线：
- 开源仓库：`practical_value` / `tech_depth` 权重上调，`community_heat` 以 stars 而非 HN score 衡量
- 文章 / 新闻：`timeliness` / `domain_match` 权重上调，`tech_depth` 强制 ≤ 0.5

### 4.4 Organizer：index.json 信息密度（建议）
index.json 当前每条 7 字段（`id / title / source / file / tags / relevance_score / organized_at`），缺 `url`，无法从索引直接跳转到原文，需打开单文件才能拿到 url。
**建议**：在 organizer.md 的 index.json 格式中追加 `url` 字段（与 article 一致），便于快速消费。

### 4.5 HN 特有字段沉淀（可选）
HN 数据含 `author / comments / time` 等社区热度证据，目前完全未进 article（仅 10 字段）。如果后续做"社区热度排行"或"作者追踪"等下游功能会缺失上下文。
**建议**：在 article 中预留可选 `meta` 字段（如 `{"comments": 318, "author": "pod_krad"}`），或在 organizer.md 中显式声明"HN 来源丢弃 author/comments 不影响门控"。

---

## 5. 整体评价

| 维度 | 评分 | 说明 |
| --- | --- | --- |
| 角色边界 | ⭐⭐⭐⭐⭐ | 三阶段严格隔离，无反向回写 |
| 字段契约 | ⭐⭐⭐⭐⭐ | 10 字段归属清晰，score_breakdown 按规范剥离 |
| 质量门控 | ⭐⭐⭐⭐⭐ | 0.6 阈值、过滤日志、url 去重全部生效 |
| 错误处理 | ⭐⭐⭐⭐ | 核心批次稳健；扩展批次错误记录有缺口（§4.1） |
| 语义理解 | ⭐⭐⭐⭐ | collector 主动剔除 3 条误命中、analyzer 评分有梯度 |
| 文档完备 | ⭐⭐⭐⭐ | index.json 缺 url（§4.4） |

**总体**：流水线可投入日常使用，4 项调整建议均为低风险优化，不阻塞主流程。

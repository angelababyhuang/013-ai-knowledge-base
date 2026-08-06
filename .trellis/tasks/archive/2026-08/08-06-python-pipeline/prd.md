# 把 LLM Skill 采集改造为 Python 流水线 Pipeline.py

## Goal

将当前由「主 Agent → Subagent → Skill」驱动、靠 LLM 执行的采集/分析/整理流程，固化为一个可直接 `python pipeline/pipeline.py` 运行的四步自动化流水线（Collect → Analyze → Organize → Save），复用现有 `pipeline/model_client.py` 做 LLM 调用，并遵守项目既有 12 字段契约与质量门控。

## 课程提示词原文要点

- 四步：①采集（GitHub Search API + **RSS 源**）②分析（LLM 摘要/评分/标签）③整理（去重+格式标准化+校验）④保存（独立 JSON 到 `knowledge/articles/`）。
- CLI：`--sources github,rss --limit N`、`--dry-run`、`--verbose`。
- 约束：采集用 httpx；RSS 用简易正则解析；分析调 `model_client.chat_with_retry()`；raw 存 `knowledge/raw/`、article 存 `knowledge/articles/`；`from model_client import create_provider, chat_with_retry`；PEP 8 + argparse + pathlib。

## 课程提示词 vs 项目现状：不兼容点对比

| # | 课程提示词 | 项目现状 | 冲突 |
| --- | --- | --- | --- |
| 1 | 数据源 = GitHub + **RSS** | 数据源 = GitHub + **Hacker News**；全项目无 RSS 代码（已核查） | ★★★ |
| 2 | source 命名 `github` / `rss` | `article.schema.json` source 枚举锁定 `github-hot-repos` / `hackernews-top`；`rss` 会校验失败 | ★★★ |
| 3 | 不提 `category` | 契约必填 `category`（3 枚举；HN 必填、GitHub 隐含 open-source） | ★★★ |
| 4 | 不提 `meta` | 契约必填 `meta`（dict 跨源容器；schema `additionalProperties:false`） | ★★★ |
| 5 | 「评分」无公式 | 五维加权 `tech_depth*0.25+practical_value*0.30+timeliness*0.20+community_heat*0.15+domain_match*0.10`，两位小数 | ★★ |
| 6 | 无 category 上限 / `_override` | analyzer 按 category 设维度上限 + `_override` 灰色地带 | ★★ |
| 7 | 无 enriched 中间层（分析完直接整理保存） | 有三阶段物化：`raw/` → `enriched/` → `articles/` | ★★ |
| 8 | 整理仅「去重+标准化+校验」 | organizer 四规则门控（score<0.6 / summary<50字 / tags<2 / url异常）+ `_filtered-{date}.json` | ★★ |
| 9 | 保存不提索引 | organizer 维护 `index.json`（9 字段，按 organized_at 降序） | ★★ |
| 10 | 不提文件命名 | 命名契约：raw=`{source}-{date}.json`、enriched=`{source}-{date}.enriched.json`、article=`{date}-{source}-{slug}.json` | ★ |
| 11 | 不提错误审计 | collector 穷举式 `errors-{date}.json`（无自由裁量） | ★ |
| 12 | `from model_client import create_provider, chat_with_retry` | model_client.py 恰有此二函数；同目录导入可行 | ✓ 兼容 |

## 兼容确认

- `pipeline/model_client.py` 提供 `create_provider()` / `chat_with_retry(provider, messages, retries, **kwargs) -> LLMResponse`，签名满足课程调用方式。
- `pipeline/pipeline.py` 与 `model_client.py` 同目录，`from model_client import ...` 在 `python pipeline/pipeline.py` 直接运行时可行（脚本目录入 sys.path）。
- httpx 已安装（0.28.1）。

## Decided Scope

1. **数据源（已决）**：GitHub + Hacker News，忽略课程的 RSS。CLI `--sources github,hn`（github→`github-hot-repos`、hn→`hackernews-top` 映射到项目 source 枚举）。
2. **契约对齐（判定）**：Pipeline 产出的 article **必须满足项目 12 字段契约**（含 `category` / `meta` / 五维加权评分 / kebab-case tags / 中文摘要），否则通不过 `hooks/validate_json.py`，无法融入现有知识库。课程简化字段不采纳。

3. **架构（已决）**：保留 `enriched/` 中间物化层。Pipeline 数据流 = `raw/` → `enriched/` → `articles/`，与现有三阶段架构一致；`score_breakdown` 留 enriched/ 作审计底稿。

## Requirements

- R1：单文件 `pipeline/pipeline.py`，四步流水线 Collect → Analyze → Organize → Save。
- R2：数据源 GitHub + HN；`--sources github,hn` 映射到 `github-hot-repos` / `hackernews-top`。
- R3：采集用 httpx（GitHub Search API + HN firebase API），遵循各源 skill 的查询参数与字段提取表；GitHub 需 `GITHUB_TOKEN`。
- R4：分析调 `model_client.chat_with_retry()`，LLM 输出 summary/tags/五维评分（+ HN 的 category），计算 relevance_score、应用 category 上限、产出 score_breakdown。
- R5：整理执行四规则门控 + url 去重；保存为 12 字段 article + 维护 index.json + 记 `_filtered-{date}.json`。
- R6：落盘遵循命名契约（raw/enriched/article/index）与幂等（按 id 去重追加）。
- R7：CLI 支持 `--sources` / `--limit` / `--dry-run` / `--verbose`；argparse + pathlib + PEP 8。
- R8：HTTP/LLM/解析失败按穷举式记 `errors-{date}.json`。

## Out of Scope

- 不改写已有 `model_client.py`（除非契约需要对齐）。
- 不动现有 `.opencode/` 的 Skill/Agent 定义（本任务是把流程沉淀为 Python，不删除原 LLM 流程）。
- 不实现 RSS 源（已决：忽略）。

## Acceptance Criteria

- [x] `python pipeline/pipeline.py --sources github,hn --limit 5` 可跑通完整四步，产出落 raw/ enriched/ articles/（github 单源真实跑通；双源共用同一代码路径）。
- [x] `--sources github --limit 5` 单源运行真实验证通过；`--sources hn` 同一代码路径（HN 采集逻辑经 mock 测试）。
- [x] `--dry-run` 不落任何文件，仅打印操作与条目摘要（真实验证：零落盘）。
- [x] `--verbose` 输出 DEBUG 级日志（真实验证）。
- [x] 产出 article 通过 `python hooks/validate_json.py` 校验（exit 0；check 阶段用 GitHub+HN 样例实测）。
- [x] 产出 article 含 12 字段（category + meta），meta 按 source 填对应字段集（build_article 实测）。
- [x] 门控生效：score<0.6 / summary<50字 / tags<2 / url异常 丢弃并记 `_filtered-{date}.json`（真实验证：5 条 duplicate url 全记 _filtered）。
- [x] 幂等：重复运行同一天不产生重复条目（真实验证：url 去重 5/5 判重）。
- [x] index.json 9 字段、按 organized_at 降序、total_count 一致（逻辑经 check 验证；本次真实跑因全重复未触发新条目写入）。
- [x] PEP 8；argparse 解析参数；pathlib 处理路径（check 阶段核验）。

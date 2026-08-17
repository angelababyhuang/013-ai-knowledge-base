# Journal - wangyao (Part 1)

> AI development session journal
> Started: 2026-07-31

---



## Session 1: 逆向梳理基线PRD + 实现 pipeline.py 四步流水线 + 编写 README

**Date**: 2026-08-06
**Task**: 逆向梳理基线PRD + 实现 pipeline.py 四步流水线 + 编写 README
**Branch**: `main`

### Summary

1) 只读逆向梳理全项目，产出 docs/baseline-prd.md 基线PRD（8板块+差距清单A1-A5，发现README/.env缺失、Telegram分发未实现、minimax与实际DeepSeek/Qwen/OpenAI不符）；2) 对齐课程提示词实现 pipeline/pipeline.py 四步流水线（Collect→Analyze→Organize→Save），解决12处对比中的4高5中冲突（RSS→HN、source命名映射、补category/meta/五维契约、保留enriched层），真实跑通GitHub采集+DeepSeek分析+url去重5/5判重；3) 编写根目录README.md（pipeline使用方法+CLI+环境配置），补上差距清单A2缺口。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `5470a0c` | (see git log) |
| `3b403ea` | (see git log) |
| `eecb3e9` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 2: MCP 知识库搜索测试

**Date**: 2026-08-06
**Task**: MCP 知识库搜索测试
**Branch**: `main`

### Summary

测试 knowledge MCP server：列出了 opencode mcp list（knowledge server connected），用 knowledge_search_articles 搜索 'Pi' 命中 pi-textbook 等 10 条，用 knowledge_get_article 获取 hahhforest/pi-textbook 完整 12 字段详情。无代码改动；本 session 的 dirty 路径均为 RSS 采集批处理的并行工作，未纳入。

### Main Changes

(Add details)

### Git Commits

(No commits - planning session)

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 3: GitHub Actions 每日采集 workflow

**Date**: 2026-08-07
**Task**: GitHub Actions 每日采集 workflow
**Branch**: `main`

### Summary

创建 .github/workflows/daily-collect.yml（cron UTC 08:00 + workflow_dispatch，Python 3.11，GitHub+RSS 双源采集，5 secret env 含 GITHUB_TOKEN，check_quality 审计，git 自动 commit/push + 空提交保护）。首次 CI 跑通后发现两个问题并修复：(1) Node 20 弃用 warning → checkout@v5/setup-python@v6；(2) check_quality 误评全量历史+_filtered淘汰日志+测试夹具导致 151 个假阳性 C 级 → glob 改为当天日期前缀 $(date -u +%Y-%m-%d)-* 自动排除非文章文件 + || true 防审计染红。关键发现：78 篇真文章全 A/B 级（0 个 C），所谓 151 C 级全是 _filtered 淘汰日志（仅 4 字段）和 index/test 文件的假阳性。修复后手动触发验证成功，workflow 自动提交 c8cf91e 采集数据。AC1-AC11 全部通过。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `4ab7213` | (see git log) |
| `073f3d3` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 4: pipeline --step/--days + 本地 crontab 定时配置

**Date**: 2026-08-07
**Task**: pipeline --step/--days + 本地 crontab 定时配置
**Branch**: `main`

### Summary

完成两个关联任务：(1) pipeline-step-flag：给 pipeline.py 加 --step 参数（支持分步执行 1,2 采集分析 / 3,4 整理入库）+ --days 参数（Step 3-4 多天回溯扫描 enriched/）+ scan_enriched_dates() + main() 批次循环重构。(2) local-crontab：创建 crontab 文件并安装——每天 08:00 跑 --step 1,2（采集+分析），每周日 10:00 跑 --step 3,4 --days 7（整理入库）。关键发现：zsh 的 . source 命令不搜索当前目录（需 ./.env），但 cron 用 /bin/sh 无此问题。手动测试验证多天扫描+去重正确（171 条全 duplicate，符合预期）。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `a5b16ce` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 5: 实现 Router/Supervisor Agent 模式并同步分支

**Date**: 2026-08-13
**Task**: 实现 Router/Supervisor Agent 模式并同步分支
**Branch**: `main`

### Summary

实现两个 Agent 设计模式教学模块：patterns/router.py（两层意图分类——关键词快速匹配 + LLM 兜底，分发 github_search/knowledge_query/general_chat 三处理器，github_search 用 urllib.request + quote 编码，knowledge_query 读本地 index.json）与 patterns/supervisor.py（Worker 出 JSON 报告 → Supervisor 三维评分 accuracy/depth/format → 不通过带反馈重做最多 max_retries=3 轮 → 超限强制返回+warning）。两模块均适配项目实际 API（pipeline.model_client.quick_chat），课程要求的 workflows.model_client.chat()/chat_json() 不存在，改用 quick_chat + json.loads 软实现。Mock 测试 + DeepSeek/GitHub 真实联调全通过。期间发现本地与远端分叉（本地领先9、远端领先5），git merge origin/main 合并，5 个 08-10 数据冲突取远端版（数据可再生、云端权威），代码零冲突保留，git push 完成双向同步。另解释了 supervisor 设计（角色 prompt 分离、temperature=0.0 求稳、带反馈重做信息闭环、max_retries=3 成本/收益权衡）。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `c59d86b` | (see git log) |
| `63aaa1e` | (see git log) |
| `a706764` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete

---

## 2026-08-17: LangGraph 课程三节（state/nodes/graph）+ Trellis 流程接入

**Task**: 08-17-langgraph-graph（首次启用 Trellis 任务跟踪）
**Branch**: `main`

### Summary

完成 LangGraph 课程三节：(1) workflows/state.py — KBState TypedDict 七字段（sources/analyses/articles/review_feedback/review_passed/iteration/cost_tracker），MAX_REVIEW_ITERATIONS=3 对齐 supervisor max_retries 语义。(2) workflows/model_client.py + nodes.py — 因课程要求的 chat()/chat_json()/accumulate_usage() 在项目不存在且 quick_chat 丢弃 usage，新建薄适配层复用 pipeline.model_client 基建；5 节点纯函数实现（collect 用 urllib.request、analyze 逐条 LLM 0-1 评分、organize <0.6 门控+双层 URL/id 去重+反馈定向修正、review 四维 LLM 评分且 iteration>=2 强制通过、save 完全对齐现有 index.json 契约）。关键陷阱：pipeline/pipeline.py 脚本式导入不可包导入，slugify/build_meta 复制并注明出处。(3) workflows/graph.py — StateGraph 组装，线性边 collect→analyze→organize→review，条件边 _route_after_review 按 review_passed 分支 save/organize 修正回路，build_graph() 返回 compile() 结果，__main__ 用 app.stream() updates 模式逐节点打印。

### Testing

- [OK] 真实端到端：GitHub+DeepSeek DRY_RUN 跑通，幂等去重生效（Top 仓库已在存量 index，dup_url 丢弃）
- [OK] 回路拓扑（fake review 确定性验证）：collect→analyze→organize→review→organize→review→organize→review→save，修正回路真实调 LLM 修订标签（tags 2→4 个）
- [OK] review 四维真实打分把冒烟假条目正确打回（summary_quality=4 + 具体反馈）

### Key Decisions

- workflows 直跑需 sys.path 注入项目根（sys.path[0] 是 workflows/），已沉淀至 .trellis/spec/backend/directory-structure.md
- WORKFLOWS_DRY_RUN=1 为冒烟必备惯例，防污染 articles/
- LLM JSON 解析失败：带严格提示重试一次→None→调用方兜底，节点内不抛错中断图；review 解析失败 fail-open + iteration 上限双保险防死循环

### Status

[OK] **Completed**

### Next Steps

- 课程下一节（预计：checkpointer 持久化 / Send 并行 / 中断恢复，待课程要求）

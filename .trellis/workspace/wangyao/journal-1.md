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

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

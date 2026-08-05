# 执行计划：基线 PRD 逆向梳理

## 交付物

- `docs/baseline-prd.md` —— 已实现功能基线 PRD（业务流程 + 代码实现两层 + 差距清单附录）。

## 前置事实来源（已扫描核实，执行时直接引用）

- 架构/编排：`AGENTS.md`、`.opencode/agents/{collector,analyzer,organizer}.md`
- 采集 procedure：`.opencode/skills/github-hot-repos/SKILL.md`、`.opencode/skills/hackernews-top/SKILL.md`
- 分析 procedure：`.opencode/skills/tech-summary/SKILL.md`
- 契约：`schemas/article.schema.json`、`schemas/quality-rubric.json`
- 校验：`hooks/validate_json.py`、`hooks/check_quality.py`
- LLM 基础设施：`pipeline/model_client.py`（依赖 `requirements.txt` = httpx）
- 决策/测试：`docs/decisions/*.md`、`sub-agent-test-log.md`
- 数据资产：`knowledge/{raw,enriched,articles}/`

## 执行清单

- [ ] 1. 拟定 `docs/baseline-prd.md` 结构：概述 → 架构与编排 → 8 板块（采集/分析/整理/契约校验/LLM/决策测试/数据资产）→ 差距与漂移清单附录。
- [ ] 2. 逐板块撰写，业务流程与代码实现两层并行，每板块标注来源 `file_path`。
- [ ] 3. 撰写附录差距清单：Telegram/飞书分发未实现、README.md/.env.example 缺失、minimax 与实际 DeepSeek/Qwen/OpenAI 不符。
- [ ] 4. 交叉核对：对照 prd.md「Confirmed Facts」与源码，确保无虚构/夸大。
- [ ] 5. 校验产出文档可被正常阅读（Markdown 结构完整、路径引用正确）。

## 验证

- 只读校验：执行后 `git status` 除新增 `docs/baseline-prd.md` 与任务目录文件外，无对现有代码/数据的改动。
- 覆盖校验：对照 prd.md Acceptance Criteria 逐项打勾。

## 风险与回滚

- 风险：对某板块实现理解偏差 → 回写前重读对应源码文件核对。
- 回滚：产出为新增文档，删除即可，无数据/代码风险。

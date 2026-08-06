# GitHub Actions 每日定时采集工作流

## Goal

创建 `.github/workflows/daily-collect.yml`，让 AI 知识库 pipeline 每天 UTC 08:00 在 GitHub Actions 上自动跑「采集→分析→整理→保存」全流程，并把当日新增条目自动 commit 回仓库；同时支持手动触发。

## Background / Context

- 项目已有 `pipeline/pipeline.py` 四步流水线（Collect→Analyze→Organize→Save），CLI 参数 `--sources github,rss --limit 20 --verbose` 已验证完全兼容。
- pipeline 内置 `validate_json.py` 结构校验（pipeline.py:911-925，事后调用），但**不调用** `check_quality.py`。
- pipeline **不做 git 操作**，commit/push 须在 workflow 内实现。
- pipeline 读取 `GITHUB_TOKEN`（pipeline.py:190）做 GitHub Search API 认证，缺失时限额仅 60 次/小时。
- `.github/workflows/` 目录当前不存在。
- `.gitignore` 已忽略 `.env`，secret 不会泄露。

## Requirements

### 功能需求（课程 10 条 + 2 处修正）

1. **定时触发**：每天 UTC 08:00（北京时间 16:00）自动运行（`cron: '0 8 * * *'`）。
2. **手动触发**：支持 `workflow_dispatch`。
3. **权限**：`permissions: contents: write`（允许 commit/push）。
4. **运行环境**：Python 3.11，启用 pip 缓存。
5. **依赖安装**：`pip install -r requirements.txt`（现有 `httpx` + `pyyaml`）。
6. **主命令**：`python3 pipeline/pipeline.py --sources github,rss --limit 20 --verbose`。
7. **LLM 密钥**（4 个，对应 model_client.py 已有 env）：`LLM_PROVIDER` / `DEEPSEEK_API_KEY` / `QWEN_API_KEY` / `OPENAI_API_KEY`。
8. **质量校验**：采集后运行 `validate_json.py` 和 `check_quality.py` 校验文章。
9. **自动提交**：git commit + push，commit 消息包含文章数量和日期。
10. **空提交保护**：没有新数据则不提交（避免空 commit）。

### 修正项（基于兼容性调研）

- **R1（补 GITHUB_TOKEN）**：课程需求 7 漏列 `GITHUB_TOKEN`。GitHub Actions 自动提供 `${{ secrets.GITHUB_TOKEN }}`，需在 workflow env 透传给 pipeline（`os.getenv("GITHUB_TOKEN")`），否则 `--limit 20` 易撞 60 次/小时未认证限流。
- **R2（check_quality 显式调用）**：pipeline 不调用 `check_quality.py`，须在 workflow 加一步显式调用（脚本已存在，无需重写）。

### 约束

- 不修改 `pipeline/pipeline.py` 及任何现有源码。
- 只新建 `.github/workflows/daily-collect.yml` 一个文件。
- secret 仅通过 `${{ secrets.* }}` 引用，绝不硬编码。

## Acceptance Criteria

- [x] AC1：`.github/workflows/daily-collect.yml` 存在且 YAML 语法合法。✅ YAML OK
- [x] AC2：含 `on.schedule.cron: '0 8 * * *'` 和 `on.workflow_dispatch`。✅ line 5-6
- [x] AC3：含 `permissions: contents: write`。✅ line 9
- [x] AC4：使用 `actions/setup-python@v5`，python-version `3.11`，`cache: 'pip'`。✅ line 28-30
- [x] AC5：`pip install -r requirements.txt` step 存在。✅ line 33
- [x] AC6：主命令 step 含 `--sources github,rss --limit 20 --verbose`。✅ line 36
- [x] AC7：env 块含 4 个 LLM secret + `GITHUB_TOKEN` 引用（共 5 个，均来自 `${{ secrets.* }}`）。✅ line 16-20
- [x] AC8：存在调用 `hooks/check_quality.py` 的 step（对当日 `knowledge/articles/*.json`）。✅ line 47
- [x] AC9：存在 git add/commit/push step，commit 消息含文章数量与日期。✅ line 56-61
- [x] AC10：空数据时不产生 commit（用 `git diff --staged --quiet` 或等价逻辑判断）。✅ line 54
- [ ] AC11：workflow_dispatch 手动触发能成功跑通（运行时验证，需推送后在 GitHub 手动触发）。⏳ 留待后续

## Notes

- `validate_json.py` pipeline 已内置调用（事后校验，pipeline.py:914），workflow 不必重复；如要加作 CI 双保险，须 `continue-on-error` 避免阻塞。
- `check_quality.py` 是事后审计工具（输出 A/B/C 级，不写回 article、不影响门控），调用失败不应中断 commit。
- 文章落盘路径：`knowledge/articles/{date}-{source}-{slug}.json`，另有 `knowledge/raw/`、`knowledge/enriched/`、`index.json` 均需纳入 commit。

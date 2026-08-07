# Implement — daily-collect-workflow

## 交付物

仅 1 个新文件：`.github/workflows/daily-collect.yml`

## 执行清单（按序）

### Step 1：创建 workflow 文件
- [x] 新建 `.github/workflows/` 目录
- [x] 写 `daily-collect.yml`，按 design.md 的 D1-D6 结构组织：
  - [x] `name: Daily Collect`
  - [x] `on:` schedule.cron `'0 8 * * *'` + workflow_dispatch
  - [x] `permissions: contents: write`
  - [x] job 级 `env:` 5 个 secret 引用（LLM_PROVIDER/DEEPSEEK_API_KEY/QWEN_API_KEY/OPENAI_API_KEY/GITHUB_TOKEN）
  - [x] `runs-on: ubuntu-latest`
  - [x] step1: `actions/checkout@v4`
  - [x] step2: `actions/setup-python@v5`（python 3.11 + cache pip）
  - [x] step3: `pip install -r requirements.txt`
  - [x] step4: 跑 pipeline 主命令
  - [x] step5: 跑 check_quality.py（continue-on-error + 通配符保护）
  - [x] step6: git add/commit/push（含空提交保护，按 D4 模板）

### Step 2：本地验证（静态）
- [x] YAML 语法校验：`python3 -c "import yaml; yaml.safe_load(open('.github/workflows/daily-collect.yml'))"`
- [x] 逐条核对 AC1-AC10（全部命中）

### Step 3：提交
- [ ] git add `.github/workflows/daily-collect.yml`
- [ ] commit: `ci: 新增每日定时采集 workflow（UTC 08:00，GitHub+RSS，自动 commit）`
- [ ] （push 由用户决定，本任务不自动 push）

## 验证命令

```bash
# YAML 语法合法性
python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/daily-collect.yml')); print('YAML OK')"

# AC 核对（grep 关键字段）
grep -c "workflow_dispatch\|0 8 \* \* \*\|contents: write\|3.11\|check_quality\|GITHUB_TOKEN" .github/workflows/daily-collect.yml

# 确认 pipeline CLI 仍兼容
python3 pipeline/pipeline.py --help | grep -E "sources|limit|verbose"
```

## 完成判定

- AC1-AC10 全部勾选（AC11 手动触发验证留作后续）。
- YAML 语法合法。
- 不改动任何现有源码（`git diff --stat` 仅含新文件）。

## Rollback

删 `.github/workflows/daily-collect.yml` 即可，无副作用。

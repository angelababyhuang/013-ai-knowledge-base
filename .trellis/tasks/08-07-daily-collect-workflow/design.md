# Design — daily-collect-workflow

## 技术决策

### D1：Secret 链路（不经过 .env 文件）

pipeline 只用 `os.getenv()` 读进程环境变量，**不读 `.env` 文件**（无 python-dotenv 依赖）。GitHub Actions 的注入机制：

```
GitHub Secrets / 自动 GITHUB_TOKEN
        │  workflow YAML env: 块引用 ${{ secrets.* }}
        ▼
Actions 运行时注入进程环境变量
        │
        ▼
pipeline.py os.getenv("XXX") 直接拿到
```

- `env` 块定义在 **job 级别**，所有 step 共享，避免重复。
- `GITHUB_TOKEN` 用 `${{ secrets.GITHUB_TOKEN }}`（Actions 自动生成，无需手动建 secret）。
- 3 个 LLM key 需用户在 repo Settings → Secrets and variables → Actions 手动新建。

### D2：Step 顺序

```
1. actions/checkout@v4          # 拉代码（默认带 GITHUB_TOKEN）
2. actions/setup-python@v5      # python 3.11 + pip cache
3. pip install -r requirements.txt
4. python3 pipeline/pipeline.py --sources github,rss --limit 20 --verbose
   ├─ 内置 validate_json.py 结构校验（pipeline.py:914）
   └─ 写入 knowledge/{raw,enriched,articles}/ + index.json
5. python3 hooks/check_quality.py knowledge/articles/*.json   # 质量审计（continue-on-error）
6. git add → 检测变更 → commit + push（条件执行）
```

### D3：check_quality.py 调用

- 命令：`python3 hooks/check_quality.py knowledge/articles/*.json`
- 通配符可能匹配 0 文件（采集失败时）→ shell 默认传字面量导致报错。
- **方案**：step 前加存在性判断，或用 `continue-on-error: true` + `if` 条件。
- 此步是审计，**不阻塞**后续 commit。

### D4：Git commit + 条件提交（核心逻辑）

pipeline 不碰 git，全部在 workflow step 实现：

```yaml
- name: Commit & push
  run: |
    git config user.name "github-actions[bot]"
    git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
    git add knowledge/
    # 空提交保护：无 staged 变更则退出
    if git diff --cached --quiet; then
      echo "无新数据，跳过提交"
      exit 0
    fi
    COUNT=$(git diff --cached --name-only | wc -l | tr -d ' ')
    DATE=$(date -u +%Y-%m-%d)
    git commit -m "chore(knowledge): 采集 ${DATE} 数据（${COUNT} 个文件变更）"
    git push
```

- `git diff --cached --quiet` 检测 staged 区是否为空（AC10）。
- commit 消息含日期 + 文件变更数（AC9）。
- 用 `github-actions[bot]` 身份提交（标准做法）。
- `git add knowledge/` 纳入 raw/enriched/articles/index.json 全部产出。

### D5：cron 时区

- GitHub Actions cron 用 **UTC**。
- UTC 08:00 = 北京 16:00 ✅（`'0 8 * * *'`）。

### D6：Python 版本与缓存

- `actions/setup-python@v5`，`python-version: '3.11'`，`cache: 'pip'`。
- pip cache 依赖 `requirements.txt` 存在（已确认 ✅）。

## 不做的事（Out of Scope）

- 不修改 pipeline.py / model_client.py。
- 不创建 `.env.example`（课程未要求；secret 全走 Actions）。
- 不实现 HN 源（课程命令用 `github,rss`）。
- 不加失败通知（Telegram/飞书分发是后续阶段）。

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| GitHub Search API 限流 | R1 补 GITHUB_TOKEN，认证后 5000 次/小时 |
| LLM 密钥未配置导致分析失败 | pipeline 已有错误处理；首跑前需确认 secret 已配置 |
| 采集 0 条文章时 check_quality 通配符报错 | step 加 `if` 或 `continue-on-error` |
| 推送被拒（权限） | `permissions: contents: write` 已声明 |

## 兼容性结论

7/10 需求完全匹配，2 处修正（R1/R2），1 处实现（git commit 逻辑）。无硬性冲突。

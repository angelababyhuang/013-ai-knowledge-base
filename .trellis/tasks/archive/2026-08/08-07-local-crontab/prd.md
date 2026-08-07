# 本地 crontab 定时采集配置

## Goal

创建项目内的 crontab 文件，配置「日采 Step1-2 + 周分析 Step3-4」本地定时任务，并指导用户安装。

## Background

- pipeline 已支持 `--step 1,2`（采集+分析）和 `--step 3,4 --days 7`（整理+入库，扫描近 7 天）。
- crontab 环境特殊：PATH 极简、不加载 shell 配置、pipeline 不读 .env 文件。
- `.env` 在标准 KEY=VALUE 格式（LLM_PROVIDER/DEEPSEEK_API_KEY/GITHUB_TOKEN），可用 `set -a; . .env; set +a` 加载。

## Requirements

1. 创建项目内 crontab 文件（可版本控制、可复现安装）。
2. 任务 1：每天 08:00 跑 `--step 1,2 --sources github,rss --limit 20`，日志追加 logs/collect.log。
3. 任务 2：每周日 10:00 跑 `--step 3,4 --sources github,rss --days 7`，日志追加 logs/analyze.log。
4. 用 anaconda python 绝对路径（crontab PATH 找不到）。
5. 任务 1 加载 .env 环境变量（Step 2 需 LLM key）。
6. 含注释说明。

## Acceptance Criteria

- [x] AC1：crontab 文件存在且格式合法。✅ 项目根 crontab
- [x] AC2：含两条 job（日 08:00 / 周日 10:00）+ 注释。✅
- [x] AC3：python 用绝对路径。✅ /Applications/anaconda3/bin/python3
- [x] AC4：任务 1 含 .env 加载。✅ set -a; . .env; set +a
- [x] AC5：任务 2 含 --days 7。✅
- [x] AC6：用户成功安装（`crontab -l` 可见）。✅ cron 运行中 + crontab -l 确认

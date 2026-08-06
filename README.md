# AI 知识库助手

自动从 GitHub 热门仓库与 Hacker News 采集 AI/LLM/Agent 领域技术动态，经 LLM 分析（中文摘要 / 英文标签 / 五维相关性评分）后，结构化存储为 JSON 知识条目。

核心是一条**四步自动化流水线**：采集（Collect）→ 分析（Analyze）→ 整理（Organize）→ 保存（Save），由 `pipeline/pipeline.py` 一键驱动。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt   # 仅 httpx
```

### 2. 配置环境变量

流水线需要 LLM API Key（用于分析）；GitHub Token 可选（提高采集限额）。

在项目根目录创建 `.env`（已被 `.gitignore` 忽略）：

```bash
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的密钥
# 可选：GITHUB_TOKEN=你的token（不配则未认证限额 60 次/小时）
```

> **注意**：代码不自动读 `.env`，运行前需手动加载：
> ```bash
> set -a && source .env && set +a
> ```
> 或直接 `export LLM_PROVIDER=deepseek DEEPSEEK_API_KEY=...`。

支持的环境变量：

| 变量 | 必需 | 说明 |
| --- | --- | --- |
| `LLM_PROVIDER` | 否 | 模型提供方：`deepseek`（默认）/ `qwen` / `openai` |
| `DEEPSEEK_API_KEY` / `QWEN_API_KEY` / `OPENAI_API_KEY` | 是 | 对应 provider 的密钥；缺失时回退 `LLM_API_KEY` |
| `LLM_API_KEY` | 备选 | 统一密钥（各 provider 专属变量缺失时回退） |
| `GITHUB_TOKEN` | 否 | GitHub 采集认证；不配限额 60 次/小时，配后 5000 次/小时 |

### 3. 运行流水线

```bash
set -a && source .env && set +a        # 加载环境变量
python3 pipeline/pipeline.py --sources github,hn --limit 20
```

## pipeline.py 使用方法

### CLI 参数

| 参数 | 取值 | 默认 | 说明 |
| --- | --- | --- | --- |
| `--sources` | 逗号分隔 `github` / `hn` | `github,hn` | 数据源；`github`→GitHub 热门仓库，`hn`→Hacker News |
| `--limit` | int | GitHub 20 / HN 10 | 每源采集条数上限 |
| `--dry-run` | flag | 关 | 采集+分析照常，但**全程不落盘**，仅打印预览 |
| `--verbose` | flag | 关 | 输出 DEBUG 级详细日志 |
| `--no-validate` | flag | 关 | 跳过保存后的 schema 校验 |

### 常用示例

```bash
# 完整流水线（双源，各 20 条）
python3 pipeline/pipeline.py --sources github,hn --limit 20

# 只采集 GitHub（5 条）
python3 pipeline/pipeline.py --sources github --limit 5

# 只采集 Hacker News（10 条）
python3 pipeline/pipeline.py --sources hn --limit 10

# 干跑模式：真实采集+分析但不落盘（预览产出，不污染数据）
python3 pipeline/pipeline.py --sources github --limit 5 --dry-run

# 详细日志（排查用）
python3 pipeline/pipeline.py --sources hn --limit 10 --verbose
```

### 四步流程

```
Collect   按 --sources 采集 GitHub / HN      → knowledge/raw/{source}-{date}.json
Analyze   每条调 LLM 摘要/标签/五维评分       → knowledge/enriched/{source}-{date}.enriched.json
Organize  四规则门控 + url 去重               → 通过集 / 丢弃集
Save      12 字段格式化 + 索引                → knowledge/articles/{date}-{source}-{slug}.json
                                              + index.json + _filtered-{date}.json
```

- **质量门控**：`relevance_score < 0.6`、摘要 < 50 字、tags < 2、url 异常的条目被丢弃，记入 `knowledge/articles/_filtered-{date}.json`。
- **去重**：以 `url` 为键跨天去重，重复条目不重复落盘。
- **幂等**：同一天重复运行按 `id` / `url` 去重，不产生重复条目。
- **错误审计**：采集/分析/解析失败穷举记录到 `knowledge/raw/errors-{date}.json`，单条失败不中断整体。

## 数据目录

| 目录 | 内容 |
| --- | --- |
| `knowledge/raw/` | 原始采集数据（`{source}-{date}.json`）+ 错误记录（`errors-{date}.json`） |
| `knowledge/enriched/` | LLM 分析增强数据（`{source}-{date}.enriched.json`，含五维评分明细） |
| `knowledge/articles/` | 最终知识条目（12 字段 JSON）+ `index.json` 索引 + `_filtered-{date}.json` 过滤日志 |

知识条目遵循 12 字段契约（`schemas/article.schema.json`）：`id / title / source / url / category / collected_at / analyzed_at / organized_at / summary / tags / relevance_score / meta`。

## 质量校验

落盘的知识条目可用 hooks 做结构与质量校验：

```bash
# 结构校验（schema 驱动，12 字段契约）
python3 hooks/validate_json.py 'knowledge/articles/*.json'

# 5 维质量评分（rubric 驱动，A≥80 / B≥60 / C<60）
python3 hooks/check_quality.py 'knowledge/articles/*.json'
```

## 项目结构

```
├── pipeline/
│   ├── pipeline.py        # 四步流水线（主入口）
│   └── model_client.py    # 统一 LLM 客户端（DeepSeek/Qwen/OpenAI）
├── hooks/
│   ├── validate_json.py   # 结构校验器（schema 驱动）
│   └── check_quality.py   # 5 维质量评分器（rubric 驱动）
├── schemas/               # 契约（article.schema.json / quality-rubric.json）
├── knowledge/             # 数据资产（raw / enriched / articles）
└── docs/                  # 文档（baseline-prd.md 现状基线 / decisions/ ADR）
```

更多背景：项目现状见 `docs/baseline-prd.md`；架构与字段契约的演进决策见 `docs/decisions/`。

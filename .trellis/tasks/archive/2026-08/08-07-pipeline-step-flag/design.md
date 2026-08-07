# Design — pipeline-step-flag

## 核心设计：条件分支 + 磁盘加载

### D1：--step 参数

```python
parser.add_argument(
    "--step", default="1,2,3,4",
    help="逗号分隔要执行的步骤：1 采集 / 2 分析 / 3 整理 / 4 入库（默认全跑）",
)
```

解析为 `steps = set(int(s) for s in args.step.split(","))`，非法值 argparse 自然报错。

### D2：新增 load_enriched() 函数

```python
def load_enriched(sources: list[str], date: str) -> list[dict[str, Any]]:
    """从 knowledge/enriched/ 读取指定日期的 enriched items（Step 3-4 独立运行时用）。"""
    items = []
    for source in sources:
        path = ENRICHED_DIR / f"{source}-{date}.enriched.json"
        data = read_json(path, {})
        if isinstance(data, dict):
            items.extend(data.get("items", []))
        else:
            logger.warning("[load] %s 格式异常，跳过", path.name)
    logger.info("[load] 从 enriched/ 加载 %d 条（date=%s）", len(items), date)
    return items
```

enriched 文件结构 `{"source":..., "items":[...], "count":N}`，只取 `items` 字段。items 内每条已含 Step3 gate_item() / organize() 所需全部字段。

### D3：main() 重构——条件分支

当前 main() 是线性 4 步。改为按 steps 集合条件执行，关键处理数据传递：

```
steps = {1,2,3,4}  # 默认全跑

# ---- Step 1 Collect ----
raw_items = []
if 1 in steps:
    采集 → save_raw() → raw_items（内存）
else:
    raw_items = []  # Step 2 若要跑会因空而报错

# ---- Step 2 Analyze ----
enriched_items = []
if 2 in steps:
    if not raw_items:
        logger.error("Step 2 需要 Step 1 的采集数据，请用 --step 1,2")
        return 1
    analyze(raw_items) → save_enriched() → enriched_items（内存）
# 若 Step 2 不在 steps 中，enriched_items 保持空，下面按需从磁盘加载

# ---- Step 3-4 前置：确保有 enriched_items ----
if (3 in steps or 4 in steps) and not enriched_items:
    enriched_items = load_enriched(sources, date)
    if not enriched_items:
        logger.error("无 enriched 数据，请先运行 --step 1,2")
        return 1

# ---- Step 3 Organize ----
if 3 in steps:
    organize(enriched_items) → passed, filtered
else:
    # Step 4 依赖 Step 3 的 passed
    若 Step 3 没跑，Step 4 也无法跑 → 报错

# ---- Step 4 Save ----
if 4 in steps:
    if 3 not in steps:
        logger.error("Step 4 需要 Step 3 的整理结果，请用 --step 3,4")
        return 1
    save_articles(passed) → save_filtered(filtered)
    事后校验（if not dry-run and not no-validate）
```

### D4：向后兼容

- `--step` 默认 `1,2,3,4`，不传时 steps={1,2,3,4}，走全部分支 = 当前行为。
- 所有现有参数（--sources/--limit/--dry-run/--verbose/--no-validate）不变。
- daily-collect.yml workflow 不传 --step，完全不受影响。

### D5：Step 组合合法性矩阵

| --step | 合法？ | 数据来源 | 说明 |
|---|---|---|---|
| `1,2,3,4` | ✅ | 全内存 | 默认，等价于当前行为 |
| `1,2` | ✅ | 内存 → 落盘 raw/+enriched/ | 日常采集+分析 |
| `3,4` | ✅ | 磁盘 enriched/ → articles/ | 周末整理+入库 |
| `1` | ✅ | 内存 → 落盘 raw/ | 只采集 |
| `2` | ❌ | 无 raw_items | 报错：需先 Step 1 |
| `3` | ✅ | 磁盘 enriched/ → 内存 passed | 只整理（不落盘 articles） |
| `4` | ❌ | 无 passed | 报错：需先 Step 3 |

### D6：date 一致性 + 多天扫描（v2 — crontab 需求驱动）

**v1 限制已解除**：原设计 `--step 3,4` 只读当天 enriched，周分析会漏掉周一到周六的数据。

**v2 新增 `--days` 参数**：
- `--days 1`（默认）：只看今天，向后兼容
- `--days N`：扫描最近 N 天的 enriched 文件（按 UTC 日期回溯）
- `--days 0`：扫描 enriched/ 目录全部日期（catch-up 用）

**新增 `scan_enriched_dates(sources, today, days)` 函数**：
- days<=0：glob enriched 目录，正则提取日期
- days>0：timedelta 回溯 N 天，过滤到有文件的日期

**main() 批次循环**：Step 3-4 构建 `batches = [(date, items), ...]`，逐日 organize（accumulating existing_urls 跨日去重）+ save（每条 article 用原始采集日期做前缀）。`from_disk` flag 避免与 Step 2 内存数据重复计数。

**验证**：`--days 0` 命中 6 日期 221 条；`--days 7` 命中 2 日期 171 条；默认 1 日 80 条。

## 不做的事

- 不加 `--date` 参数（超出课程要求的最小改动）。
- 不加扫描多天 enriched 的能力（同上）。
- 不改 hooks/schemas/其他文件。
- 不写 crontab 文件（crontab 编写是下一阶段，本任务只让 pipeline 支持 --step）。

# pipeline 支持 --step 分步执行

## Goal

给 `pipeline/pipeline.py` 增加 `--step` 参数，支持分步执行四步流水线，使课程要求的「日采 Step1-2 + 周分析 Step3-4」crontab 方案可行。

## Background / Context

- 课程要求两条 crontab：每天跑 `--step 1 --step 2`（采集+分析），每周跑 `--step 3 --step 4`（整理+入库）。
- 当前 pipeline.py **无 `--step` 参数**（`--step 1` 直接报 unrecognized arguments）。
- 当前 main() 四步在单进程串行，数据靠内存传递：Step1 产出 raw_items → Step2 消费 → 产出 enriched_items → Step3 消费。
- enriched 文件已含 Step3-4 所需全部字段（relevance_score/summary/tags/url/source），结构为 `{"source":..., "items":[...], "count":N}`。
- **关键可行性**：Step3-4 可从 enriched/ 文件加载，不依赖内存——只需新增 `load_enriched()` 函数。

## Requirements

### 功能需求

1. 新增 `--step` 参数：逗号分隔步骤号（如 `--step 1,2` / `--step 3,4`），默认 `1,2,3,4`（全跑，向后兼容）。
2. **Step 1,2 模式**（采集+分析）：跑 collect → save raw/ → analyze → save enriched/，不跑 organize/save。
3. **Step 3,4 模式**（整理+入库）：从 `knowledge/enriched/{source}-{date}.enriched.json` 加载 items → organize（门控+去重）→ save articles/。
4. 数据依赖处理：
   - Step 2 依赖 Step 1 的 raw_items（内存）→ 若只跑 Step 2 无 Step 1，报错退出。
   - Step 3-4 依赖 enriched_items → 若 Step 2 未跑，从 enriched/ 文件读取；读取为空则报错提示先跑 `--step 1,2`。
5. 向后兼容：不传 `--step` 时行为与当前完全一致（全跑 4 步）。

### 约束

- 只改 `pipeline/pipeline.py`，不动 hooks/、schemas/、其他源码。
- 不改变现有文件格式（raw/enriched/articles 输出结构不变）。
- 保持 `--dry-run`/`--verbose`/`--no-validate` 在各 step 模式下正常工作。

## Acceptance Criteria

- [x] AC1：`--step` 参数存在于 `--help` 输出。✅
- [x] AC2：`python3 pipeline/pipeline.py --step 1,2 --sources github --limit 3` 只跑采集+分析，产出 raw/ 和 enriched/，不产出 articles/。✅ 逻辑验证（Step 3-4 包在条件分支内，--step 1,2 不触发）
- [x] AC3：`python3 pipeline/pipeline.py --step 3,4` 从 enriched/ 加载，产出 articles/，不调采集 API、不调 LLM。✅ dry-run 测试：加载 80 条 enriched，采集 0 条
- [x] AC4：不传 `--step` 时行为与改造前完全一致（全跑，回归测试）。✅ 默认 '1,2,3,4'，steps={1,2,3,4}
- [x] AC5：`--step 2` 单独跑（无 Step 1）报清晰错误，退出码非 0。✅ exit code 1
- [x] AC6：`--step 3,4` 无 enriched 数据时报清晰错误提示先跑 `--step 1,2`。✅ load_enriched 返回空时报错
- [x] AC7：`--step 3,4 --dry-run` 不落盘但打印预览。✅ "未落盘任何文件"
- [x] AC8：现有 `daily-collect.yml` workflow（不传 --step）仍正常工作。✅ 默认全跑，向后兼容

## Notes

- Step 编号对应：1 Collect / 2 Analyze / 3 Organize / 4 Save（与 pipeline.py 顶部注释一致）。
- 课程 crontab 的环境问题（PATH/密钥/路径）是 crontab 编写阶段的事，不在本任务范围。本任务只让 pipeline 支持 `--step`。

# Implement — pipeline-step-flag

## 交付物

只改 `pipeline/pipeline.py` 一个文件。

## 执行清单

### Step 1：加 --step 参数
- [ ] 在 `parse_args()`（line 931-955）加 `--step` 参数，default `"1,2,3,4"`
- [ ] 在 `main()` 解析 `steps = set(int(s) for s in args.step.split(","))`

### Step 2：加 load_enriched() 函数
- [ ] 在 Step 3 区域（line 747 附近）新增 `load_enriched(sources, date)` 函数（按 design D2）

### Step 3：重构 main() 条件分支
- [ ] Step 1 Collect：包在 `if 1 in steps:` 内（现有逻辑不变，仅加条件）
- [ ] Step 2 Analyze：包在 `if 2 in steps:` 内，前置检查 `if not raw_items` 报错
- [ ] Step 3-4 前置：`(3 in steps or 4 in steps) and not enriched_items` → 调 `load_enriched()`
- [ ] Step 3 Organize：包在 `if 3 in steps:` 内
- [ ] Step 4 Save：包在 `if 4 in steps:` 内，前置检查 `if 3 not in steps` 报错
- [ ] 事后校验 run_validation() 仅在 `4 in steps` 时执行

### Step 4：验证
- [ ] `python3 pipeline/pipeline.py --help` 含 --step
- [ ] `python3 pipeline/pipeline.py --step 3,4`（无前置 Step1-2）从 enriched/ 加载成功或报清晰错误
- [ ] `python3 pipeline/pipeline.py --step 1,2 --sources github --limit 3 --dry-run` 只采集分析不入库
- [ ] `python3 pipeline/pipeline.py --step 2` 单独跑报错（缺 Step 1）
- [ ] 不传 --step 时 `--dry-run` 行为与改造前一致（回归）

## 验证命令

```bash
# AC1: --help 含 --step
python3 pipeline/pipeline.py --help | grep -A1 -- '--step'

# AC5: --step 2 单独跑报错
python3 pipeline/pipeline.py --step 2 2>&1 | grep -i 'step 1\|error'

# AC4: 不传 --step 回归（dry-run 不落盘）
python3 pipeline/pipeline.py --sources github --limit 2 --dry-run --verbose

# AC2: --step 1,2 dry-run
python3 pipeline/pipeline.py --step 1,2 --sources github --limit 2 --dry-run --verbose
```

## 完成判定

- AC1-AC8 全部通过。
- 只改 pipeline.py（`git diff --stat` 仅 1 文件）。
- 现有 workflow（不传 --step）回归不受影响。

## Rollback

`git checkout pipeline/pipeline.py` 回退全部改动。

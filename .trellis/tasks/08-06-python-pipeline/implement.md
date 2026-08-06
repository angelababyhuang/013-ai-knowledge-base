# 执行计划：pipeline/pipeline.py

## 交付物

- `pipeline/pipeline.py`（唯一新增源码文件；产出写入现有 `knowledge/` 目录）。

## 前置确认

- 数据源 = GitHub + HN（无 RSS）。
- 产出满足 12 字段契约；保留 enriched/ 中间层。
- 复用 `model_client.create_provider` / `chat_with_retry`。
- 依赖：httpx（已装）。GitHub 需 `GITHUB_TOKEN`；分析需 LLM key（`LLM_PROVIDER` + 对应 `*_API_KEY` 或 `LLM_API_KEY`）。

## 执行清单（按序）

- [ ] 1. 骨架：argparse CLI（--sources/--limit/--dry-run/--verbose/--no-validate）、logging、pathlib 路径常量、knowledge 目录定位。
- [ ] 2. Step1 Collect：GitHub 采集（查询构造/认证头/限流重试/字段映射）+ HN 采集（topstories→详情→关键词过滤→分层筛选→URL回填→字段映射）；幂等写 raw/。
- [ ] 3. Step2 Analyze：构造 prompt（要求严格 JSON）→ chat_with_retry → 提取/解析 JSON → 五维加权算 relevance_score → category 上限截断 + score_breakdown → 幂等写 enriched/。
- [ ] 4. Step3 Organize：四规则门控 + url 去重（比对 articles/ 存量）。
- [ ] 5. Step4 Save：12 字段格式化 + category 补全 + meta 透传 + slug → 写 article → 更新 index.json → 记 _filtered → 记 errors。
- [ ] 6. dry-run 分支：全程不落盘，结尾打印预览。
- [ ] 7. 校验分支：subprocess 调 hooks/validate_json.py。
- [ ] 8. 自测：--dry-run 跑通；再小 limit 真实跑 github 单源、hn 单源；最后双源。
- [ ] 9. 验收：产出 article 过 validate_json.py；门控/去重/幂等/index 符合 Acceptance Criteria。

## 验证命令

```bash
python pipeline/pipeline.py --sources github --limit 5 --dry-run --verbose
python pipeline/pipeline.py --sources hn --limit 10 --dry-run
python pipeline/pipeline.py --sources github,hn --limit 5
python hooks/validate_json.py 'knowledge/articles/*.json'
python hooks/check_quality.py 'knowledge/articles/*.json'
```

## 风险与回滚

- 风险：LLM 返回非严格 JSON → 解析失败。缓解：提取 ```json 块 + 异常记 errors 跳过该条。
- 风险：HN category 由 LLM 判定可能不稳定。缓解：解析后校验枚举，非法值回退 article-or-news 并记 _override。
- 风险：GitHub 未配 token 限流。缓解：检测 403/429 读 X-RateLimit-Reset 重试≤3，仍失败记 errors。
- 回滚：仅新增 pipeline.py，删除即可；knowledge/ 产物可按日期清理。

## 完成前检查

- [ ] PEP 8（无未用导入、命名规范、行宽合理）。
- [ ] 未改动 model_client.py / .opencode/ / schemas/ / hooks/。
- [ ] git status 仅新增 pipeline/pipeline.py 与 knowledge/ 产物、任务文件。

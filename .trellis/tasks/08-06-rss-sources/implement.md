# 执行计划：RSS 数据源

## 交付物

- 新增：`pipeline/rss_sources.yaml`
- 修改：`pipeline/pipeline.py`（RSS 采集路径）、`schemas/article.schema.json`（source 枚举 +`rss`、meta 说明）、`requirements.txt`（+pyyaml）

## 前置确认

- 7 个源（已去 hackernews-best）；URL/enabled 来自 `research/rss-feeds.md` 实测。
- RSS 走完整四步进 articles；source 统一 `rss`、feed_name 入 meta、category 由 LLM 判定。
- 新增依赖 pyyaml；RSS 解析用 stdlib ElementTree。

## 执行清单（按序）

- [ ] 1. `requirements.txt` 加 `pyyaml`；`pip install pyyaml`。
- [ ] 2. 创建 `pipeline/rss_sources.yaml`（7 源，字段 name/url/category/enabled/note）。
- [ ] 3. `schemas/article.schema.json`：source 枚举加 `rss`；meta description 补 RSS 字段集。
- [ ] 4. pipeline.py 加 `load_rss_sources()`：读 yaml、过滤 enabled 且 url 非空。
- [ ] 5. pipeline.py 加 `parse_feed()`：ElementTree 解析 RSS 2.0 item 与 Atom entry（`{*}` 命名空间），按发布时间降序取前 limit 条。
- [ ] 6. pipeline.py 加 `collect_rss()`：逐源 httpx 抓取 → 解析 → 字段提取（id=guid|link / title / source=rss / url=link / feed_name / author / published / summary_raw）→ 失败记 errors；幂等写 `raw/rss-{date}.json`。
- [ ] 7. 适配 analyze：RSS 条目 prompt 输入用 title+summary_raw；category 由 LLM 判定。
- [ ] 8. 适配 save：`build_article`/`build_meta` 支持 source=rss → meta={feed_name,author,published}。
- [ ] 9. CLI：`--sources` 接受 `rss`，映射采集路径。
- [ ] 10. 自验：`py_compile`、`--help`、dry-run RSS 单源、真实小 limit RSS 跑通、产出过 validate_json。

## 验证命令

```bash
pip install -r requirements.txt
python -m py_compile pipeline/pipeline.py
python pipeline/pipeline.py --help
set -a && source .env && set +a
python pipeline/pipeline.py --sources rss --limit 3 --dry-run --verbose
python pipeline/pipeline.py --sources rss --limit 3
python hooks/validate_json.py 'knowledge/articles/*.json'
python -c "import yaml; yaml.safe_load(open('pipeline/rss_sources.yaml'))"  # yaml 语法校验
```

## 风险与回滚

- 风险：RSS XML 格式差异（RSS2.0/Atom/命名空间）→ ElementTree `{*}` 通配 + 解析失败记 errors 跳过。
- 风险：机器之心无 url → 采集跳过空 url 源。
- 风险：RSSHub 源（anthropic）不稳定 → 默认 enabled:false。
- 回滚：新增 yaml 删除即可；pipeline.py/schema/requirements 的改动 git 可回退。

## 完成前检查

- [ ] yaml 语法合法，7 源字段齐全。
- [ ] schema source 枚举含 rss；article 含 rss 的 meta 字段集。
- [ ] 产出 rss article 过 validate_json（exit 0）。
- [ ] 未改 model_client.py / .opencode/；GitHub/HN 路径不受影响。
- [ ] git status 仅含预期改动文件。

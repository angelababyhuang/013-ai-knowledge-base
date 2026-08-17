# Directory Structure

> How backend code is organized in this project.

---

## Overview

项目是「无框架的 Python 脚本 + 包」混合形态：`pipeline/`、`patterns/`、`workflows/` 三个包 + 顶层脚本（`mcp_knowledge_server.py`）+ `hooks/` 校验器。LLM/外部 API 调用统一经 `pipeline/model_client.py` 的 provider 基建（DeepSeek/Qwen/OpenAI 多 provider + 指数退避重试 + token 计价）。

---

## Directory Layout

```
├── mcp_knowledge_server.py    # MCP 知识库服务（顶层脚本）
├── hooks/                     # schema/rubric 驱动的校验器（validate_json / check_quality）
├── pipeline/                  # 四步流水线（脚本式，见下方陷阱）
│   ├── model_client.py        # 统一 LLM 客户端（可包导入 ✓）
│   └── pipeline.py            # Collect→Analyze→Organize→Save
├── patterns/                  # Agent 模式示例（router / supervisor）
└── workflows/                 # LangGraph 工作流（课程主线，包导入 ✓）
    ├── state.py               # KBState（TypedDict 共享状态）
    ├── model_client.py        # 课程签名适配层 → 复用 pipeline.model_client
    ├── nodes.py               # 5 个纯函数节点
    └── graph.py               # StateGraph 组装 + build_graph()
```

---

## Module Organization

### 陷阱：pipeline/pipeline.py 不可包导入

`pipeline/pipeline.py` 顶层是脚本式导入（`from model_client import ...`），
**只能以 `python pipeline/pipeline.py` 方式运行**，`from pipeline.pipeline import X` 会 ModuleNotFoundError。

- 需要复用其函数（slugify/build_article 等）时：**复制并在 docstring 注明出处**，不要 import（先例：`workflows/nodes.py`）。
- `pipeline/model_client.py` 是正常包模块，可以安全 import。

### workflows/ 包约定

1. **sys.path 注入**：包内模块互相导入（`from workflows.state import ...`）前，先注入项目根：
   ```python
   _PROJECT_ROOT = Path(__file__).resolve().parent.parent
   if str(_PROJECT_ROOT) not in sys.path:
       sys.path.insert(0, str(_PROJECT_ROOT))
   ```
   原因：模块会被 `python workflows/xxx.py` 直跑（sys.path[0] 是 workflows/ 而非项目根）。
2. **LLM 调用**：走 `workflows/model_client.py` 的 `chat()/chat_json()/accumulate_usage()`（带 usage 返回），底层复用 pipeline 基建；不要再新写 `_llm_json` 拷贝。
3. **DRY_RUN 惯例**：`WORKFLOWS_DRY_RUN=1` 环境变量让 save_node 只打日志不落盘，自测/冒烟必须带，防止污染 `knowledge/articles/` 与 `index.json`。
4. **直跑自测**：每个模块带 `if __name__ == "__main__"` 冒烟块；需要 LLM key 时按 `set -a && . ./.env && set +a` 加载（与 crontab 一致）。
5. **幂等契约**：organize/save 按规范化 URL + id 对存量 index.json 查重，重复运行不产生重复条目（AGENTS.md 规则 3）。

---

## Naming Conventions

- 包/模块名英文小写下划线；知识数据文件名见 AGENTS.md「编码规范」
- LangGraph 节点函数 `xxx_node`，注册名用短名（collect/analyze/organize/review/save）

---

## Examples

- `workflows/graph.py` — StateGraph 组装、条件边路由（`_route_after_review` + path_map）、updates 流式打印的标准写法
- `workflows/nodes.py` — 纯函数节点（返回部分状态更新、不抛错中断图）+ 与 pipeline 契约对齐的注释方式
- `workflows/reviewer.py` — 加权评分代码重算（`compute_weighted_score`，不信任模型算术）+ fail-open 异常路径的标准写法

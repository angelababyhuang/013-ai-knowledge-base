import type { Plugin } from "@opencode-ai/plugin"

/**
 * validate.ts — 知识条目落盘后自动 schema 校验。
 *
 * 监听 tool.execute.after：当 Agent 用 write/edit 写入 knowledge/articles/ 下的
 * 知识条目（{date}-{source}-{slug}.json）时，自动跑 hooks/validate_json.py 复核。
 *
 * 实现要点（踩坑总结）：
 *  - 用 .nothrow() 而非 .quiet()：.quiet() 会让 OpenCode 卡死；.nothrow() 仅阻止
 *    非零退出码抛异常，stdout 仍正常缓冲，可安全读取。
 *  - 所有 shell 调用包 try/catch：插件里未捕获的异常会阻塞 Agent 主循环。
 */

const VALIDATOR = "hooks/validate_json.py"

/** 判断是否为待校验的知识条目文件（排除 index.json / _filtered-*.json 等元文件）。 */
function isArticleFile(filePath: string): boolean {
  const normalized = filePath.replace(/\\/g, "/")
  if (!normalized.includes("knowledge/articles/")) return false
  if (!normalized.endsWith(".json")) return false
  const basename = normalized.split("/").pop() || ""
  if (basename === "index.json" || basename.startsWith("_")) return false
  return true
}

export const ValidatePlugin: Plugin = async ({ $ }) => {
  return {
    "tool.execute.after": async (input, output) => {
      // 仅 write / edit 工具触发
      if (input.tool !== "write" && input.tool !== "edit") return

      // 兼容 file_path（snake_case）与 filePath（camelCase）两种命名
      const args = (input.args ?? {}) as Record<string, unknown>
      const filePath =
        (args.file_path as string) ?? (args.filePath as string) ?? ""
      if (!filePath || !isArticleFile(filePath)) return

      try {
        // .nothrow()：validator 失败（exit 1）时不抛异常，靠 exitCode 判定
        const result = await $`python3 ${VALIDATOR} ${filePath}`.nothrow()

        if (result.exitCode === 0) {
          output.output = `✓ schema 校验通过：${filePath}`
        } else {
          // result.text() 读取已缓冲的 stdout（BunShellOutput 级，不触发 quiet）
          output.output = `⚠ schema 校验失败（exit ${result.exitCode}）：${filePath}\n${result.text()}`
        }
      } catch (err) {
        // 兜底：python3 缺失 / 脚本路径错误等异常，绝不向上抛
        output.output = `⚠ 校验脚本执行异常：${err instanceof Error ? err.message : String(err)}`
      }
    },
  }
}

import { relative } from "path"

const ValidatePlugin = async ({ $, directory }) => {
  return {
    "tool.execute.after": async (input, output) => {
      if (input.tool !== "write" && input.tool !== "edit") {
        return
      }

      const filePath = input.args.file_path ?? input.args.filePath ?? ""
      const normalizedPath = filePath.replace(/\\/g, "/")
      if (!filePath || (!normalizedPath.includes("knowledge/articles/") && !normalizedPath.endsWith("knowledge/articles/")) || !normalizedPath.endsWith(".json")) {
        return
      }

      console.log("[validate-json] Detected write to:", filePath)

      const hookPath = `${directory}/hooks/validate_json.py`
      const relPath = relative(directory, filePath)

      try {
        console.log("[validate-json] Running:", `python3 ${hookPath} ${relPath}`)
        const result = await $({ nothrow: true })`python3 ${hookPath} ${relPath}`

        console.log("[validate-json] Exit code:", result.exitCode)
        if (result.exitCode !== 0) {
          console.log(`[validate-json] Validation failed for ${relPath}`)
          console.log(result.stderr || result.stdout)
        } else {
          console.log(`[validate-json] Validation passed for ${relPath}`)
        }
      } catch (err) {
        console.error(`[validate-json] Shell execution error:`, err)
      }
    },
  }
}

export default ValidatePlugin
// Agent Forge hook (PostToolUse, Edit|Write|MultiEdit): format the edited file with the
// project's own Prettier. No-op when the file type is not handled or when
// node_modules/.bin/prettier does not exist (never downloads anything).
import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { join } from "node:path";

const EXT = [".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".json", ".css", ".scss", ".md", ".yaml", ".yml", ".html", ".vue"];

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => (raw += chunk));
process.stdin.on("end", () => {
  let payload;
  try {
    payload = JSON.parse(raw || "{}");
  } catch {
    process.exit(0);
  }
  const file = String((payload && payload.tool_input && payload.tool_input.file_path) || "");
  if (!file || !EXT.some((e) => file.toLowerCase().endsWith(e))) process.exit(0);
  const root = process.env.CLAUDE_PROJECT_DIR || process.cwd();
  const bin = join(root, "node_modules", ".bin", process.platform === "win32" ? "prettier.cmd" : "prettier");
  if (!existsSync(bin)) process.exit(0);
  spawnSync(bin, ["--log-level", "silent", "--write", file], { cwd: root, stdio: "ignore", timeout: 30000, shell: process.platform === "win32" });
  process.exit(0);
});

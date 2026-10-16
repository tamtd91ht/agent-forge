// Agent Forge hook (PreToolUse, Edit|Write|MultiEdit): refuse edits to secret-looking files.
// Reads the hook payload from stdin; exit code 2 blocks the tool call and returns stderr to the
// agent. Never reads the target file. No dependencies.
const SECRET_NAMES = new Set([".env", ".envrc", ".npmrc", ".pypirc", ".netrc", "id_rsa", "id_ed25519", "id_ecdsa"]);
const SECRET_SUFFIXES = [".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".secret"];
const SECRET_PREFIXES = [".env.", "credentials", "secrets"];
const ALLOWED = new Set([".env.example", ".env.sample", ".env.template", ".env.dist"]);

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => (raw += chunk));
process.stdin.on("end", () => {
  let payload;
  try {
    payload = JSON.parse(raw || "{}");
  } catch {
    process.exit(0); // malformed payload: never block on our own bug
  }
  const path = String((payload && payload.tool_input && payload.tool_input.file_path) || "");
  const name = path.replace(/\\/g, "/").split("/").pop().toLowerCase();
  if (!name || ALLOWED.has(name)) process.exit(0);
  const bad =
    SECRET_NAMES.has(name) ||
    SECRET_PREFIXES.some((p) => name.startsWith(p)) ||
    SECRET_SUFFIXES.some((s) => name.endsWith(s));
  if (bad) {
    process.stderr.write(
      `agent-forge guard: refusing to edit secret-looking file ${path}. Ask the user to change credentials by hand.\n`,
    );
    process.exit(2);
  }
  process.exit(0);
});

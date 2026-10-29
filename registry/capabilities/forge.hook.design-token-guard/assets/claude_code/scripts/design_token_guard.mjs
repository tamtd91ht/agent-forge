// Agent Forge hook (PostToolUse, Edit|Write|MultiEdit): warn when the text just written into a
// UI source file bypasses the design tokens: a raw colour literal (#hex, rgb(), hsl()), a Tailwind
// arbitrary radius / spacing / font size (rounded-[13px], p-[7px], text-[15px]) or a hard-coded
// font-family. The edit is already on disk; exit 2 sends the warning to the agent so it uses
// the token or the scale step instead. Theme / token files, tests and stories are skipped; a line containing
// "design-token-ok" is accepted as a deliberate exception. Reads only the hook payload, never
// the file. Fails open (exit 0) on anything unexpected.

const UI_EXT = /\.(jsx?|tsx?|mjs|cjs|vue|svelte|astro|css|scss|sass|less)$/i;
const SKIP_PATH =
  /(^|[\/\\])(node_modules|dist|build|\.next|coverage|__tests__|__mocks__|tests?|fixtures?|stories|storybook)([\/\\]|$)|\.(test|spec|stories)\.[a-z]+$|\.d\.ts$|\.config\.[cm]?[jt]s$/i;
const TOKEN_FILE =
  /(^|[\/\\])((design-)?tokens?|themes?)[\/\\]|(^|[\/\\])[^\/\\]*(tokens?|theme|themes|palette|colou?rs?|variables|globals?)[^\/\\]*$/i;
const HEX = /(?<![\w&#\/])#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{3,4})(?![\w-])/gi;
const FUNC = /\b(?:rgba?|hsla?)\(\s*[\d.]/gi;
const ARBITRARY =
  /(?<![\w-])(rounded(?:-[trblse]{1,2})?|p[xytrblse]?|m[xytrblse]?|gap(?:-[xy])?|space-[xy]|text)-\[(\d+(?:\.\d+)?)px\]/g;
const FONT_FAMILY = /font-family\s*:\s*(?!\s*(var\(|inherit|initial|unset|revert))/i;
const CUSTOM_PROPERTY = /^\s*--[\w-]+\s*:/;
const COMMENT = /^\s*(\/\/|\/\*|\*|<!--)/;
const MAX_REPORTED = 8;

// Known OMICX values -> the token that should be used instead (omicx-ui skill, tokens.css).
const KNOWN = {
  "#1e3150": "primary / foreground",
  "#00b1ff": "accent / focus",
  "#56cc6e": "success",
  "#ff5955": "danger",
  "#fea220": "warning",
  "#6c63ff": "indigo",
  "#fbbf24": "yellow",
  "#f8f8f9": "background",
  "#f5f6fa": "surface-quaternary",
  "#8e9aad": "muted (text-secondary)",
  "#e7eaf0": "border (tertiary)",
  "#0c1c35": "background (dark)",
  "#16243c": "surface (dark)",
  "#182b44": "surface-secondary (dark)",
  "#152942": "surface-quaternary (dark)",
  "#253a55": "border (dark)",
};

// Scales of the omicx-ui skill (tokens.css): px -> utility.
const RADIUS = { 6: "rounded-tiny", 8: "rounded-small", 10: "rounded-medium", 12: "rounded-large", 16: "rounded-extra", 20: "rounded-card", 24: "rounded-dialog" };
const TEXT = { 12: "text-xs", 14: "text-sm", 16: "text-base", 18: "text-lg", 20: "text-xl", 22: "text-title" };

function arbitraryHint(prop, px) {
  const n = Number(px);
  if (prop.startsWith("rounded")) {
    return RADIUS[n] ? `use ${RADIUS[n]}` : "use the radius scale (tiny 6, small 8, medium 10, large 12, extra 16, card 20, dialog 24)";
  }
  if (prop === "text") {
    return TEXT[n] ? `use ${TEXT[n]}` : "use the type scale (xs 12, sm 14, base 16, title 22)";
  }
  return n % 4 === 0 ? `use ${prop}-${n / 4} (4 px grid)` : "off the 4 px spacing grid; use the nearest step";
}

function writtenText(input) {
  const parts = [];
  if (typeof input.content === "string") parts.push(input.content);
  if (typeof input.new_string === "string") parts.push(input.new_string);
  if (Array.isArray(input.edits)) {
    for (const e of input.edits) if (e && typeof e.new_string === "string") parts.push(e.new_string);
  }
  return parts.join("\n");
}

function findings(text) {
  const out = [];
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length && out.length < MAX_REPORTED; i++) {
    const line = lines[i];
    if (line.includes("design-token-ok") || CUSTOM_PROPERTY.test(line) || COMMENT.test(line)) continue;
    const hits = [];
    for (const h of line.match(HEX) || []) {
      const hint = KNOWN[h.toLowerCase()];
      hits.push(`${h}${hint ? `  -> use token: ${hint}` : ""}`);
    }
    for (const f of line.match(FUNC) || []) hits.push(f.replace(/[\d.\s]+$/, "") + "...)");
    for (const m of line.matchAll(ARBITRARY)) hits.push(`${m[0]}  -> ${arbitraryHint(m[1], m[2])}`);
    if (FONT_FAMILY.test(line)) hits.push("font-family  -> use the font token (font-sans / var(--font-sans))");
    for (const h of hits) {
      out.push(`  line ${i + 1}: ${h}`);
      if (out.length >= MAX_REPORTED) break;
    }
  }
  return out;
}

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => (raw += chunk));
process.stdin.on("end", () => {
  try {
    const payload = JSON.parse(raw || "{}");
    const input = (payload && payload.tool_input) || {};
    const file = String(input.file_path || "");
    if (!file || !UI_EXT.test(file) || SKIP_PATH.test(file) || TOKEN_FILE.test(file)) process.exit(0);
    const found = findings(writtenText(input));
    if (found.length === 0) process.exit(0);
    process.stderr.write(
      [
        `agent-forge design-token-guard (PostToolUse warning; the edit is already written): value(s) bypassing the design tokens in ${file}:`,
        ...found,
        "Replace each with a design token or scale step (CSS variable, Tailwind theme utility or theme constant; see the omicx-ui skill, references/tokens.css),",
        "or move the value into the project's token / theme file. If the value is deliberate (brand asset, third-party colour, pixel-exact embed), add a 'design-token-ok' comment on that line.",
      ].join("\n") + "\n",
    );
    process.exit(2);
  } catch {
    process.exit(0);
  }
});

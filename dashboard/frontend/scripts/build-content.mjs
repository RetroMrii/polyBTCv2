import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import MarkdownIt from "markdown-it";

const frontend = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const root = path.resolve(frontend, "../..");
const research = path.join(root, "research");
const destination = path.join(frontend, "public/research");
const catalog = JSON.parse(
  fs.readFileSync(path.join(research, "catalog.json"), "utf8"),
);
const slugify = (value) =>
  value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
const papers = [];
for (const paper of catalog) {
  const source = path.join(research, paper.file);
  const md = new MarkdownIt({ html: false, linkify: false, typographer: true });
  const headings = [];
  const seen = new Set();
  md.core.ruler.push("publication-links", (state) => {
    for (let i = 0; i < state.tokens.length; i++) {
      const token = state.tokens[i];
      if (token.type === "heading_open") {
        const title = state.tokens[i + 1].content;
        const id = slugify(title);
        if (seen.has(id))
          throw new Error(`Duplicate heading in ${paper.slug}: ${id}`);
        seen.add(id);
        token.attrSet("id", id);
        if (token.tag === "h2") headings.push({ id, title });
      }
      for (const child of token.children || []) {
        const attr =
          child.type === "image"
            ? "src"
            : child.type === "link_open"
              ? "href"
              : null;
        if (!attr) continue;
        const link = child.attrGet(attr);
        if (/^https?:\/\//.test(link)) {
          child.attrSet("rel", "noreferrer");
          continue;
        }
        if (link.startsWith("#")) continue;
        const resolved = path.resolve(path.dirname(source), link);
        if (
          !resolved.startsWith(research + path.sep) ||
          !fs.existsSync(resolved)
        )
          throw new Error(`Broken/unsafe link: ${paper.slug}: ${link}`);
        const relative = path
          .relative(research, resolved)
          .replaceAll("\\", "/");
        child.attrSet(
          attr,
          relative.startsWith("papers/")
            ? `#/papers/${path.basename(relative, ".md")}`
            : `research/${relative}`,
        );
        if (child.type === "image") child.attrSet("loading", "lazy");
      }
    }
  });
  const markdown = fs.readFileSync(source, "utf8");
  const html = md.render(markdown);
  papers.push({
    ...paper,
    headings,
    html,
    words: markdown.split(/\s+/).length,
  });
}
fs.mkdirSync(path.join(frontend, "src/generated"), { recursive: true });
fs.writeFileSync(
  path.join(frontend, "src/generated/papers.json"),
  JSON.stringify(papers),
);
fs.copyFileSync(
  path.join(research, "sources/demo.json"),
  path.join(frontend, "src/generated/demo.json"),
);
fs.copyFileSync(
  path.join(research, "sources/forecast-evidence.json"),
  path.join(frontend, "src/generated/forecast.json"),
);
for (const folder of ["papers", "figures", "sources"]) {
  fs.mkdirSync(path.join(destination, folder), { recursive: true });
  for (const file of fs.readdirSync(path.join(research, folder))) {
    if (!/\.(md|json|svg|png)$/.test(file)) continue;
    fs.copyFileSync(
      path.join(research, folder, file),
      path.join(destination, folder, file),
    );
  }
}
for (const file of ["catalog.json", "claims.json", "reproduction.json"])
  fs.copyFileSync(path.join(research, file), path.join(destination, file));
// Only explicit publication files enter the static site. Operational data is never traversed.
for (const file of fs.readdirSync(path.join(destination, "sources"))) {
  const text = fs.readFileSync(path.join(destination, "sources", file), "utf8");
  if (
    /[A-Za-z]:\\\\|C:\\Users|H:\\PolyBTC|api[_-]?secret|private_key/i.test(text)
  )
    throw new Error(`Private-path/credential marker in ${file}`);
}
console.log(
  `Rendered ${papers.length} canonical papers; all relative links resolved. Static export contains only the publication allowlist.`,
);

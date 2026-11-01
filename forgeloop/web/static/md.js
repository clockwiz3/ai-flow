// A small Markdown renderer that builds DOM nodes (never innerHTML): headings, lists, tables, code, emphasis.
import { diffView, h } from "./dom.js";

function inline(text) {
  const out = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g;
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("`")) out.push(h("code", {}, tok.slice(1, -1)));
    else if (tok.startsWith("**")) out.push(h("strong", {}, tok.slice(2, -2)));
    else {
      const [, label, href] = tok.match(/\[([^\]]+)\]\(([^)]+)\)/);
      const safe = /^https?:\/\//.test(href) ? href : null;  // no javascript: or relative links from tickets
      out.push(safe ? h("a", { href: safe, target: "_blank", rel: "noopener noreferrer" }, label) : label);
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const isRow = (l) => /^\s*\|.*\|\s*$/.test(l);
const cells = (l) => l.trim().slice(1, -1).split("|").map((c) => c.trim());

export function markdown(src) {
  const root = h("div", { class: "md" });
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^\s*<\/?(details|summary)/.test(line)) { i++; continue; }  // collapsible wrappers: show the content
    const fence = line.match(/^```(\w*)/);
    if (fence) {
      const body = [];
      for (i++; i < lines.length && !lines[i].startsWith("```"); i++) body.push(lines[i]);
      i++;
      root.append(fence[1] === "diff" ? diffView(body.join("\n")) : h("pre", {}, h("code", {}, body.join("\n"))));
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)/);
    if (heading) { root.append(h(`h${heading[1].length}`, {}, inline(heading[2]))); i++; continue; }
    if (isRow(line) && i + 1 < lines.length && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
      const table = h("table", {}, h("thead", {}, h("tr", {}, cells(line).map((c) => h("th", {}, inline(c))))));
      const body = h("tbody");
      for (i += 2; i < lines.length && isRow(lines[i]); i++) body.append(h("tr", {}, cells(lines[i]).map((c) => h("td", {}, inline(c)))));
      table.append(body);
      root.append(table);
      continue;
    }
    const item = line.match(/^(\s*)([-*]|\d+\.)\s+(.*)/);
    if (item) {
      const ordered = /\d/.test(item[2]);
      const list = h(ordered ? "ol" : "ul");
      while (i < lines.length) {
        const m = lines[i].match(/^(\s*)([-*]|\d+\.)\s+(.*)/);
        if (m) { list.append(h("li", {}, inline(m[3].replace(/^\[( |x)\]\s*/, (_, x) => (x === "x" ? "☑ " : "☐ "))))); i++; }
        else if (/^\s{2,}\S/.test(lines[i]) && list.lastChild) { list.lastChild.append(" ", ...inline(lines[i].trim())); i++; }
        else break;
      }
      root.append(list);
      continue;
    }
    if (!line.trim()) { i++; continue; }
    const para = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|\s*[-*]\s|\s*\d+\.\s|\s*\|)/.test(lines[i])) para.push(lines[i++]);
    if (!para.length) para.push(lines[i++]);
    root.append(h("p", {}, inline(para.join(" "))));
  }
  return root;
}

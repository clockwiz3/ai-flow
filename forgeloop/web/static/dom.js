// Tiny DOM helpers. Everything dynamic goes through text nodes: ticket and issue text is untrusted input.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (key === "class") el.className = value;
    else if (key === "style" && typeof value === "object") Object.assign(el.style, value);
    else if (key === "value") el.value = value;
    else if (key === "checked") el.checked = Boolean(value);
    else el.setAttribute(key, value === true ? "" : String(value));
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function mount(el, ...children) {
  el.replaceChildren();
  return append(el, children);
}

export const usd = (v, digits = 4) => (v === null || v === undefined ? "–" : `$${Number(v).toFixed(digits)}`);
export const pct = (v) => (v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`);

export function ago(iso) {
  if (!iso) return "";
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

export function badge(text, kind = "") {
  return h("span", { class: `badge ${kind}` }, text);
}

const STAGE_KIND = { delivered: "ok", escalated: "warn" };
const PHASE_KIND = { running: "info", awaiting_approval: "warn", paused: "", finished: "" };

export function stageBadge(stage, phase) {
  if (phase === "awaiting_approval") return badge("awaiting approval", "warn");
  if (phase === "running") return badge(`running · ${stage.replace("_", " ")}`, "info");
  if (phase === "paused") return badge(`paused · ${stage.replace("_", " ")}`);
  return badge(stage, STAGE_KIND[stage] || PHASE_KIND[phase] || "");
}

export function diffView(text) {
  const pre = h("pre", { class: "code diff" });
  for (const line of text.split("\n")) {
    let cls = "";
    if (line.startsWith("diff --git") || line.startsWith("+++") || line.startsWith("---")) cls = "file";
    else if (line.startsWith("@@")) cls = "hunk";
    else if (line.startsWith("+")) cls = "add";
    else if (line.startsWith("-")) cls = "del";
    pre.append(h("span", { class: cls }, line), "\n");
  }
  return pre;
}

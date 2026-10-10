/**
 * 极简 Markdown → HTML 渲染器（零依赖）。
 *
 * 为什么不用 marked / markdown-it：
 *   1. 报告内容和搜索结果都来自**模型自由生成**，直接 innerHTML 等于把 XSS 入口敞开；
 *      所以这里先转义、再按白名单加标签，可控性比引入一个完整的解析器更强。
 *   2. 报告是**流式**到达的 —— 中途会出现没闭合的 ``` 或 **。
 *      完整解析器遇到半截语法容易吃掉后面的内容，这个实现刻意容忍残句。
 *
 * 支持范围：标题 / 粗斜体 / 行内代码 / 围栏代码块 / 引用 / 有序无序列表 /
 *          分隔线 / 表格 / 链接。不支持的语法原样显示，不会丢内容。
 */

const ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;"
};

export function escapeHtml(raw: string): string {
  return raw.replace(/[&<>"']/g, (ch) => ESCAPES[ch] ?? ch);
}

/** 行内语法。输入是**未转义**的原始文本，函数内部负责转义。 */
function inline(raw: string): string {
  let text = escapeHtml(raw);

  // 行内代码先摘出来，免得里面的 * 和 _ 被后面几条规则误伤
  const codes: string[] = [];
  text = text.replace(/`([^`\n]+)`/g, (_all, code: string) => {
    codes.push(code);
    return `\u0000${codes.length - 1}\u0000`;
  });

  text = text
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>")
    .replace(/~~([^~\n]+)~~/g, "<del>$1</del>")
    .replace(
      /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
    )
    // 裸链接（模型经常直接甩 URL）
    .replace(
      /(^|[\s(])(https?:\/\/[^\s<)]+)/g,
      '$1<a href="$2" target="_blank" rel="noopener noreferrer">$2</a>'
    );

  return text.replace(/\u0000(\d+)\u0000/g, (_all, index: string) => {
    return `<code class="md-inline">${codes[Number(index)]}</code>`;
  });
}

const RE_FENCE = /^\s*```(\S*)\s*$/;
const RE_HEADING = /^(#{1,6})\s+(.*)$/;
const RE_HR = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;
const RE_QUOTE = /^\s*>\s?(.*)$/;
const RE_UL = /^\s*[-*+]\s+(.*)$/;
const RE_OL = /^\s*(\d+)[.)]\s+(.*)$/;
const RE_TABLE_SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function isBlockStart(line: string): boolean {
  return (
    RE_FENCE.test(line) ||
    RE_HEADING.test(line) ||
    RE_HR.test(line) ||
    RE_QUOTE.test(line) ||
    RE_UL.test(line) ||
    RE_OL.test(line)
  );
}

function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

export function renderMarkdown(source: string): string {
  if (!source) return "";

  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  const out: string[] = [];
  let i = 0;
  let openList: "ul" | "ol" | null = null;

  const closeList = (): void => {
    if (openList) {
      out.push(`</${openList}>`);
      openList = null;
    }
  };

  while (i < lines.length) {
    const line = lines[i];

    // ---- 围栏代码块（未闭合时按到文末处理，流式中途也不会丢字）----
    const fence = line.match(RE_FENCE);
    if (fence) {
      closeList();
      const lang = fence[1];
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !RE_FENCE.test(lines[i])) {
        body.push(lines[i]);
        i += 1;
      }
      i += 1; // 跳过闭合围栏；没闭合就走到末尾
      const cls = lang ? ` class="language-${escapeHtml(lang)}"` : "";
      out.push(`<pre class="md-pre"><code${cls}>${escapeHtml(body.join("\n"))}</code></pre>`);
      continue;
    }

    // ---- 空行 ----
    if (!line.trim()) {
      closeList();
      i += 1;
      continue;
    }

    // ---- 标题 ----
    const heading = line.match(RE_HEADING);
    if (heading) {
      closeList();
      const level = heading[1].length;
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      i += 1;
      continue;
    }

    // ---- 分隔线 ----
    if (RE_HR.test(line)) {
      closeList();
      out.push('<hr class="md-hr" />');
      i += 1;
      continue;
    }

    // ---- 表格：当前行是表头、下一行是分隔行 ----
    if (line.includes("|") && i + 1 < lines.length && RE_TABLE_SEP.test(lines[i + 1])) {
      closeList();
      const head = splitRow(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
        rows.push(splitRow(lines[i]));
        i += 1;
      }
      const thead = `<thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead>`;
      const tbody = rows.length
        ? `<tbody>${rows
            .map((row) => `<tr>${row.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`)
            .join("")}</tbody>`
        : "";
      out.push(`<div class="md-table-wrap"><table>${thead}${tbody}</table></div>`);
      continue;
    }

    // ---- 引用 ----
    if (RE_QUOTE.test(line)) {
      closeList();
      const body: string[] = [];
      while (i < lines.length && RE_QUOTE.test(lines[i])) {
        body.push(lines[i].match(RE_QUOTE)?.[1] ?? "");
        i += 1;
      }
      out.push(`<blockquote>${body.map((l) => inline(l)).join("<br />")}</blockquote>`);
      continue;
    }

    // ---- 列表（连续同类项归到同一个 <ul>/<ol>）----
    const ul = line.match(RE_UL);
    const ol = line.match(RE_OL);
    if (ul || ol) {
      const kind: "ul" | "ol" = ul ? "ul" : "ol";
      if (openList !== kind) {
        closeList();
        out.push(`<${kind}>`);
        openList = kind;
      }
      out.push(`<li>${inline(ul ? ul[1] : (ol as RegExpMatchArray)[2])}</li>`);
      i += 1;
      continue;
    }

    // ---- 段落：一直吃到空行或下一个块级语法的开头 ----
    closeList();
    const para: string[] = [line];
    i += 1;
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i])) {
      // 表格分隔行单独判断一次，避免把表格吞进段落
      if (lines[i].includes("|") && RE_TABLE_SEP.test(lines[i])) break;
      para.push(lines[i]);
      i += 1;
    }
    out.push(`<p>${para.map((l) => inline(l)).join("<br />")}</p>`);
  }

  closeList();
  return out.join("\n");
}

/** 从 `* 标题 : https://...` 形式的来源摘要里抽出 { title, url }。 */
export interface ParsedSource {
  title: string;
  url: string;
}

export function parseSources(summary: string | undefined): ParsedSource[] {
  if (!summary) return [];
  const seen = new Set<string>();
  const list: ParsedSource[] = [];

  for (const line of summary.split("\n")) {
    const match = line.match(/^\s*[-*]\s*(.*?)\s*:\s*(https?:\/\/\S+)\s*$/);
    if (!match) continue;
    const url = match[2];
    if (seen.has(url)) continue;
    seen.add(url);
    list.push({ title: match[1] || url, url });
  }
  return list;
}

/** 站点图标用文字代替，省一次外部请求（也避免离线时碎图）。 */
export function siteLabel(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

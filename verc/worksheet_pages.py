"""Turn the workbook's Markdown into small HTML pages for the "Your task today" scenes.

Each "## Worksheet N: Name" section becomes one page, keyed by N. The video
shows the top of the page on a tilted sheet, so no Word or PDF tools are needed.
"""

from __future__ import annotations

import html
import re

HEAD_RE = re.compile(r"^##\s+Worksheet\s+(\d+)\s*:\s*(.+)$")


def inline(text: str) -> str:
    t = html.escape(text.strip())
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<i>\1</i>", t)
    t = re.sub(r"\[VERIFY[^\]]*\]", "", t)
    return t


def table_html(rows: list[str]) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    if len(cells) >= 2 and all(re.fullmatch(r":?-{2,}:?", c) for c in cells[1]):
        head, body = cells[0], cells[2:]
    else:
        head, body = None, cells
    out = ["<table>"]
    if head:
        out.append("<tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr>")
    for r in body[:8]:
        ex = r and r[0].lower().startswith("example")
        out.append("<tr>" + "".join(f'<td{" class=ex" if ex else ""}>{inline(c)}</td>' for c in r) + "</tr>")
    out.append("</table>")
    return "".join(out)


def section_html(lines: list[str]) -> str:
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(table_html(rows))
            continue
        m = re.match(r"\[\[LINES\s+(\d+)\]\]", line.strip())
        if m:
            out.append("".join('<div class="ln"></div>' for _ in range(min(int(m.group(1)), 6))))
        elif line.startswith("### "):
            out.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("> "):
            out.append(f"<blockquote>{inline(line[2:])}</blockquote>")
        elif re.match(r"^\d+\.\s", line):
            items = []
            while i < len(lines) and re.match(r"^\d+\.\s", lines[i]):
                text = re.sub(r"^\d+\.\s", "", lines[i])
                items.append(f"<li>{inline(text)}</li>")
                i += 1
            out.append("<ol>" + "".join(items) + "</ol>")
            continue
        elif line.startswith("- [ ]"):
            items = []
            while i < len(lines) and lines[i].startswith("- [ ]"):
                items.append(f"<li>{inline(lines[i][5:])}</li>")
                i += 1
            out.append('<ul class="cb">' + "".join(items) + "</ul>")
            continue
        elif line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{inline(lines[i][2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        else:
            out.append(f"<p>{inline(line)}</p>")
        i += 1
    return "".join(out)


def workbook_pages(markdown: str) -> dict[str, str]:
    pages: dict[str, str] = {}
    current, title, body = None, "", []
    for line in markdown.splitlines() + ["## end"]:
        if line.startswith("## "):
            if current:
                pages[current] = f"<h2>Worksheet {current}: {inline(title)}</h2>" + section_html(body)
            m = HEAD_RE.match(line)
            current, title, body = (m.group(1), m.group(2), []) if m else (None, "", [])
        elif current:
            body.append(line)
    return pages

